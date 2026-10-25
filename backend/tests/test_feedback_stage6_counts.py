"""Stage 6 feedback counts.

Rows live in a private in-memory SQLite database. The async service is driven
through a sync session adapter, so these tests do not open the project
Postgres and do not leave feedback_items rows there.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import DocumentAsset, FeedbackItem, KnowledgeBucket
from app.routers.buckets import create_bucket_router
from app.services.feedback_counts import FeedbackCountService, FeedbackCounts
from app.services.sql_schema_card import DEFAULT_SQL_TOOL_ALLOWED_TABLES, build_schema_card
from tests.auth_helpers import auth_headers

BACKEND_ROOT = Path(__file__).resolve().parents[1]

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
BUCKET_A = "bucket-a"
BUCKET_B = "bucket-b"
BUCKET_FOREIGN = "bucket-foreign"
SECRET_PHRASE = "уникальная фраза stage6-qx7"
PHONE = "+7 900 000-00-00"
FOREIGN_BODY = "чужой текст +7 900 000-00-00"
ROUTE_FOREIGN_BODY = "чужой текст маршрута +7 900 000-00-00"
COUNT_KEYS = {"noise", "churn_signal", "bug", "feature", "total", "indexed"}
NOT_FOUND = "Bucket not found."


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

    async def commit(self) -> None:
        self._session.commit()

    async def execute(self, statement, params=None, **kwargs):  # noqa: ANN001
        return self._session.execute(statement, params, **kwargs)


class _UnusedBucketService:
    """The counts route does not call the bucket service."""


def _make_engine():
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

    assert engine.dialect.name == "sqlite"
    Base.metadata.create_all(
        engine,
        tables=[
            KnowledgeBucket.__table__,
            DocumentAsset.__table__,
            FeedbackItem.__table__,
        ],
    )
    return engine


def _session_factory(engine):
    def factory():
        return _AsyncSessionAdapter(Session(engine, expire_on_commit=False))

    return factory


@pytest.fixture()
def counts_db():
    engine = _make_engine()
    try:
        yield engine, _session_factory(engine)
    finally:
        engine.dispose()


def _add_bucket(session: Session, *, bucket_id: str, tenant_id: str) -> None:
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


def _add_item(
    session: Session,
    *,
    item_id: str,
    tenant_id: str,
    bucket_id: str,
    feedback_class: str,
    body: str,
    index_in_rag: bool,
    generator_class: str | None = None,
    index_text: str | None = None,
) -> None:
    session.add(
        FeedbackItem(
            id=item_id,
            tenant_id=tenant_id,
            bucket_id=bucket_id,
            feedback_class=feedback_class,
            body=body,
            index_in_rag=index_in_rag,
            generator_class=generator_class,
            index_text=index_text,
        )
    )


def _counts(factory, *, tenant_id: str, bucket_id: str) -> FeedbackCounts | None:
    service = FeedbackCountService(session_factory=factory)  # type: ignore[arg-type]
    return asyncio.run(
        service.counts_for_bucket(tenant_id=tenant_id, bucket_id=bucket_id)
    )


def _app(factory) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_bucket_router(
            bucket_service=_UnusedBucketService(),  # type: ignore[arg-type]
            default_tenant_id="unused",
            feedback_count_service=FeedbackCountService(session_factory=factory),  # type: ignore[arg-type]
        )
    )
    return app


def _get(app: FastAPI, path: str, *, tenant_id: str) -> httpx.Response:
    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                path,
                headers=auth_headers(sub="user-a", tenant_id=tenant_id, roles=["analyst"]),
            )

    return asyncio.run(_run())


def test_counts_use_feedback_class_and_index_flag(counts_db) -> None:
    """Bucket A counts feedback_class and index_in_rag; the other bucket stays out."""

    engine, factory = counts_db
    with Session(engine) as session:
        _add_bucket(session, bucket_id=BUCKET_A, tenant_id=TENANT_A)
        _add_bucket(session, bucket_id=BUCKET_B, tenant_id=TENANT_A)
        session.flush()
        _add_item(
            session,
            item_id="noise-1",
            tenant_id=TENANT_A,
            bucket_id=BUCKET_A,
            feedback_class="noise",
            body="шум",
            index_in_rag=False,
        )
        _add_item(
            session,
            item_id="churn-1",
            tenant_id=TENANT_A,
            bucket_id=BUCKET_A,
            feedback_class="churn_signal",
            body="короткий сигнал",
            index_in_rag=False,
        )
        _add_item(
            session,
            item_id="bug-indexed",
            tenant_id=TENANT_A,
            bucket_id=BUCKET_A,
            feedback_class="bug",
            body="баг в индексе",
            index_in_rag=True,
            generator_class="noise",
        )
        _add_item(
            session,
            item_id="bug-held",
            tenant_id=TENANT_A,
            bucket_id=BUCKET_A,
            feedback_class="bug",
            body="баг без индекса",
            index_in_rag=False,
        )
        _add_item(
            session,
            item_id="feature-1",
            tenant_id=TENANT_A,
            bucket_id=BUCKET_A,
            feedback_class="feature",
            body="фича",
            index_in_rag=True,
        )
        _add_item(
            session,
            item_id="bug-other-bucket",
            tenant_id=TENANT_A,
            bucket_id=BUCKET_B,
            feedback_class="bug",
            body="баг другого бакета",
            index_in_rag=True,
        )
        session.commit()

    counts = _counts(factory, tenant_id=TENANT_A, bucket_id=BUCKET_A)
    assert counts is not None
    assert counts.noise == 1
    assert counts.churn_signal == 1
    assert counts.bug == 2
    assert counts.feature == 1
    assert counts.total == 5
    assert counts.indexed == 2
    assert counts.total == counts.noise + counts.churn_signal + counts.bug + counts.feature
    assert counts.indexed <= counts.bug + counts.feature

    other = _counts(factory, tenant_id=TENANT_A, bucket_id=BUCKET_B)
    assert other is not None
    assert other.bug == 1
    assert counts.bug == 2


def test_foreign_tenant_row_in_same_bucket_is_ignored(counts_db) -> None:
    """A tenant B row in tenant A's bucket does not increase tenant A's counts."""

    engine, factory = counts_db
    with Session(engine) as session:
        _add_bucket(session, bucket_id=BUCKET_A, tenant_id=TENANT_A)
        session.flush()
        _add_item(
            session,
            item_id="foreign-bug",
            tenant_id=TENANT_B,
            bucket_id=BUCKET_A,
            feedback_class="bug",
            body=FOREIGN_BODY,
            index_in_rag=True,
        )
        session.commit()
        stored = session.scalar(select(func.count()).select_from(FeedbackItem))
    assert stored == 1

    counts = _counts(factory, tenant_id=TENANT_A, bucket_id=BUCKET_A)
    assert counts == FeedbackCounts(
        noise=0,
        churn_signal=0,
        bug=0,
        feature=0,
        total=0,
        indexed=0,
    )


def test_empty_bucket_is_zeros(counts_db) -> None:
    """An existing bucket with no rows returns six zeros, not None."""

    engine, factory = counts_db
    with Session(engine) as session:
        _add_bucket(session, bucket_id=BUCKET_A, tenant_id=TENANT_A)
        session.commit()

    counts = _counts(factory, tenant_id=TENANT_A, bucket_id=BUCKET_A)
    assert counts is not None
    assert counts == FeedbackCounts(
        noise=0,
        churn_signal=0,
        bug=0,
        feature=0,
        total=0,
        indexed=0,
    )


def test_missing_bucket_is_none(counts_db) -> None:
    """An unknown bucket id returns None."""

    _engine, factory = counts_db
    assert _counts(factory, tenant_id=TENANT_A, bucket_id="bucket-missing") is None


def test_other_tenant_bucket_is_none(counts_db) -> None:
    """Tenant A's call does not see tenant B's bucket."""

    engine, factory = counts_db
    with Session(engine) as session:
        _add_bucket(session, bucket_id=BUCKET_FOREIGN, tenant_id=TENANT_B)
        session.flush()
        _add_item(
            session,
            item_id="tenant-b-bug",
            tenant_id=TENANT_B,
            bucket_id=BUCKET_FOREIGN,
            feedback_class="bug",
            body=FOREIGN_BODY,
            index_in_rag=True,
        )
        session.commit()

    assert _counts(factory, tenant_id=TENANT_A, bucket_id=BUCKET_FOREIGN) is None


def test_route_own_bucket_200_has_no_feedback_text(counts_db) -> None:
    """Own bucket returns six count fields and does not echo row text."""

    engine, factory = counts_db
    with Session(engine) as session:
        _add_bucket(session, bucket_id=BUCKET_A, tenant_id=TENANT_A)
        session.flush()
        _add_item(
            session,
            item_id="secret-bug",
            tenant_id=TENANT_A,
            bucket_id=BUCKET_A,
            feedback_class="bug",
            body=f"{SECRET_PHRASE} {PHONE}",
            index_in_rag=True,
            index_text=f"{SECRET_PHRASE} {PHONE}",
        )
        session.commit()

    response = _get(
        _app(factory),
        f"/buckets/{BUCKET_A}/feedback-counts",
        tenant_id=TENANT_A,
    )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == COUNT_KEYS
    assert SECRET_PHRASE not in response.text
    assert PHONE not in response.text
    assert "body" not in response.text
    assert "index_text" not in response.text


def test_route_other_tenant_404(counts_db) -> None:
    """Tenant A's JWT does not receive tenant B's bucket counts or row text."""

    engine, factory = counts_db
    with Session(engine) as session:
        _add_bucket(session, bucket_id=BUCKET_FOREIGN, tenant_id=TENANT_B)
        session.flush()
        for class_name, index_in_rag in (
            ("noise", False),
            ("churn_signal", False),
            ("bug", True),
            ("feature", True),
        ):
            _add_item(
                session,
                item_id=f"foreign-{class_name}",
                tenant_id=TENANT_B,
                bucket_id=BUCKET_FOREIGN,
                feedback_class=class_name,
                body=ROUTE_FOREIGN_BODY,
                index_in_rag=index_in_rag,
            )
        session.commit()

    response = _get(
        _app(factory),
        f"/buckets/{BUCKET_FOREIGN}/feedback-counts",
        tenant_id=TENANT_A,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == NOT_FOUND
    assert ROUTE_FOREIGN_BODY not in response.text
    assert PHONE not in response.text
    assert not any(character.isdigit() for character in response.text)


def test_route_unknown_bucket_404(counts_db) -> None:
    """An unknown bucket id is the same 404 as a foreign bucket."""

    _engine, factory = counts_db
    response = _get(
        _app(factory),
        "/buckets/bucket-missing/feedback-counts",
        tenant_id=TENANT_A,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == NOT_FOUND


def test_route_empty_bucket_200_zeros(counts_db) -> None:
    """An empty own bucket returns 200 and six zeros."""

    engine, factory = counts_db
    with Session(engine) as session:
        _add_bucket(session, bucket_id=BUCKET_A, tenant_id=TENANT_A)
        session.commit()

    response = _get(
        _app(factory),
        f"/buckets/{BUCKET_A}/feedback-counts",
        tenant_id=TENANT_A,
    )
    assert response.status_code == 200
    assert response.json() == {key: 0 for key in COUNT_KEYS}


def test_feedback_items_stay_out_of_readonly_sql() -> None:
    """The feedback table stays off the SQL-tool allowlist and schema card."""

    assert "feedback_items" not in DEFAULT_SQL_TOOL_ALLOWED_TABLES
    card = build_schema_card(allowed_tables=DEFAULT_SQL_TOOL_ALLOWED_TABLES)
    assert "feedback_items" not in card

    counts_source = (BACKEND_ROOT / "app" / "services" / "feedback_counts.py").read_text(encoding="utf-8")
    router_source = (BACKEND_ROOT / "app" / "routers" / "buckets.py").read_text(encoding="utf-8")
    execution_source = (BACKEND_ROOT / "app" / "services" / "sql_execution_service.py").read_text(encoding="utf-8")
    tool_source = (BACKEND_ROOT / "app" / "services" / "tools" / "execute_readonly_sql.py").read_text(encoding="utf-8")
    factory_source = (BACKEND_ROOT / "app" / "services" / "tools" / "factory.py").read_text(encoding="utf-8")
    for source in (counts_source, router_source, execution_source, tool_source, factory_source):
        assert "feedback_items" not in source
    assert "execute_readonly" not in counts_source
    assert "execute_readonly" not in router_source
    assert execution_source.count("async def execute_readonly") == 1
    assert factory_source.count("ExecuteReadonlySqlTool(") == 1
