"""Stage 1 schema, policy, and job-actor checks.

CHECK constraints run on a private in-memory SQLite database. The executed
SQL is the ORM model's CheckConstraint text. The original pair is a subset
of the model and must match alembic revision 20261023_0010. Stage 2 check
names live on the model and in revision 20261023_0011. Nothing here opens
the project Postgres or leaves feedback_items rows there.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, insert, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.schema import CheckConstraint

from app.db.base import Base
from app.db.models import DocumentAsset, FeedbackItem, KnowledgeBucket
from app.services.access_policy import UserContext
from app.services.bucket_service import indexing_job_actor_fields
from app.services.feedback_index_policy import feedback_item_enters_product_qdrant
from app.services.sql_schema_card import DEFAULT_SQL_TOOL_ALLOWED_TABLES, build_schema_card

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "20261023_0010_feedback_items_and_job_acl.py"
STAGE2_MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "20261023_0011_feedback_rule_columns.py"
BUCKET_SERVICE_PATH = APP_ROOT / "services" / "bucket_service.py"

TENANT_ID = "tenant-a"
BUCKET_ID = "bucket-a"
DOC_ID = "doc-1"

CLASS_CHECK = "feedback_class IN ('noise', 'churn_signal', 'bug', 'feature')"
INDEX_CHECK = "index_in_rag = false OR feedback_class IN ('bug', 'feature')"
GENERATOR_CLASS_CHECK = (
    "generator_class IS NULL OR generator_class IN ('noise', 'churn_signal', 'bug', 'feature')"
)
RULE_CLASS_CHECK = "rule_class IS NULL OR rule_class IN ('noise', 'churn_signal', 'bug', 'feature')"
RULE_MATCHES_CHECK = "rule_class IS NULL OR feedback_class = rule_class"
RULE_REASON_CHECK = (
    "rule_reason IS NULL OR rule_reason IN "
    "('lexicon_noise', 'lexicon_churn', 'keep_generator', 'exact_duplicate')"
)
STAGE2_CHECKS = {
    "ck_feedback_items_generator_class": GENERATOR_CLASS_CHECK,
    "ck_feedback_items_rule_class": RULE_CLASS_CHECK,
    "ck_feedback_items_rule_matches_feedback": RULE_MATCHES_CHECK,
    "ck_feedback_items_rule_reason": RULE_REASON_CHECK,
}
JOB_SOURCES = frozenset(
    {
        "retry_indexing",
        "bucket_existing_document_commit",
        "bucket_existing_upload_dedup",
        "bucket_commit",
        "personal_commit",
    }
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):  # noqa: ANN001
    del type_, compiler, kw
    return "JSON"


def _model_checks() -> dict[str, str]:
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in FeedbackItem.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _sqlite_engine():
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
    with Session(engine) as session:
        session.add(
            KnowledgeBucket(
                id=BUCKET_ID,
                tenant_id=TENANT_ID,
                name="feedback",
                description="",
                status="ready",
                metadata_json={},
            )
        )
        session.add(
            DocumentAsset(
                id=DOC_ID,
                tenant_id=TENANT_ID,
                owner_user_id="owner-real",
                title="notes.txt",
                file_name="notes.txt",
                source_type="txt",
                source_path="storage://tenant-a/documents/notes.txt",
                status="uploaded",
                visibility="private",
                allowed_roles=[],
                size_bytes=1,
                metadata_json={},
            )
        )
        session.commit()
    return engine


@pytest.fixture()
def feedback_db():
    engine = _sqlite_engine()
    try:
        yield engine
    finally:
        engine.dispose()


def test_feedback_items_absent_from_sql_tool_schema() -> None:
    assert "feedback_items" not in DEFAULT_SQL_TOOL_ALLOWED_TABLES
    card = build_schema_card(allowed_tables=DEFAULT_SQL_TOOL_ALLOWED_TABLES)
    assert "feedback_items" not in card


def test_model_check_sql_matches_migration() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    stage2 = STAGE2_MIGRATION_PATH.read_text(encoding="utf-8")
    checks = _model_checks()
    old = {
        "ck_feedback_items_feedback_class": CLASS_CHECK,
        "ck_feedback_items_index_in_rag_class": INDEX_CHECK,
    }
    assert old.items() <= checks.items()
    assert set(checks) == set(old) | set(STAGE2_CHECKS)
    assert CLASS_CHECK in migration
    assert INDEX_CHECK in migration
    assert "ck_feedback_items_feedback_class" in migration
    assert "ck_feedback_items_index_in_rag_class" in migration
    assert "sa.false()" in migration
    assert STAGE2_CHECKS.items() <= checks.items()
    for name, sql in STAGE2_CHECKS.items():
        assert name in stage2
        assert sql in stage2


def test_sqlite_executes_model_check_constraints(feedback_db) -> None:
    with feedback_db.connect() as connection:
        ddl = connection.execute(text("SELECT sql FROM sqlite_master WHERE name='feedback_items'")).scalar_one()
    assert "ck_feedback_items_feedback_class" in ddl
    assert "ck_feedback_items_index_in_rag_class" in ddl
    assert CLASS_CHECK in ddl
    assert INDEX_CHECK in ddl


def test_feedback_class_outside_four_values_is_rejected(feedback_db) -> None:
    with Session(feedback_db) as session:
        session.add(
            FeedbackItem(
                id="bad-class",
                tenant_id=TENANT_ID,
                bucket_id=BUCKET_ID,
                document_id=DOC_ID,
                feedback_class="praise",
                body="not a class",
                index_in_rag=False,
            )
        )
        with pytest.raises(IntegrityError, match="ck_feedback_items_feedback_class"):
            session.commit()
        session.rollback()


@pytest.mark.parametrize("feedback_class", ["noise", "churn_signal"])
def test_index_in_rag_true_rejected_for_noise_and_churn(feedback_db, feedback_class: str) -> None:
    with Session(feedback_db) as session:
        session.add(
            FeedbackItem(
                id=f"bad-{feedback_class}",
                tenant_id=TENANT_ID,
                bucket_id=BUCKET_ID,
                document_id=DOC_ID,
                feedback_class=feedback_class,
                body="should stay out of qdrant",
                index_in_rag=True,
            )
        )
        with pytest.raises(IntegrityError, match="ck_feedback_items_index_in_rag_class"):
            session.commit()
        session.rollback()


@pytest.mark.parametrize("feedback_class", ["bug", "feature"])
def test_index_in_rag_true_is_stored_for_bug_and_feature(feedback_db, feedback_class: str) -> None:
    with Session(feedback_db) as session:
        row = FeedbackItem(
            id=f"yes-{feedback_class}",
            tenant_id=TENANT_ID,
            bucket_id=BUCKET_ID,
            document_id=DOC_ID,
            feedback_class=feedback_class,
            body="product row",
            index_in_rag=True,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        assert row.index_in_rag is True


@pytest.mark.parametrize("feedback_class", ["noise", "churn_signal", "bug", "feature"])
def test_index_in_rag_false_is_stored_for_every_class(feedback_db, feedback_class: str) -> None:
    with Session(feedback_db) as session:
        row = FeedbackItem(
            id=f"no-{feedback_class}",
            tenant_id=TENANT_ID,
            bucket_id=BUCKET_ID,
            document_id=DOC_ID,
            feedback_class=feedback_class,
            body="kept in postgres",
            index_in_rag=False,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        assert row.index_in_rag is False


def test_new_feedback_row_index_in_rag_defaults_false(feedback_db) -> None:
    with Session(feedback_db) as session:
        orm_row = FeedbackItem(
            id="orm-default",
            tenant_id=TENANT_ID,
            bucket_id=BUCKET_ID,
            document_id=DOC_ID,
            feedback_class="noise",
            body="orm default",
        )
        session.add(orm_row)
        session.execute(
            insert(FeedbackItem).values(
                id="core-default",
                tenant_id=TENANT_ID,
                bucket_id=BUCKET_ID,
                document_id=DOC_ID,
                feedback_class="churn_signal",
                body="server default",
            )
        )
        session.commit()
        session.refresh(orm_row)
        core_row = session.get(FeedbackItem, "core-default")
        assert orm_row.index_in_rag is False
        assert core_row is not None
        assert core_row.index_in_rag is False


@pytest.mark.parametrize(
    ("feedback_class", "index_in_rag", "expected"),
    [
        ("noise", True, False),
        ("noise", False, False),
        ("churn_signal", True, False),
        ("churn_signal", False, False),
        ("bug", False, False),
        ("feature", False, False),
        ("bug", True, True),
        ("feature", True, True),
        ("other", True, False),
        ("", True, False),
    ],
)
def test_feedback_item_enters_product_qdrant_only_for_flagged_bug_and_feature(
    feedback_class: str,
    index_in_rag: bool,
    expected: bool,
) -> None:
    assert (
        feedback_item_enters_product_qdrant(
            feedback_class=feedback_class,
            index_in_rag=index_in_rag,
        )
        is expected
    )


def _is_true(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _column_index_in_rag_target(target: ast.AST) -> bool:
    if isinstance(target, ast.Name) and target.id == "index_in_rag":
        return True
    return isinstance(target, ast.Attribute) and target.attr == "index_in_rag"


def _index_in_rag_true_assignments(tree: ast.AST) -> list[ast.AST]:
    hits: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_true(node.value):
            if any(_column_index_in_rag_target(target) for target in node.targets):
                hits.append(node)
        elif isinstance(node, ast.AnnAssign) and node.value is not None and _is_true(node.value):
            if _column_index_in_rag_target(node.target):
                hits.append(node)
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "index_in_rag" and _is_true(keyword.value):
                    hits.append(node)
    return hits


def test_assignment_scanner_ignores_point_payload_and_flags_column_writes() -> None:
    payload = ast.parse('def write():\n    payload["index_in_rag"] = True\n')
    assert _index_in_rag_true_assignments(payload) == []
    column = ast.parse("def write(row):\n    row.index_in_rag = True\n")
    assert _index_in_rag_true_assignments(column)
    keyword = ast.parse("FeedbackItem(index_in_rag=True)\n")
    assert _index_in_rag_true_assignments(keyword)


def test_product_code_does_not_assign_index_in_rag_true() -> None:
    hits: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _index_in_rag_true_assignments(tree):
            hits.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")
    assert hits == []


def test_indexing_job_actor_fields_copies_user_id_and_sorted_roles() -> None:
    user = UserContext(
        tenant_id="tenant-a",
        user_id="user-7",
        roles=frozenset({"admin", "analyst"}),
    )
    assert indexing_job_actor_fields(user) == {
        "owner_user_id": "user-7",
        "owner_roles_json": ["admin", "analyst"],
    }
    empty = UserContext(tenant_id="tenant-a", user_id="user-7", roles=frozenset())
    assert indexing_job_actor_fields(empty)["owner_roles_json"] == []


def _job_source(call: ast.Call) -> str:
    for keyword in call.keywords:
        if keyword.arg != "metadata_json" or not isinstance(keyword.value, ast.Dict):
            continue
        for key, value in zip(keyword.value.keys, keyword.value.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "source" and isinstance(value, ast.Constant):
                return str(value.value)
    raise AssertionError("DocumentIndexingJob is missing metadata source")


def _unpacks_actor_fields(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg is not None or not isinstance(keyword.value, ast.Call):
            continue
        func = keyword.value.func
        if not isinstance(func, ast.Name) or func.id != "indexing_job_actor_fields":
            continue
        return len(keyword.value.args) == 1 and isinstance(keyword.value.args[0], ast.Name) and keyword.value.args[0].id == "user"
    return False


def test_bucket_job_constructors_pass_actor_fields_for_every_source() -> None:
    tree = ast.parse(BUCKET_SERVICE_PATH.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "DocumentIndexingJob"
    ]
    sources = {_job_source(call) for call in calls}
    assert sources == JOB_SOURCES
    assert len(calls) == len(JOB_SOURCES)
    assert all(_unpacks_actor_fields(call) for call in calls)


def _attribute_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _is_user_tenant(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "tenant_id"
        and isinstance(node.value, ast.Name)
        and node.value.id == "user"
    )


def test_bucket_and_integration_dispatch_pass_tenant_not_user_id() -> None:
    checked = 0
    for relative in ("app/routers/buckets.py", "app/routers/integrations.py"):
        tree = ast.parse((BACKEND_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _attribute_name(node.func)
            if name == "dispatch":
                tenant = next(keyword.value for keyword in node.keywords if keyword.arg == "tenant_id")
                assert _is_user_tenant(tenant)
                checked += 1
            elif name == "add_task":
                tenant = next(keyword.value for keyword in node.keywords if keyword.arg == "message_tenant_id")
                assert _is_user_tenant(tenant)
                checked += 1
    assert checked == 4
