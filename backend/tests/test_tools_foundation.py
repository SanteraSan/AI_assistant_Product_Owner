from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from app.models.chat import SourceChunk
from app.services.access_policy import UserContext
from app.services.agent.tool_loop import parse_tool_loop_response
from app.services.tools.base import ToolContext, ToolResult, tool_ok
from app.services.tools.executor import ToolExecutor
from app.services.tools.get_document_status import GetDocumentStatusTool
from app.services.tools.get_user_context import GetUserContextTool
from app.services.tools.list_buckets import ListBucketsTool
from app.services.tools.permissions import can_invoke_tool
from app.services.tools.rag_search import RagSearchTool
from app.services.tools.registry import ToolRegistry


def _user(*, roles: set[str], user_id: str = "u1") -> UserContext:
    return UserContext(tenant_id="tenant-a", user_id=user_id, roles=frozenset(roles))


def test_role_matrix_read_tools_any_authenticated() -> None:
    assert can_invoke_tool(tool_name="get_user_context", roles=frozenset({"viewer"}))
    assert can_invoke_tool(tool_name="list_buckets", roles=frozenset({"analyst"}))
    assert can_invoke_tool(tool_name="rag_search", roles=frozenset({"custom_role"}))


def test_role_matrix_sql_tools_denied_for_viewer() -> None:
    assert not can_invoke_tool(tool_name="text_to_sql", roles=frozenset({"viewer"}))
    assert not can_invoke_tool(
        tool_name="execute_readonly_sql",
        roles=frozenset({"viewer"}),
    )
    assert can_invoke_tool(tool_name="text_to_sql", roles=frozenset({"analyst"}))
    assert can_invoke_tool(tool_name="execute_readonly_sql", roles=frozenset({"admin"}))


@pytest.mark.anyio
async def test_get_user_context_tool() -> None:
    tool = GetUserContextTool()
    result = await tool.run(
        ToolContext(user=_user(roles={"viewer"}), request_id="req-1"),
        tool.args_model(),
    )
    assert result.ok
    assert result.data["tenant_id"] == "tenant-a"
    assert result.data["roles"] == ["viewer"]
    assert result.data["is_admin"] is False


@pytest.mark.anyio
async def test_executor_denies_sql_for_viewer_before_run() -> None:
    class _SqlArgs(BaseModel):
        question: str = Field(default="x")

    class _SqlTool:
        name = "text_to_sql"
        description = "sql"
        args_model = _SqlArgs
        called = False

        async def run(self, ctx: ToolContext, args: _SqlArgs) -> ToolResult:
            del ctx, args
            self.called = True
            return tool_ok({"sql": "SELECT 1"})

    registry = ToolRegistry()
    sql_tool = _SqlTool()
    registry.register(sql_tool)
    executor = ToolExecutor(registry=registry, session_factory=None)

    execution = await executor.execute(
        name="text_to_sql",
        arguments={"question": "how many?"},
        user=_user(roles={"viewer"}),
        request_id="req-deny",
    )
    assert execution.result.status == "denied"
    assert execution.result.error_code == "tool_forbidden"
    assert sql_tool.called is False
    assert execution.audit_entry["status"] == "denied"
    assert execution.audit_entry["name"] == "text_to_sql"
    assert "id" in execution.audit_entry
    assert "latency_ms" in execution.audit_entry


@pytest.mark.anyio
async def test_executor_invalid_arguments() -> None:
    class _Args(BaseModel):
        document_id: str = Field(..., min_length=1)

    class _Tool:
        name = "get_document_status"
        description = "status"
        args_model = _Args

        async def run(self, ctx: ToolContext, args: _Args) -> ToolResult:
            del ctx, args
            return tool_ok({})

    registry = ToolRegistry()
    registry.register(_Tool())
    executor = ToolExecutor(registry=registry)

    execution = await executor.execute(
        name="get_document_status",
        arguments={},
        user=_user(roles={"analyst"}),
        request_id="req-invalid",
    )
    assert execution.result.status == "invalid_input"
    assert execution.result.error_code == "invalid_arguments"


@pytest.mark.anyio
async def test_get_document_status_no_leak() -> None:
    class _BucketService:
        async def get_document(self, *, user: UserContext, document_id: str):
            del user, document_id
            return None

    tool = GetDocumentStatusTool(bucket_service=_BucketService())  # type: ignore[arg-type]
    result = await tool.run(
        ToolContext(user=_user(roles={"viewer"}), request_id="req-2"),
        tool.args_model(document_id="missing-doc"),
    )
    assert result.status == "denied"
    assert result.error_code == "document_not_readable"


@pytest.mark.anyio
async def test_list_buckets_tenant_scoped() -> None:
    class _Bucket:
        id = "b1"
        name = "Alpha"
        description = "desc"
        status = "ready"

    class _BucketService:
        async def list_buckets(self, *, tenant_id: str):
            assert tenant_id == "tenant-a"
            return [(_Bucket(), 3)]

    tool = ListBucketsTool(bucket_service=_BucketService())  # type: ignore[arg-type]
    result = await tool.run(
        ToolContext(user=_user(roles={"analyst"}), request_id="req-3"),
        tool.args_model(),
    )
    assert result.ok
    assert result.data["buckets"][0]["name"] == "Alpha"
    assert result.data["buckets"][0]["document_count"] == 3


@pytest.mark.anyio
async def test_rag_search_uses_scoped_document_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BucketService:
        async def list_documents(self, *, user: UserContext, bucket_id: str):
            del user, bucket_id
            return None

    class _SearchResult:
        sources = [
            SourceChunk(
                id="p1",
                score=0.9,
                title="Doc",
                source_type="text",
                source_path="a.txt",
                content="hello world",
                metadata={"document_id": "doc-1"},
            )
        ]
        retrieval = {"final_top_k": 1}

    class _RagService:
        async def search(self, **kwargs):
            assert kwargs["document_ids"] == ["doc-1"]
            assert kwargs["tenant_id"] == "tenant-a"
            return _SearchResult()

    async def _fake_resolve(**kwargs):
        del kwargs
        return ["doc-1"]

    monkeypatch.setattr(
        "app.services.tools.rag_search.resolve_rag_document_ids",
        _fake_resolve,
    )
    tool = RagSearchTool(
        bucket_service=_BucketService(),  # type: ignore[arg-type]
        rag_service=_RagService(),  # type: ignore[arg-type]
    )
    result = await tool.run(
        ToolContext(user=_user(roles={"viewer"}), request_id="req-4"),
        tool.args_model(query="hello", document_ids=["doc-1"]),
    )
    assert result.ok
    assert result.data["source_count"] == 1
    assert result.data["sources"][0]["content"] == "hello world"


def test_parse_tool_loop_response_tool_calls() -> None:
    parsed = parse_tool_loop_response(
        'Here is JSON:\n{"tool_calls":[{"name":"list_buckets","arguments":{}}]}'
    )
    assert parsed.error is None
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0].name == "list_buckets"
    assert parsed.final_answer is None


def test_parse_tool_loop_response_final_answer_fenced() -> None:
    parsed = parse_tool_loop_response(
        '```json\n{"final_answer":"You are a viewer in tenant-a","tool_calls":[]}\n```'
    )
    assert parsed.error is None
    assert parsed.tool_calls == []
    assert "viewer" in (parsed.final_answer or "")


def test_registry_list_specs() -> None:
    registry = ToolRegistry()
    registry.register(GetUserContextTool())
    specs = registry.list_specs()
    assert specs[0]["name"] == "get_user_context"
    assert "parameters" in specs[0]


@pytest.mark.anyio
async def test_executor_audit_shape_on_success() -> None:
    registry = ToolRegistry()
    registry.register(GetUserContextTool())
    executor = ToolExecutor(registry=registry)
    execution = await executor.execute(
        name="get_user_context",
        arguments={},
        user=_user(roles={"admin"}),
        request_id="req-ok",
    )
    entry = execution.audit_entry
    assert entry["status"] == "ok"
    assert entry["error_code"] is None
    assert entry["result_preview"] is not None
    assert set(entry) >= {
        "id",
        "name",
        "arguments",
        "status",
        "latency_ms",
        "error_code",
        "error_message",
        "result_preview",
    }
