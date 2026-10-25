"""Stage 8 product index.

Jobs and feedback rows live in a private in-memory SQLite database. The async
functions are driven through a sync session adapter. These tests do not call
``create_engine`` on ``settings.postgres_dsn``, do not open the project
Postgres, Qdrant, or Ollama, and do not rewrite holdout or cleaned.jsonl.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import DefaultClause

from app.db.base import Base
from app.db.models import (
    BucketDocument,
    DocumentAclEntry,
    DocumentAsset,
    DocumentIndexingJob,
    FeedbackItem,
    KnowledgeBucket,
)
from app.services.document_indexing_service import (
    DocumentIndexingService,
    assert_product_qdrant_target,
    ensure_feedback_product_document,
    enqueue_feedback_product_job,
    open_product_qdrant_store,
)
from app.services.feedback_rules import (
    CORPUS_ID_PREFIX,
    INDEX_TEXT_MAX_CHARS,
    FeedbackCleanedRow,
    FeedbackSourceRow,
    bind_feedback_items_to_document,
    feedback_product_document_id,
    seed_feedback_items,
)
from app.services.sql_schema_card import DEFAULT_SQL_TOOL_ALLOWED_TABLES, build_schema_card

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "build_feedback_corpus.py"
HOLDOUT_PATH = REPO_ROOT / "data" / "feedback" / "v1" / "holdout.jsonl"
CLEANED_PATH = REPO_ROOT / "data" / "feedback" / "v1" / "cleaned.jsonl"
SQL_TOOL_PATH = BACKEND_ROOT / "app" / "services" / "tools" / "execute_readonly_sql.py"

DEMO_TENANT = "local_demo"
DEMO_BUCKET = "taskflow_seed"
PRODUCT_DOCUMENT_ID = "806b53c9-fea8-550e-b555-02f482cbf352"
SYSTEM_OWNER = "system-seed"

TENANT_ID = "tenant-a"
OTHER_TENANT = "other-tenant"
BUCKET_ID = "bucket-a"
OTHER_BUCKET = "bucket-b"
FOREIGN_BUCKET = "bucket-foreign"
DOC_ID = "doc-product"
OTHER_DOC_ID = "doc-other"
JOB_ID = "job-product"
KEPT_SOURCE_PATH = "storage://local_demo/kept/original-feedback.txt"
KEPT_BUCKET_NAME = "kept-bucket-name"
FILE_TEXT = "FILE_SHOULD_NOT_ENTER_POINTS"
BROWSER_KEY = "sk-browser-stage8-do-not-log"
NOISE_TEXT = "Класс!"
CHURN_TEXT = "Удаляю"
BUG_OFF_TEXT = "BUG_FLAG_FALSE_SHOULD_STAY"
FEATURE_TEXT = "FEATURE_SHOULD_INDEX"
EMPTY_TEXT = ""
FOREIGN_TEXT = "FOREIGN_TENANT_SHOULD_STAY"
OTHER_DOC_TEXT = "OTHER_DOC_SHOULD_STAY"
LONG_TAIL = "LONG_TAIL_SHOULD_NOT_INDEX"
BUG_CORPUS_ID = "fb-v1-0007"
FEATURE_ROW_ID = "feature-yes"


def _first_holdout_text() -> str:
    line = HOLDOUT_PATH.read_text(encoding="utf-8").splitlines()[0]
    text = json.loads(line)["text"]
    if not isinstance(text, str) or not text.strip():
        raise AssertionError("holdout first row has no text")
    return text


HOLDOUT_TEXT = _first_holdout_text()
BUG_TEXT = f"BUG_SHOULD_INDEX {'x' * INDEX_TEXT_MAX_CHARS} {LONG_TAIL}"


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):  # noqa: ANN001
    del type_, compiler, kw
    return "JSON"


class _AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def __aenter__(self) -> _AsyncSessionAdapter:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        try:
            if exc_type is not None:
                self._session.rollback()
        finally:
            self._session.close()
        return False

    async def scalar(self, statement):  # noqa: ANN001
        return self._session.scalar(statement)

    async def scalars(self, statement):  # noqa: ANN001
        return self._session.scalars(statement)

    async def execute(self, statement, params=None, **kwargs):  # noqa: ANN001
        return self._session.execute(statement, params, **kwargs)

    async def commit(self) -> None:
        self._session.commit()

    async def flush(self) -> None:
        self._session.flush()

    def add(self, instance: object) -> None:
        self._session.add(instance)

    def add_all(self, instances: list[object]) -> None:
        self._session.add_all(instances)


class RecordingStorage:
    def __init__(self, text: str = FILE_TEXT) -> None:
        self.refs: list[str] = []
        self._text = text

    def materialize(self, ref: str, destination: Path) -> Path:
        self.refs.append(ref)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self._text, encoding="utf-8")
        return destination


class RecordingQdrant:
    def __init__(self) -> None:
        self.upserts: list[list[tuple[str, list[float], dict[str, object]]]] = []
        self.ensured = 0

    def ensure_collection(self, vector_size: int, recreate: bool = False) -> None:
        del vector_size, recreate
        self.ensured += 1

    def upsert_chunks(self, pending) -> None:  # noqa: ANN001
        self.upserts.append(list(pending))


class RecordingEmbed:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(self, model: str, content: str) -> list[float]:
        del model
        self.texts.append(content)
        return [0.25, 0.5, 0.75]


def _make_engine():
    column = DocumentIndexingJob.__table__.c.owner_roles_json
    saved_default = column.server_default
    column.server_default = DefaultClause(text("'[]'"))
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        assert engine.dialect.name == "sqlite"
        Base.metadata.create_all(
            engine,
            tables=[
                KnowledgeBucket.__table__,
                DocumentAsset.__table__,
                DocumentAclEntry.__table__,
                BucketDocument.__table__,
                DocumentIndexingJob.__table__,
                FeedbackItem.__table__,
            ],
        )
    finally:
        column.server_default = saved_default
    return engine


def _session_factory(engine):
    def factory():
        return _AsyncSessionAdapter(Session(engine, expire_on_commit=False))

    return factory


@pytest.fixture()
def indexing_db():
    engine = _make_engine()
    try:
        yield engine, _session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _do_not_touch_project_services(monkeypatch: pytest.MonkeyPatch):
    """Fail if a test dials Postgres or constructs a real Qdrant client."""

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError(f"project service opened: {args[:1]!r} {kwargs!r}")

    monkeypatch.setattr("app.db.session.create_engine", _boom)
    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", _boom)
    monkeypatch.setattr("qdrant_client.QdrantClient", _boom)
    monkeypatch.setattr("app.clients.qdrant_store.QdrantClient", _boom)

    before = {path: path.read_bytes() for path in (HOLDOUT_PATH, CLEANED_PATH)}
    yield
    after = {path: path.read_bytes() for path in (HOLDOUT_PATH, CLEANED_PATH)}
    assert after == before


def _service(factory, storage, qdrant, embed) -> DocumentIndexingService:
    return DocumentIndexingService(
        session_factory=factory,  # type: ignore[arg-type]
        qdrant_store=qdrant,  # type: ignore[arg-type]
        ollama_client=embed,  # type: ignore[arg-type]
        embedding_model="nomic-embed-text",
        object_storage=storage,  # type: ignore[arg-type]
        image_vision_enabled=False,
    )


def _as_json(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _add_bucket(
    session: Session,
    *,
    bucket_id: str,
    tenant_id: str,
    name: str | None = None,
) -> None:
    session.add(
        KnowledgeBucket(
            id=bucket_id,
            tenant_id=tenant_id,
            name=name or bucket_id,
            description="",
            status="ready",
            metadata_json={},
        )
    )


def _add_document(
    session: Session,
    *,
    document_id: str,
    tenant_id: str,
    source_path: str,
    visibility: str = "tenant",
    owner_user_id: str = SYSTEM_OWNER,
) -> None:
    session.add(
        DocumentAsset(
            id=document_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            title="fb-v1.txt",
            file_name="fb-v1.txt",
            source_type="feedback_corpus",
            source_path=source_path,
            status="uploaded",
            visibility=visibility,
            allowed_roles=[],
            size_bytes=0,
            metadata_json={},
        )
    )


def _add_link(session: Session, *, document_id: str, bucket_id: str, tenant_id: str) -> None:
    session.add(
        BucketDocument(
            tenant_id=tenant_id,
            bucket_id=bucket_id,
            document_id=document_id,
            added_by_user_id=SYSTEM_OWNER,
            indexing_status="pending",
        )
    )


def _add_job(
    session: Session,
    *,
    document_id: str,
    bucket_id: str,
    tenant_id: str,
    metadata: dict[str, object] | None = None,
) -> None:
    session.add(
        DocumentIndexingJob(
            id=JOB_ID,
            tenant_id=tenant_id,
            bucket_id=bucket_id,
            document_id=document_id,
            status="pending",
            owner_user_id=SYSTEM_OWNER,
            owner_roles_json=[],
            metadata_json=metadata or {"source": "bucket_commit"},
        )
    )


def _add_feedback(
    session: Session,
    *,
    item_id: str,
    feedback_class: str,
    body: str,
    index_in_rag: bool,
    created_at: datetime,
    document_id: str | None,
    tenant_id: str = TENANT_ID,
    bucket_id: str = BUCKET_ID,
    corpus_id: str | None = None,
) -> None:
    session.add(
        FeedbackItem(
            id=item_id,
            tenant_id=tenant_id,
            bucket_id=bucket_id,
            document_id=document_id,
            feedback_class=feedback_class,
            body=body,
            index_in_rag=index_in_rag,
            corpus_id=corpus_id,
            created_at=created_at,
        )
    )


def _cleaned_row(
    *,
    corpus_id: str,
    text: str,
    rule_class: str,
    index_in_rag: bool,
    rule_reason: str,
) -> FeedbackCleanedRow:
    return FeedbackCleanedRow(
        source=FeedbackSourceRow(
            corpus_id=corpus_id,
            generator_class=rule_class,
            scenario_id=None,
            text=text,
            source_file="memory.jsonl",
            source_line=1,
            is_exact_duplicate=False,
            duplicate_of=None,
        ),
        rule_class=rule_class,
        index_in_rag=index_in_rag,
        rule_reason=rule_reason,
        index_text=text,
        index_text_truncated=False,
    )


def _record_qdrant(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    constructed: list[tuple[object, ...]] = []

    class _RecordingClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            constructed.append(("QdrantClient", args, kwargs))

    class _RecordingStore:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            constructed.append(("QdrantStore", args, kwargs))

    monkeypatch.setattr("qdrant_client.QdrantClient", _RecordingClient)
    monkeypatch.setattr("app.clients.qdrant_store.QdrantClient", _RecordingClient)
    monkeypatch.setattr("app.services.document_indexing_service.QdrantStore", _RecordingStore)
    return constructed


def test_bucket_points_keep_only_flagged_bug_and_feature(
    indexing_db,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Upsert keeps the flagged bug and feature. Noise, churn, and holdout stay in the table."""

    assert len(BUG_TEXT) > INDEX_TEXT_MAX_CHARS
    assert LONG_TAIL not in BUG_TEXT[:INDEX_TEXT_MAX_CHARS]
    assert HOLDOUT_TEXT not in {NOISE_TEXT, CHURN_TEXT, BUG_TEXT, FEATURE_TEXT}
    engine, factory = indexing_db
    base = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    rows = [
        ("noise-class", "noise", NOISE_TEXT, False, DOC_ID, TENANT_ID, BUCKET_ID, "fb-v1-0001"),
        ("churn-short", "churn_signal", CHURN_TEXT, False, DOC_ID, TENANT_ID, BUCKET_ID, "fb-v1-0002"),
        ("bug-off", "bug", BUG_OFF_TEXT, False, DOC_ID, TENANT_ID, BUCKET_ID, "fb-v1-0003"),
        ("bug-empty", "bug", EMPTY_TEXT, True, DOC_ID, TENANT_ID, BUCKET_ID, "fb-v1-0004"),
        ("bug-yes", "bug", BUG_TEXT, True, DOC_ID, TENANT_ID, BUCKET_ID, BUG_CORPUS_ID),
        ("feature-yes", "feature", FEATURE_TEXT, True, DOC_ID, TENANT_ID, BUCKET_ID, "   "),
        ("noise-holdout", "noise", HOLDOUT_TEXT, False, DOC_ID, TENANT_ID, BUCKET_ID, "fb-v1-0098"),
        ("foreign-tenant", "feature", FOREIGN_TEXT, True, DOC_ID, OTHER_TENANT, FOREIGN_BUCKET, "fb-v1-0005"),
        ("other-doc", "feature", OTHER_DOC_TEXT, True, OTHER_DOC_ID, TENANT_ID, BUCKET_ID, "fb-v1-0006"),
    ]
    with Session(engine) as session:
        _add_bucket(session, bucket_id=BUCKET_ID, tenant_id=TENANT_ID)
        _add_bucket(session, bucket_id=FOREIGN_BUCKET, tenant_id=OTHER_TENANT)
        _add_document(session, document_id=DOC_ID, tenant_id=TENANT_ID, source_path="feedback://tenant-a/bucket-a/fb-v1")
        _add_document(
            session,
            document_id=OTHER_DOC_ID,
            tenant_id=TENANT_ID,
            source_path="feedback://tenant-a/bucket-a/other.txt",
        )
        _add_link(session, document_id=DOC_ID, bucket_id=BUCKET_ID, tenant_id=TENANT_ID)
        _add_job(
            session,
            document_id=DOC_ID,
            bucket_id=BUCKET_ID,
            tenant_id=TENANT_ID,
            metadata={"source": "bucket_commit", "provider_api_key": BROWSER_KEY},
        )
        session.flush()
        for offset, row in enumerate(rows):
            item_id, feedback_class, body, index_in_rag, document_id, tenant_id, bucket_id, corpus_id = row
            _add_feedback(
                session,
                item_id=item_id,
                feedback_class=feedback_class,
                body=body,
                index_in_rag=index_in_rag,
                document_id=document_id,
                tenant_id=tenant_id,
                bucket_id=bucket_id,
                corpus_id=corpus_id,
                created_at=base + timedelta(seconds=offset),
            )
        session.commit()

    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    embed = RecordingEmbed()
    service = _service(factory, storage, qdrant, embed)
    caplog.set_level(logging.DEBUG, logger="app.services.document_indexing_service")

    asyncio.run(service.process_job(JOB_ID, message_tenant_id=TENANT_ID))

    with Session(engine) as session:
        job = session.get(DocumentIndexingJob, JOB_ID)
        document = session.get(DocumentAsset, DOC_ID)
        link = session.scalar(
            select(BucketDocument).where(
                BucketDocument.tenant_id == TENANT_ID,
                BucketDocument.bucket_id == BUCKET_ID,
                BucketDocument.document_id == DOC_ID,
            )
        )
        stored = {row.id: row for row in session.scalars(select(FeedbackItem)).all()}
    assert job is not None and document is not None and link is not None
    assert job.status == "completed"
    assert job.chunks_indexed == 2
    assert job.failed_stage is None
    assert job.error is None
    assert document.status == "indexed"
    assert link.indexing_status == "indexed"
    assert storage.refs == []
    assert qdrant.ensured == 1
    assert len(qdrant.upserts) == 1
    payloads = [item[2] for item in qdrant.upserts[0]]
    assert [payload["feedback_item_id"] for payload in payloads] == ["bug-yes", FEATURE_ROW_ID]
    assert [payload["feedback_class"] for payload in payloads] == ["bug", "feature"]
    assert {payload["feedback_class"] for payload in payloads} == {"bug", "feature"}
    assert [payload["title"] for payload in payloads] == [BUG_CORPUS_ID, FEATURE_ROW_ID]
    assert payloads[0]["content"] == BUG_TEXT.strip()[:INDEX_TEXT_MAX_CHARS]
    assert payloads[1]["content"] == FEATURE_TEXT
    assert embed.texts == [payload["content"] for payload in payloads]
    assert "" not in embed.texts
    for payload in payloads:
        assert payload["source_type"] == "feedback"
        assert payload["index_in_rag"] is True
        assert payload["synthetic"] is True
        assert payload["document_metadata"]["synthetic"] is True
        assert payload["document_id"] == DOC_ID
        assert payload["tenant_id"] == TENANT_ID
        assert payload["bucket_id"] == BUCKET_ID
    blob = json.dumps(qdrant.upserts, ensure_ascii=False, default=str)
    for secret in (
        NOISE_TEXT,
        CHURN_TEXT,
        HOLDOUT_TEXT,
        BUG_OFF_TEXT,
        FOREIGN_TEXT,
        OTHER_DOC_TEXT,
        LONG_TAIL,
        FILE_TEXT,
        BROWSER_KEY,
    ):
        assert secret not in blob
        assert secret not in caplog.text
    assert "noise" not in {payload["feedback_class"] for payload in payloads}
    assert "churn_signal" not in {payload["feedback_class"] for payload in payloads}
    assert stored["noise-class"].body == NOISE_TEXT
    assert stored["noise-class"].feedback_class == "noise"
    assert stored["noise-class"].index_in_rag is False
    assert stored["churn-short"].body == CHURN_TEXT
    assert stored["churn-short"].feedback_class == "churn_signal"
    assert stored["churn-short"].index_in_rag is False
    assert stored["noise-holdout"].body == HOLDOUT_TEXT
    assert stored["noise-holdout"].feedback_class == "noise"
    assert stored["bug-off"].index_in_rag is False
    assert stored["bug-empty"].body == ""
    assert stored["bug-empty"].index_in_rag is True
    assert stored["bug-yes"].index_in_rag is True
    assert stored["feature-yes"].index_in_rag is True
    assert stored["foreign-tenant"].body == FOREIGN_TEXT
    assert stored["other-doc"].body == OTHER_DOC_TEXT
    assert {row.feedback_class for row in stored.values()} >= {"noise", "churn_signal", "bug", "feature"}


def test_seed_leaves_document_id_empty_and_bind_only_fb_v1_rows(
    indexing_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seed keeps document_id empty. Bind writes it only on this bucket's fb-v1 rows."""

    constructed = _record_qdrant(monkeypatch)
    engine, factory = indexing_db
    product_document_id = feedback_product_document_id(tenant_id=DEMO_TENANT, bucket_id=DEMO_BUCKET)
    seeded = (
        _cleaned_row(
            corpus_id="fb-v1-0001",
            text="SEEDED_BUG",
            rule_class="bug",
            index_in_rag=True,
            rule_reason="keep_generator",
        ),
        _cleaned_row(
            corpus_id="fb-v1-0002",
            text="SEEDED_NOISE",
            rule_class="noise",
            index_in_rag=False,
            rule_reason="lexicon_noise",
        ),
    )
    with Session(engine) as session:
        _add_bucket(session, bucket_id=DEMO_BUCKET, tenant_id=DEMO_TENANT, name=KEPT_BUCKET_NAME)
        _add_bucket(session, bucket_id=OTHER_BUCKET, tenant_id=DEMO_TENANT)
        _add_bucket(session, bucket_id=FOREIGN_BUCKET, tenant_id=OTHER_TENANT)
        _add_document(
            session,
            document_id=product_document_id,
            tenant_id=DEMO_TENANT,
            source_path=KEPT_SOURCE_PATH,
        )
        _add_document(
            session,
            document_id=OTHER_DOC_ID,
            tenant_id=DEMO_TENANT,
            source_path="storage://local_demo/other.txt",
        )
        session.flush()
        _add_feedback(
            session,
            item_id="old-bug",
            feedback_class="bug",
            body="OLD_BUG_SHOULD_BE_REPLACED",
            index_in_rag=True,
            document_id=OTHER_DOC_ID,
            tenant_id=DEMO_TENANT,
            bucket_id=DEMO_BUCKET,
            corpus_id="fb-v1-0001",
            created_at=datetime(2026, 10, 25, 8, 0, tzinfo=UTC),
        )
        _add_feedback(
            session,
            item_id="manual-row",
            feedback_class="noise",
            body="MANUAL_SHOULD_STAY",
            index_in_rag=False,
            document_id=OTHER_DOC_ID,
            tenant_id=DEMO_TENANT,
            bucket_id=DEMO_BUCKET,
            corpus_id="note-9",
            created_at=datetime(2026, 10, 25, 8, 1, tzinfo=UTC),
        )
        _add_feedback(
            session,
            item_id="no-corpus",
            feedback_class="feature",
            body="NO_CORPUS_SHOULD_STAY",
            index_in_rag=True,
            document_id=OTHER_DOC_ID,
            tenant_id=DEMO_TENANT,
            bucket_id=DEMO_BUCKET,
            corpus_id=None,
            created_at=datetime(2026, 10, 25, 8, 2, tzinfo=UTC),
        )
        _add_feedback(
            session,
            item_id="other-bucket",
            feedback_class="bug",
            body="OTHER_BUCKET_SHOULD_STAY",
            index_in_rag=True,
            document_id=OTHER_DOC_ID,
            tenant_id=DEMO_TENANT,
            bucket_id=OTHER_BUCKET,
            corpus_id="fb-v1-0001",
            created_at=datetime(2026, 10, 25, 8, 3, tzinfo=UTC),
        )
        _add_feedback(
            session,
            item_id="foreign-tenant",
            feedback_class="feature",
            body=FOREIGN_TEXT,
            index_in_rag=True,
            document_id=None,
            tenant_id=OTHER_TENANT,
            bucket_id=FOREIGN_BUCKET,
            corpus_id="fb-v1-0001",
            created_at=datetime(2026, 10, 25, 8, 4, tzinfo=UTC),
        )
        session.commit()

    async def _seed() -> int:
        async with factory() as session:
            inserted = await seed_feedback_items(
                session,
                tenant_id=DEMO_TENANT,
                bucket_id=DEMO_BUCKET,
                cleaned_rows=seeded,
            )
            await session.commit()
            return inserted

    assert asyncio.run(_seed()) == 2
    with Session(engine) as session:
        target = session.scalars(
            select(FeedbackItem).where(
                FeedbackItem.tenant_id == DEMO_TENANT,
                FeedbackItem.bucket_id == DEMO_BUCKET,
                FeedbackItem.corpus_id.like(f"{CORPUS_ID_PREFIX}%"),
            )
        ).all()
        manual = session.get(FeedbackItem, "manual-row")
        bare = session.get(FeedbackItem, "no-corpus")
        other_bucket = session.get(FeedbackItem, "other-bucket")
        foreign = session.get(FeedbackItem, "foreign-tenant")
    assert session_ids(target) == {"fb-v1-0001", "fb-v1-0002"}
    assert {row.document_id for row in target} == {None}
    assert {row.body for row in target} == {"SEEDED_BUG", "SEEDED_NOISE"}
    assert manual is not None and manual.document_id == OTHER_DOC_ID and manual.body == "MANUAL_SHOULD_STAY"
    assert bare is not None and bare.document_id == OTHER_DOC_ID and bare.corpus_id is None
    assert other_bucket is not None and other_bucket.document_id == OTHER_DOC_ID
    assert foreign is not None and foreign.document_id is None and foreign.body == FOREIGN_TEXT

    assert asyncio.run(_seed()) == 2
    with Session(engine) as session:
        target_again = session.scalars(
            select(FeedbackItem).where(
                FeedbackItem.tenant_id == DEMO_TENANT,
                FeedbackItem.bucket_id == DEMO_BUCKET,
                FeedbackItem.corpus_id.like(f"{CORPUS_ID_PREFIX}%"),
            )
        ).all()
        manual_again = session.get(FeedbackItem, "manual-row")
    assert len(target_again) == 2
    assert len({row.corpus_id for row in target_again}) == 2
    assert {row.document_id for row in target_again} == {None}
    assert manual_again is not None and manual_again.document_id == OTHER_DOC_ID

    async def _bind() -> int:
        async with factory() as session:
            updated = await bind_feedback_items_to_document(
                session,
                tenant_id=DEMO_TENANT,
                bucket_id=DEMO_BUCKET,
                document_id=product_document_id,
            )
            await session.commit()
            return updated

    assert asyncio.run(_bind()) == 2
    with Session(engine) as session:
        bound = session.scalars(
            select(FeedbackItem).where(
                FeedbackItem.tenant_id == DEMO_TENANT,
                FeedbackItem.bucket_id == DEMO_BUCKET,
                FeedbackItem.corpus_id.like(f"{CORPUS_ID_PREFIX}%"),
            )
        ).all()
        manual = session.get(FeedbackItem, "manual-row")
        bare = session.get(FeedbackItem, "no-corpus")
        other_bucket = session.get(FeedbackItem, "other-bucket")
        foreign = session.get(FeedbackItem, "foreign-tenant")
        buckets = session.scalar(select(func.count()).select_from(KnowledgeBucket))
    assert {row.document_id for row in bound} == {product_document_id}
    assert {row.corpus_id for row in bound} == {"fb-v1-0001", "fb-v1-0002"}
    assert manual is not None and manual.document_id == OTHER_DOC_ID and manual.corpus_id == "note-9"
    assert bare is not None and bare.document_id == OTHER_DOC_ID and bare.corpus_id is None
    assert other_bucket is not None and other_bucket.document_id == OTHER_DOC_ID
    assert other_bucket.bucket_id == OTHER_BUCKET
    assert foreign is not None and foreign.document_id is None and foreign.tenant_id == OTHER_TENANT
    assert buckets == 3
    assert constructed == []


def session_ids(rows: list[FeedbackItem]) -> set[str | None]:
    return {row.corpus_id for row in rows}


@pytest.mark.parametrize(
    ("collection_name", "embedding_model"),
    [
        pytest.param("feedback_eval_v1", "nomic-embed-text", id="eval-collection"),
        pytest.param("other-collection", "nomic-embed-text", id="other-collection"),
        pytest.param("", "nomic-embed-text", id="empty-collection"),
        pytest.param("   ", "nomic-embed-text", id="blank-collection"),
        pytest.param("Documents", "nomic-embed-text", id="wrong-case-collection"),
        pytest.param("documents", "qwen3.5:9b", id="other-embedding"),
        pytest.param("documents", "", id="empty-embedding"),
        pytest.param("documents", "nomic-embed-text:latest", id="tagged-embedding"),
    ],
)
def test_refused_collection_or_embedding_does_not_construct_qdrant(
    monkeypatch: pytest.MonkeyPatch,
    collection_name: str,
    embedding_model: str,
) -> None:
    """The script guard refuses a bad target before any Qdrant client exists."""

    script = SCRIPT_PATH.read_text(encoding="utf-8")
    assert script.index("assert_product_qdrant_target(") < script.index("QdrantClient(")
    constructed = _record_qdrant(monkeypatch)
    with pytest.raises(ValueError, match="refusing product index"):
        assert_product_qdrant_target(collection_name=collection_name, embedding_model=embedding_model)
    with pytest.raises(ValueError, match="refusing product index"):
        open_product_qdrant_store(
            url="http://127.0.0.1:9",
            collection_name=collection_name,
            embedding_model=embedding_model,
            check_compatibility=False,
        )
    assert constructed == []


def test_documents_nomic_target_is_accepted_without_constructing_qdrant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """documents plus nomic-embed-text passes the guard and does not open Qdrant."""

    constructed = _record_qdrant(monkeypatch)
    assert_product_qdrant_target(collection_name="documents", embedding_model="nomic-embed-text")
    assert_product_qdrant_target(collection_name="  documents  ", embedding_model="  nomic-embed-text  ")
    assert constructed == []


def test_feedback_product_document_id_for_local_demo_seed() -> None:
    """The demo bucket's product document id is stable."""

    assert (
        feedback_product_document_id(tenant_id="local_demo", bucket_id="taskflow_seed")
        == PRODUCT_DOCUMENT_ID
    )


def test_ensure_missing_bucket_does_not_create_knowledge_bucket(indexing_db) -> None:
    """A missing bucket raises and leaves knowledge_buckets empty."""

    _engine, factory = indexing_db

    async def _run() -> tuple[int, int, int]:
        async with factory() as session:
            with pytest.raises(ValueError, match="refusing to create"):
                await ensure_feedback_product_document(
                    session,
                    tenant_id=DEMO_TENANT,
                    bucket_id=DEMO_BUCKET,
                    document_id=PRODUCT_DOCUMENT_ID,
                    owner_user_id=SYSTEM_OWNER,
                )
            buckets = await session.scalar(select(func.count()).select_from(KnowledgeBucket))
            assets = await session.scalar(select(func.count()).select_from(DocumentAsset))
            jobs = await session.scalar(select(func.count()).select_from(DocumentIndexingJob))
            return int(buckets or 0), int(assets or 0), int(jobs or 0)

    buckets, assets, jobs = asyncio.run(_run())
    assert buckets == 0
    assert assets == 0
    assert jobs == 0


def test_ensure_foreign_tenant_bucket_is_not_replaced(indexing_db) -> None:
    """A bucket owned by another tenant is not retargeted or duplicated."""

    engine, factory = indexing_db
    with Session(engine) as session:
        _add_bucket(session, bucket_id=DEMO_BUCKET, tenant_id=OTHER_TENANT, name=KEPT_BUCKET_NAME)
        session.commit()

    async def _run() -> None:
        async with factory() as session:
            with pytest.raises(ValueError, match="refusing to create"):
                await ensure_feedback_product_document(
                    session,
                    tenant_id=DEMO_TENANT,
                    bucket_id=DEMO_BUCKET,
                    document_id=PRODUCT_DOCUMENT_ID,
                    owner_user_id=SYSTEM_OWNER,
                )

    asyncio.run(_run())
    with Session(engine) as session:
        buckets = session.scalars(select(KnowledgeBucket)).all()
        assets = session.scalar(select(func.count()).select_from(DocumentAsset))
    assert len(buckets) == 1
    assert buckets[0].id == DEMO_BUCKET
    assert buckets[0].tenant_id == OTHER_TENANT
    assert buckets[0].name == KEPT_BUCKET_NAME
    assert assets == 0


def test_existing_asset_keeps_path_and_job_is_pending_bucket_commit(indexing_db) -> None:
    """An existing tenant asset keeps its path. The new job is a pending bucket commit."""

    engine, factory = indexing_db
    document_id = feedback_product_document_id(tenant_id=DEMO_TENANT, bucket_id=DEMO_BUCKET)
    assert document_id == PRODUCT_DOCUMENT_ID
    with Session(engine) as session:
        _add_bucket(session, bucket_id=DEMO_BUCKET, tenant_id=DEMO_TENANT, name=KEPT_BUCKET_NAME)
        _add_document(
            session,
            document_id=document_id,
            tenant_id=DEMO_TENANT,
            source_path=KEPT_SOURCE_PATH,
            visibility="tenant",
            owner_user_id="asset-owner",
        )
        session.commit()

    async def _run() -> str:
        async with factory() as session:
            await ensure_feedback_product_document(
                session,
                tenant_id=DEMO_TENANT,
                bucket_id=DEMO_BUCKET,
                document_id=document_id,
                owner_user_id=SYSTEM_OWNER,
            )
            job_id = await enqueue_feedback_product_job(
                session,
                tenant_id=DEMO_TENANT,
                bucket_id=DEMO_BUCKET,
                document_id=document_id,
                owner_user_id=SYSTEM_OWNER,
            )
            await session.commit()
            return job_id

    job_id = asyncio.run(_run())
    with Session(engine) as session:
        buckets = session.scalars(select(KnowledgeBucket)).all()
        asset = session.get(DocumentAsset, document_id)
        jobs = session.scalars(select(DocumentIndexingJob)).all()
    assert len(buckets) == 1
    assert buckets[0].id == DEMO_BUCKET
    assert buckets[0].tenant_id == DEMO_TENANT
    assert buckets[0].name == KEPT_BUCKET_NAME
    assert asset is not None
    assert asset.source_path == KEPT_SOURCE_PATH
    assert asset.visibility == "tenant"
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == job_id
    assert job.status == "pending"
    assert job.owner_user_id == SYSTEM_OWNER
    assert _as_json(job.owner_roles_json) == []
    assert _as_json(job.metadata_json) == {"source": "bucket_commit"}
    assert job.tenant_id == DEMO_TENANT
    assert job.bucket_id == DEMO_BUCKET
    assert job.document_id == document_id


def test_feedback_items_stay_out_of_readonly_sql() -> None:
    """The feedback table stays off execute_readonly_sql."""

    assert "feedback_items" not in DEFAULT_SQL_TOOL_ALLOWED_TABLES
    card = build_schema_card(allowed_tables=DEFAULT_SQL_TOOL_ALLOWED_TABLES)
    assert "feedback_items" not in card
    assert "feedback_items" not in SQL_TOOL_PATH.read_text(encoding="utf-8")
