"""Stage 1 indexing worker tests.

Jobs and feedback rows live in a private in-memory SQLite database. The async
service is driven through a sync session adapter, so these tests do not open
the project Postgres and do not call Ollama.
"""

from __future__ import annotations

import ast
import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select, text
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
from app.services.bucket_service import PERSONAL_INDEX_BUCKET_ID
from app.services.document_indexing_service import DocumentIndexingService

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = BACKEND_ROOT / "scripts" / "run_indexing_worker.py"

TENANT_ID = "tenant-a"
BUCKET_ID = "bucket-a"
DOC_ID = "doc-1"
JOB_ID = "job-1"
ASSET_PATH = "storage://tenant-a/documents/notes.txt"
EVIL_PATH = "storage://evil/from-broker-message.txt"
BROKER_USER = "broker-user-should-not-log"
DOC_TEXT = "Короткий текст документа для индексации."
BUG_BODY = "BUG_SHOULD_INDEX"
FEATURE_BODY = "FEATURE_SHOULD_INDEX"
REJECTED_BODIES = (
    "NOISE_SHOULD_STAY",
    "CHURN_SHOULD_STAY",
    "BUG_FLAG_FALSE_SHOULD_STAY",
    "OTHER_DOC_SHOULD_STAY",
    "OTHER_TENANT_SHOULD_STAY",
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):  # noqa: ANN001
    del type_, compiler, kw
    return "JSON"


def _worker_message_tenant_id():
    source = WORKER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "message_tenant_id"
    )
    segment = ast.get_source_segment(source, function)
    assert segment is not None
    namespace: dict[str, object] = {}
    exec(segment, namespace)  # noqa: S102 — load the worker function without importing Kafka.
    return namespace["message_tenant_id"], source, tree


WORKER_MESSAGE_TENANT_ID, _WORKER_SOURCE, WORKER_TREE = _worker_message_tenant_id()


def _broker_payload(**extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "user_id": BROKER_USER,
        "roles": ["admin"],
        "source_path": EVIL_PATH,
    }
    payload.update(extra)
    return payload


def _matching_tenant() -> str:
    tenant_id = WORKER_MESSAGE_TENANT_ID(_broker_payload(tenant_id=f"  {TENANT_ID}  "))
    assert tenant_id == TENANT_ID
    return tenant_id


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

    async def commit(self) -> None:
        self._session.commit()


class RecordingStorage:
    def __init__(self, text: str = DOC_TEXT, *, error: Exception | None = None) -> None:
        self.refs: list[str] = []
        self._text = text
        self._error = error

    def materialize(self, ref: str, destination: Path) -> Path:
        self.refs.append(ref)
        if self._error is not None:
            raise self._error
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self._text, encoding="utf-8")
        return destination


class RecordingQdrant:
    def __init__(self, *, upsert_error: Exception | None = None) -> None:
        self.upserts: list[list] = []
        self.ensured = 0
        self._upsert_error = upsert_error

    def ensure_collection(self, vector_size: int, recreate: bool = False) -> None:
        del vector_size, recreate
        self.ensured += 1

    def upsert_chunks(self, pending) -> None:  # noqa: ANN001
        self.upserts.append(list(pending))
        if self._upsert_error is not None:
            raise self._upsert_error


class RecordingEmbed:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.texts: list[str] = []
        self._error = error

    async def embed(self, model: str, content: str) -> list[float]:
        del model
        self.texts.append(content)
        if self._error is not None:
            raise self._error
        return [0.25, 0.5, 0.75]


class RecordingPublisher:
    def __init__(self) -> None:
        self.indexed: list[dict] = []
        self.failed: list[dict] = []

    async def publish_document_indexed(self, **kwargs):  # noqa: ANN003
        self.indexed.append(kwargs)
        return {"published": True}

    async def publish_document_index_failed(self, **kwargs):  # noqa: ANN003
        self.failed.append(kwargs)
        return {"published": True}


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


def _service(factory, storage, qdrant, embed, publisher=None) -> DocumentIndexingService:
    return DocumentIndexingService(
        session_factory=factory,  # type: ignore[arg-type]
        qdrant_store=qdrant,  # type: ignore[arg-type]
        ollama_client=embed,  # type: ignore[arg-type]
        embedding_model="nomic-embed-text",
        event_publisher=publisher,  # type: ignore[arg-type]
        object_storage=storage,  # type: ignore[arg-type]
        image_vision_enabled=False,
    )


def _add_bucket(session: Session, *, bucket_id: str = BUCKET_ID, tenant_id: str = TENANT_ID) -> None:
    session.add(
        KnowledgeBucket(
            id=bucket_id,
            tenant_id=tenant_id,
            name=bucket_id,
            description="",
            status="ready",
            metadata_json={},
        )
    )


def _add_document(
    session: Session,
    *,
    document_id: str = DOC_ID,
    tenant_id: str = TENANT_ID,
    owner_user_id: str = "owner-real",
    source_path: str = ASSET_PATH,
    status: str = "uploaded",
    error: str | None = None,
) -> None:
    session.add(
        DocumentAsset(
            id=document_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            title="notes.txt",
            file_name="notes.txt",
            source_type="txt",
            source_path=source_path,
            status=status,
            visibility="private",
            allowed_roles=[],
            size_bytes=32,
            error=error,
            metadata_json={},
        )
    )


def _add_link(
    session: Session,
    *,
    document_id: str = DOC_ID,
    bucket_id: str = BUCKET_ID,
    indexing_status: str = "pending",
    indexing_error: str | None = None,
) -> None:
    session.add(
        BucketDocument(
            tenant_id=TENANT_ID,
            bucket_id=bucket_id,
            document_id=document_id,
            added_by_user_id="owner-real",
            indexing_status=indexing_status,
            indexing_error=indexing_error,
        )
    )


def _add_job(
    session: Session,
    *,
    job_id: str = JOB_ID,
    document_id: str = DOC_ID,
    bucket_id: str = BUCKET_ID,
    owner_user_id: str | None = "owner-real",
    owner_roles: list[str] | None = None,
    source: str = "bucket_commit",
    status: str = "pending",
    attempts: int = 0,
    error: str | None = None,
    failed_stage: str | None = None,
) -> None:
    session.add(
        DocumentIndexingJob(
            id=job_id,
            tenant_id=TENANT_ID,
            bucket_id=bucket_id,
            document_id=document_id,
            status=status,
            attempts=attempts,
            chunks_indexed=0,
            error=error,
            failed_stage=failed_stage,
            owner_user_id=owner_user_id,
            owner_roles_json=list(owner_roles or []),
            metadata_json={"source": source},
        )
    )


def _add_feedback(
    session: Session,
    *,
    item_id: str,
    feedback_class: str,
    body: str,
    index_in_rag: bool,
    document_id: str = DOC_ID,
    tenant_id: str = TENANT_ID,
    created_at: datetime,
) -> None:
    session.add(
        FeedbackItem(
            id=item_id,
            tenant_id=tenant_id,
            bucket_id=BUCKET_ID,
            document_id=document_id,
            feedback_class=feedback_class,
            body=body,
            index_in_rag=index_in_rag,
            created_at=created_at,
        )
    )


async def _reload(factory, job_id: str, document_id: str = DOC_ID, bucket_id: str = BUCKET_ID):
    async with factory() as session:
        job = await session.scalar(select(DocumentIndexingJob).where(DocumentIndexingJob.id == job_id))
        document = await session.scalar(select(DocumentAsset).where(DocumentAsset.id == document_id))
        link = await session.scalar(
            select(BucketDocument).where(
                BucketDocument.tenant_id == TENANT_ID,
                BucketDocument.bucket_id == bucket_id,
                BucketDocument.document_id == document_id,
            )
        )
    return job, document, link


def _assert_stage_logs(caplog: pytest.LogCaptureFixture, job_id: str, document_id: str, stage: str) -> None:
    matches = [
        record
        for record in caplog.records
        if record.args and len(record.args) >= 3 and record.args[2] == stage
    ]
    assert matches, caplog.text
    for record in matches:
        assert record.args[0] == job_id
        assert record.args[1] == document_id
    assert BROKER_USER not in caplog.text
    assert EVIL_PATH not in caplog.text


def test_message_tenant_id_ignores_user_role_and_source_path() -> None:
    function_source = _WORKER_SOURCE[
        _WORKER_SOURCE.index("def message_tenant_id") : _WORKER_SOURCE.index("async def run_worker")
    ]
    assert "user_id" not in function_source
    assert "source_path" not in function_source
    payload = _broker_payload(tenant_id="  tenant-a  ")
    assert WORKER_MESSAGE_TENANT_ID(payload) == "tenant-a"
    assert WORKER_MESSAGE_TENANT_ID({}) is None
    assert WORKER_MESSAGE_TENANT_ID({"tenant_id": ""}) is None
    assert WORKER_MESSAGE_TENANT_ID({"tenant_id": "   "}) is None
    assert WORKER_MESSAGE_TENANT_ID({"tenant_id": None}) is None
    assert WORKER_MESSAGE_TENANT_ID({"tenant_id": 7}) is None
    assert WORKER_MESSAGE_TENANT_ID({"tenant_id": ["tenant-a"]}) is None
    assert WORKER_MESSAGE_TENANT_ID({"user_id": "admin-user", "roles": ["admin"], "source_path": EVIL_PATH}) is None


def test_worker_forwards_only_job_ids_and_tenant() -> None:
    calls = [
        node
        for node in ast.walk(WORKER_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "process_jobs"
    ]
    assert len(calls) == 1
    call = calls[0]
    assert len(call.args) == 1
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "clean_ids"
    assert [keyword.arg for keyword in call.keywords] == ["message_tenant_id"]
    value = call.keywords[0].value
    assert isinstance(value, ast.Call)
    assert isinstance(value.func, ast.Name) and value.func.id == "message_tenant_id"
    assert len(value.args) == 1 and isinstance(value.args[0], ast.Name) and value.args[0].id == "payload"


def test_tenant_mismatch_skips_index_and_does_not_log_broker_user(indexing_db, caplog: pytest.LogCaptureFixture) -> None:
    engine, factory = indexing_db
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session)
        _add_job(session, owner_user_id="owner-real", attempts=4)
        session.commit()
    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    service = _service(factory, storage, qdrant, RecordingEmbed(), RecordingPublisher())
    caplog.set_level(logging.WARNING, logger="app.services.document_indexing_service")
    cases = [
        ({}, None),
        ({"tenant_id": ""}, None),
        ({"tenant_id": "   "}, None),
        ({"tenant_id": None}, None),
        ({"tenant_id": 7}, None),
        ({"tenant_id": ["tenant-a"]}, None),
        ({"tenant_id": "other-tenant"}, "other-tenant"),
    ]
    tenants: list[str | None] = []
    for extra, expected in cases:
        extracted = WORKER_MESSAGE_TENANT_ID(_broker_payload(**extra))
        assert extracted == expected
        tenants.append(extracted)
    tenants.extend(["", "   ", "other-tenant"])

    async def _run() -> None:
        for tenant_id in tenants:
            await service.process_job(JOB_ID, message_tenant_id=tenant_id)

    asyncio.run(_run())
    job, document, _link = asyncio.run(_reload(factory, JOB_ID))
    assert job.status == "pending"
    assert job.attempts == 4
    assert job.failed_stage is None
    assert job.error is None
    assert job.document_id == DOC_ID
    assert document.status == "uploaded"
    assert storage.refs == []
    assert qdrant.upserts == []
    assert qdrant.ensured == 0
    _assert_stage_logs(caplog, JOB_ID, DOC_ID, "tenant_check")
    assert len([record for record in caplog.records if record.args and record.args[2] == "tenant_check"]) == len(tenants)


def test_process_job_uses_job_owner_roles_and_asset_source_path(indexing_db, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, factory = indexing_db
    seen: dict[str, object] = {}

    def _spy(*, document, user, acl_entries):  # noqa: ANN001
        del document
        seen["user_id"] = user.user_id
        seen["roles"] = set(user.roles)
        seen["acl_count"] = len(list(acl_entries))
        return True

    monkeypatch.setattr("app.services.document_indexing_service.can_read_document", _spy)
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session, owner_user_id="doc-owner")
        _add_job(session, owner_user_id="job-owner", owner_roles=["analyst"])
        session.commit()
    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    service = _service(factory, storage, qdrant, RecordingEmbed())

    asyncio.run(service.process_job(JOB_ID, message_tenant_id=_matching_tenant()))
    job, _document, _link = asyncio.run(_reload(factory, JOB_ID))
    assert seen == {"user_id": "job-owner", "roles": {"analyst"}, "acl_count": 0}
    assert storage.refs == [ASSET_PATH]
    assert EVIL_PATH not in storage.refs
    assert job.status == "completed"
    assert job.failed_stage is None
    assert qdrant.upserts


def test_owner_can_read_document_without_feedback_rows(indexing_db, caplog: pytest.LogCaptureFixture) -> None:
    engine, factory = indexing_db
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session, owner_user_id="owner-real")
        _add_link(session)
        _add_job(session, owner_user_id="owner-real", owner_roles=[])
        session.commit()
    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    publisher = RecordingPublisher()
    service = _service(factory, storage, qdrant, RecordingEmbed(), publisher)
    caplog.set_level(logging.WARNING, logger="app.services.document_indexing_service")

    asyncio.run(service.process_job(JOB_ID, message_tenant_id=f"  {TENANT_ID}  "))
    job, document, link = asyncio.run(_reload(factory, JOB_ID))
    assert job.status == "completed"
    assert job.chunks_indexed == 1
    assert job.error is None
    assert not job.failed_stage
    assert job.document_id == DOC_ID
    assert document.status == "indexed"
    assert document.error is None
    assert link.indexing_status == "indexed"
    assert storage.refs == [ASSET_PATH]
    assert len(qdrant.upserts) == 1
    assert [item[2]["content"] for item in qdrant.upserts[0]] == [DOC_TEXT]
    assert publisher.failed == []
    assert publisher.indexed[0]["document_id"] == DOC_ID
    assert BROKER_USER not in caplog.text


@pytest.mark.parametrize("owner_user_id", [None, "", "   "])
def test_empty_owner_fails_acl_check_without_storage(
    indexing_db,
    caplog: pytest.LogCaptureFixture,
    owner_user_id: str | None,
) -> None:
    engine, factory = indexing_db
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session, owner_user_id="owner-real")
        _add_link(session)
        _add_job(session, owner_user_id=owner_user_id, source="bucket_commit")
        session.commit()
    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    publisher = RecordingPublisher()
    service = _service(factory, storage, qdrant, RecordingEmbed(), publisher)
    caplog.set_level(logging.WARNING, logger="app.services.document_indexing_service")

    asyncio.run(service.process_job(JOB_ID, message_tenant_id=_matching_tenant()))
    job, document, link = asyncio.run(_reload(factory, JOB_ID))
    assert job.status == "failed"
    assert job.failed_stage == "acl_check"
    assert job.error == "Indexing job has no owner."
    assert job.document_id == DOC_ID
    assert document.status == "index_failed"
    assert link.indexing_status == "index_failed"
    assert storage.refs == []
    assert qdrant.upserts == []
    assert qdrant.ensured == 0
    assert publisher.failed == []
    assert publisher.indexed == []
    _assert_stage_logs(caplog, JOB_ID, DOC_ID, "acl_check")


@pytest.mark.parametrize(
    ("source", "bucket_id", "expect_link"),
    [
        ("bucket_commit", BUCKET_ID, True),
        ("retry_indexing", BUCKET_ID, True),
        ("personal_commit", PERSONAL_INDEX_BUCKET_ID, False),
    ],
)
def test_unreadable_owner_fails_acl_check_without_storage(
    indexing_db,
    caplog: pytest.LogCaptureFixture,
    source: str,
    bucket_id: str,
    expect_link: bool,
) -> None:
    engine, factory = indexing_db
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session, owner_user_id="owner-real")
        if expect_link:
            _add_link(session, bucket_id=bucket_id)
        _add_job(
            session,
            bucket_id=bucket_id,
            owner_user_id="intruder",
            owner_roles=[],
            source=source,
        )
        session.commit()
    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    publisher = RecordingPublisher()
    service = _service(factory, storage, qdrant, RecordingEmbed(), publisher)
    caplog.set_level(logging.WARNING, logger="app.services.document_indexing_service")

    asyncio.run(service.process_job(JOB_ID, message_tenant_id=_matching_tenant()))
    job, document, link = asyncio.run(_reload(factory, JOB_ID, bucket_id=bucket_id))
    assert job.status == "failed"
    assert job.failed_stage == "acl_check"
    assert job.error == "Document access denied."
    assert job.document_id == DOC_ID
    assert document.status == "index_failed"
    assert document.error == "Document access denied."
    if expect_link:
        assert link.indexing_status == "index_failed"
        assert link.indexing_error == "Document access denied."
    else:
        assert link is None
    assert storage.refs == []
    assert qdrant.upserts == []
    assert qdrant.ensured == 0
    assert publisher.failed == []
    _assert_stage_logs(caplog, JOB_ID, DOC_ID, "acl_check")


def test_admin_role_snapshot_can_index_but_empty_roles_cannot(indexing_db, caplog: pytest.LogCaptureFixture) -> None:
    engine, factory = indexing_db
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session, owner_user_id="doc-owner")
        _add_link(session)
        _add_job(session, job_id="job-admin", owner_user_id="user-admin", owner_roles=["admin"])
        _add_job(session, job_id="job-plain", owner_user_id="user-admin", owner_roles=[])
        session.commit()
    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    publisher = RecordingPublisher()
    service = _service(factory, storage, qdrant, RecordingEmbed(), publisher)
    caplog.set_level(logging.WARNING, logger="app.services.document_indexing_service")

    async def _run() -> None:
        await service.process_job("job-admin", message_tenant_id=_matching_tenant())
        await service.process_job("job-plain", message_tenant_id=_matching_tenant())

    asyncio.run(_run())
    admin_job, document, link = asyncio.run(_reload(factory, "job-admin"))
    plain_job, _document, _link = asyncio.run(_reload(factory, "job-plain"))
    assert admin_job.status == "completed"
    assert admin_job.chunks_indexed == 1
    assert not admin_job.failed_stage
    assert plain_job.status == "failed"
    assert plain_job.failed_stage == "acl_check"
    assert plain_job.error == "Document access denied."
    assert storage.refs == [ASSET_PATH]
    assert len(qdrant.upserts) == 1
    assert document.status == "index_failed"
    assert link.indexing_status == "index_failed"
    assert publisher.failed == []
    assert publisher.indexed[0]["document_id"] == DOC_ID
    _assert_stage_logs(caplog, "job-plain", DOC_ID, "acl_check")


def test_success_after_failure_clears_error_and_failed_stage(indexing_db) -> None:
    engine, factory = indexing_db
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session, owner_user_id="owner-real", status="index_failed", error="previous embed failure")
        _add_link(session, indexing_status="index_failed", indexing_error="previous embed failure")
        _add_job(
            session,
            owner_user_id="owner-real",
            status="failed",
            attempts=1,
            error="previous embed failure",
            failed_stage="embed",
        )
        session.commit()
    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    service = _service(factory, storage, qdrant, RecordingEmbed())

    asyncio.run(service.process_job(JOB_ID, message_tenant_id=_matching_tenant()))
    job, document, link = asyncio.run(_reload(factory, JOB_ID))
    assert job.status == "completed"
    assert job.chunks_indexed == 1
    assert job.error is None
    assert job.failed_stage is None
    assert document.status == "indexed"
    assert document.error is None
    assert link.indexing_status == "indexed"
    assert link.indexing_error is None
    assert storage.refs == [ASSET_PATH]


@pytest.mark.parametrize(
    ("stage", "storage", "qdrant", "embed"),
    [
        ("load_object", RecordingStorage(error=RuntimeError("storage down")), RecordingQdrant(), RecordingEmbed()),
        ("parse", RecordingStorage(text="   \n"), RecordingQdrant(), RecordingEmbed()),
        ("embed", RecordingStorage(), RecordingQdrant(), RecordingEmbed(error=RuntimeError("embed down"))),
        ("upsert", RecordingStorage(), RecordingQdrant(upsert_error=RuntimeError("upsert down")), RecordingEmbed()),
    ],
)
def test_indexing_stage_failure_keeps_document_id(
    indexing_db,
    caplog: pytest.LogCaptureFixture,
    stage: str,
    storage: RecordingStorage,
    qdrant: RecordingQdrant,
    embed: RecordingEmbed,
) -> None:
    engine, factory = indexing_db
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session, owner_user_id="owner-real")
        _add_link(session)
        _add_job(session, owner_user_id="owner-real", source="bucket_commit")
        session.commit()
    publisher = RecordingPublisher()
    service = _service(factory, storage, qdrant, embed, publisher)
    caplog.set_level(logging.WARNING, logger="app.services.document_indexing_service")

    asyncio.run(service.process_job(JOB_ID, message_tenant_id=_matching_tenant()))
    job, document, link = asyncio.run(_reload(factory, JOB_ID))
    assert job.status == "failed"
    assert job.failed_stage == stage
    assert job.document_id == DOC_ID
    assert document.status == "index_failed"
    assert link.indexing_status == "index_failed"
    assert publisher.failed[0]["document_id"] == DOC_ID
    assert publisher.failed[0]["failed_stage"] == stage
    assert publisher.failed[0]["job_id"] == JOB_ID
    assert "user_id" not in publisher.failed[0]
    assert storage.refs == [ASSET_PATH]
    _assert_stage_logs(caplog, JOB_ID, DOC_ID, stage)
    if stage in {"load_object", "parse"}:
        assert embed.texts == []
        assert qdrant.upserts == []
    if stage == "embed":
        assert qdrant.upserts == []
    if stage == "upsert":
        assert qdrant.upserts


def test_missing_asset_sets_load_asset_and_publishes_document_id(
    indexing_db,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine, factory = indexing_db
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session, tenant_id="tenant-b", owner_user_id="owner-real")
        _add_job(session, owner_user_id="owner-real")
        session.commit()
    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    publisher = RecordingPublisher()
    service = _service(factory, storage, qdrant, RecordingEmbed(), publisher)
    caplog.set_level(logging.WARNING, logger="app.services.document_indexing_service")

    asyncio.run(service.process_job(JOB_ID, message_tenant_id=_matching_tenant()))
    job, document, _link = asyncio.run(_reload(factory, JOB_ID))
    assert job.status == "failed"
    assert job.failed_stage == "load_asset"
    assert job.error == "Document asset not found."
    assert job.document_id == DOC_ID
    assert document.status == "uploaded"
    assert document.tenant_id == "tenant-b"
    assert storage.refs == []
    assert qdrant.upserts == []
    assert publisher.failed[0]["document_id"] == DOC_ID
    assert publisher.failed[0]["failed_stage"] == "load_asset"
    assert "user_id" not in publisher.failed[0]
    _assert_stage_logs(caplog, JOB_ID, DOC_ID, "load_asset")


def test_only_flagged_bug_and_feature_rows_are_upserted(indexing_db) -> None:
    engine, factory = indexing_db
    base = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session, owner_user_id="owner-real")
        _add_document(session, document_id="doc-other", owner_user_id="owner-real", source_path="storage://tenant-a/documents/other.txt")
        _add_link(session)
        _add_job(session, owner_user_id="owner-real")
        session.flush()
        rows = [
            ("noise", "noise", REJECTED_BODIES[0], False),
            ("churn", "churn_signal", REJECTED_BODIES[1], False),
            ("bug-off", "bug", REJECTED_BODIES[2], False),
            ("bug-empty", "bug", "", True),
            ("bug-yes", "bug", BUG_BODY, True),
            ("feature-yes", "feature", FEATURE_BODY, True),
        ]
        for offset, (item_id, feedback_class, body, index_in_rag) in enumerate(rows):
            _add_feedback(
                session,
                item_id=item_id,
                feedback_class=feedback_class,
                body=body,
                index_in_rag=index_in_rag,
                created_at=base + timedelta(seconds=offset),
            )
        _add_feedback(
            session,
            item_id="other-doc",
            feedback_class="feature",
            body=REJECTED_BODIES[3],
            index_in_rag=True,
            document_id="doc-other",
            created_at=base + timedelta(seconds=20),
        )
        _add_feedback(
            session,
            item_id="other-tenant",
            feedback_class="feature",
            body=REJECTED_BODIES[4],
            index_in_rag=True,
            tenant_id="tenant-b",
            created_at=base + timedelta(seconds=21),
        )
        session.commit()
    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    embed = RecordingEmbed()
    service = _service(factory, storage, qdrant, embed)

    asyncio.run(service.process_job(JOB_ID, message_tenant_id=_matching_tenant()))
    job, document, link = asyncio.run(_reload(factory, JOB_ID))
    assert job.status == "completed"
    assert job.chunks_indexed == 2
    assert job.failed_stage is None
    assert job.error is None
    assert document.status == "indexed"
    assert link.indexing_status == "indexed"
    assert storage.refs == []
    assert embed.texts == [BUG_BODY, FEATURE_BODY]
    assert len(qdrant.upserts) == 1
    payloads = [item[2] for item in qdrant.upserts[0]]
    assert [payload["content"] for payload in payloads] == [BUG_BODY, FEATURE_BODY]
    assert [payload["feedback_class"] for payload in payloads] == ["bug", "feature"]
    assert {payload["feedback_item_id"] for payload in payloads} == {"bug-yes", "feature-yes"}
    for payload in payloads:
        assert payload["index_in_rag"] is True
        assert payload["document_id"] == DOC_ID
    blob = str(qdrant.upserts) + str(embed.texts)
    for secret in REJECTED_BODIES:
        assert secret not in blob
    assert "" not in embed.texts


def test_rejected_feedback_rows_complete_without_upsert(indexing_db) -> None:
    engine, factory = indexing_db
    base = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    with Session(engine) as session:
        _add_bucket(session)
        _add_document(session, owner_user_id="owner-real", status="uploaded")
        _add_link(session, indexing_status="pending")
        _add_job(session, owner_user_id="owner-real", source="bucket_commit")
        session.flush()
        rows = [
            ("noise", "noise", "NOISE_SHOULD_STAY", False),
            ("churn", "churn_signal", "CHURN_SHOULD_STAY", False),
            ("bug-off", "bug", "BUG_FLAG_FALSE_SHOULD_STAY", False),
            ("feature-off", "feature", "FEATURE_FLAG_FALSE_SHOULD_STAY", False),
            ("bug-empty", "bug", "", True),
            ("feature-blank", "feature", "   ", True),
        ]
        for offset, (item_id, feedback_class, body, index_in_rag) in enumerate(rows):
            _add_feedback(
                session,
                item_id=item_id,
                feedback_class=feedback_class,
                body=body,
                index_in_rag=index_in_rag,
                created_at=base + timedelta(seconds=offset),
            )
        session.commit()
    storage = RecordingStorage()
    qdrant = RecordingQdrant()
    embed = RecordingEmbed()
    service = _service(factory, storage, qdrant, embed)

    asyncio.run(service.process_job(JOB_ID, message_tenant_id=_matching_tenant()))
    job, document, link = asyncio.run(_reload(factory, JOB_ID))
    assert job.status == "completed"
    assert job.chunks_indexed == 0
    assert job.failed_stage is None
    assert document.status == "indexed"
    assert document.status != "index_failed"
    assert link.indexing_status == "indexed"
    assert link.indexing_status != "index_failed"
    assert storage.refs == []
    assert embed.texts == []
    assert qdrant.upserts == []
    assert qdrant.ensured == 0
