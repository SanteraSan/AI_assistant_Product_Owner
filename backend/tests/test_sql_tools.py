from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.services.access_policy import UserContext
from app.services.sql_execution_service import SqlExecutionResult, SqlExecutionService
from app.services.sql_schema_card import (
    DEFAULT_SQL_TOOL_ALLOWED_TABLES,
    build_schema_card,
    parse_allowed_tables,
)
from app.services.text_to_sql_service import TextToSqlService
from app.services.tools.executor import ToolExecutor
from app.services.tools.execute_readonly_sql import ExecuteReadonlySqlTool
from app.services.tools.registry import ToolRegistry
from app.services.tools.text_to_sql import TextToSqlTool


def _user(*roles: str) -> UserContext:
    return UserContext(tenant_id="tenant-a", user_id="u1", roles=frozenset(roles))


def test_schema_card_only_allowlisted_tables() -> None:
    card = build_schema_card(allowed_tables=frozenset({"rag_request_logs"}))
    assert "rag_request_logs(" in card
    assert "document_acl_entries" not in card


def test_parse_allowed_tables_default_and_override() -> None:
    assert parse_allowed_tables("") == DEFAULT_SQL_TOOL_ALLOWED_TABLES
    assert parse_allowed_tables("a, b") == frozenset({"a", "b"})


def test_validate_rejects_destructive_and_unknown_table() -> None:
    service = SqlExecutionService(
        postgres_dsn="postgresql+asyncpg://u:p@localhost:5432/db",
        allowed_tables=frozenset({"rag_request_logs"}),
    )
    destructive = service.validate("DELETE FROM rag_request_logs")
    assert not destructive.valid
    assert destructive.error and "destructive" in destructive.error

    unknown = service.validate("SELECT * FROM document_acl_entries")
    assert not unknown.valid
    assert unknown.error and "unknown_tables" in unknown.error

    ok = service.validate("SELECT id FROM rag_request_logs LIMIT 5")
    assert ok.valid


@pytest.mark.anyio
async def test_execute_readonly_sql_tool_validation_error() -> None:
    class _Svc:
        async def execute_readonly(self, sql: str) -> SqlExecutionResult:
            del sql
            return SqlExecutionResult(
                success=False,
                sql=None,
                tables=[],
                rows=[],
                row_count=0,
                truncated=False,
                validation_error="destructive_keyword:delete",
            )

    tool = ExecuteReadonlySqlTool(sql_execution_service=_Svc())  # type: ignore[arg-type]
    result = await tool.run(
        SimpleNamespace(user=_user("analyst"), request_id="r1"),  # type: ignore[arg-type]
        tool.args_model(sql="DELETE FROM rag_request_logs"),
    )
    assert result.status == "invalid_input"
    assert result.error_code == "destructive_keyword:delete"


@pytest.mark.anyio
async def test_executor_denies_execute_sql_for_viewer() -> None:
    class _Svc:
        called = False

        async def execute_readonly(self, sql: str) -> SqlExecutionResult:
            self.called = True
            del sql
            return SqlExecutionResult(
                success=True,
                sql="SELECT 1",
                tables=[],
                rows=[{"?column?": 1}],
                row_count=1,
                truncated=False,
            )

    svc = _Svc()
    registry = ToolRegistry()
    registry.register(ExecuteReadonlySqlTool(sql_execution_service=svc))  # type: ignore[arg-type]
    executor = ToolExecutor(registry=registry)
    execution = await executor.execute(
        name="execute_readonly_sql",
        arguments={"sql": "SELECT 1"},
        user=_user("viewer"),
        request_id="deny-sql",
    )
    assert execution.result.status == "denied"
    assert svc.called is False


@pytest.mark.anyio
async def test_text_to_sql_tool_happy_path() -> None:
    class _Gen:
        question = "count runs"
        sql = "SELECT count(*) AS c FROM evaluation_runs"
        model_used = "lora-model"
        fallback_used = False
        validation_valid = True
        validation_error = None
        tables = ["evaluation_runs"]
        warning = None

    class _Svc:
        async def generate(self, *, question: str):
            assert question
            return _Gen()

    tool = TextToSqlTool(text_to_sql_service=_Svc())  # type: ignore[arg-type]
    result = await tool.run(
        SimpleNamespace(user=_user("analyst"), request_id="r2"),  # type: ignore[arg-type]
        tool.args_model(question="Сколько evaluation runs?"),
    )
    assert result.ok
    assert result.data["sql"].startswith("SELECT")
    assert result.data["model_used"] == "lora-model"


@pytest.mark.anyio
async def test_text_to_sql_service_falls_back_when_preferred_missing() -> None:
    class _Ollama:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def generate(self, model: str, prompt: str, **kwargs):
            del prompt, kwargs
            self.calls.append(model)
            if model == "missing-lora":
                request = httpx.Request("POST", "http://ollama/api/generate")
                response = httpx.Response(404, request=request)
                raise httpx.HTTPStatusError("missing", request=request, response=response)
            return {
                "response": "SELECT id FROM evaluation_runs LIMIT 5",
            }

    class _Sql:
        def validate(self, sql: str):
            from app.services.sql_validator import validate_read_only_sql

            return validate_read_only_sql(
                sql,
                allowed_tables={"evaluation_runs"},
            )

    ollama = _Ollama()
    service = TextToSqlService(
        ollama_client=ollama,  # type: ignore[arg-type]
        sql_execution_service=_Sql(),  # type: ignore[arg-type]
        preferred_model="missing-lora",
        fallback_model="qwen2.5-coder:7b",
        allowed_tables=frozenset({"evaluation_runs"}),
    )
    generation = await service.generate(question="list evaluation run ids")
    assert generation.fallback_used is True
    assert generation.model_used == "qwen2.5-coder:7b"
    assert generation.validation_valid is True
    assert generation.warning is not None
    assert ollama.calls == ["missing-lora", "qwen2.5-coder:7b"]


@pytest.mark.anyio
async def test_execute_readonly_happy_path_payload() -> None:
    class _Svc:
        async def execute_readonly(self, sql: str) -> SqlExecutionResult:
            assert "SELECT" in sql.upper()
            return SqlExecutionResult(
                success=True,
                sql="SELECT id FROM evaluation_runs",
                tables=["evaluation_runs"],
                rows=[{"id": "1"}, {"id": "2"}],
                row_count=2,
                truncated=False,
            )

    tool = ExecuteReadonlySqlTool(sql_execution_service=_Svc())  # type: ignore[arg-type]
    result = await tool.run(
        SimpleNamespace(user=_user("admin"), request_id="r3"),  # type: ignore[arg-type]
        tool.args_model(sql="SELECT id FROM evaluation_runs"),
    )
    assert result.ok
    assert result.data["row_count"] == 2
    assert result.data["truncated"] is False
