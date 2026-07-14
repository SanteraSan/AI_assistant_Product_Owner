from __future__ import annotations

import json

import pytest

from app.services.access_policy import UserContext
from app.services.agent.langgraph_adapter import LangGraphAgentAdapter
from app.services.tools.base import ToolContext, ToolResult, tool_ok
from app.services.tools.executor import ToolExecutor
from app.services.tools.registry import ToolRegistry
from pydantic import BaseModel, Field


class _EmptyArgs(BaseModel):
    pass


class _ListBucketsTool:
    name = "list_buckets"
    description = "list"
    args_model = _EmptyArgs

    async def run(self, ctx: ToolContext, args: _EmptyArgs) -> ToolResult:
        del ctx, args
        return tool_ok({"buckets": [{"id": "b1", "name": "Alpha"}]})


class _SqlArgs(BaseModel):
    sql: str = Field(...)


class _SqlTool:
    name = "execute_readonly_sql"
    description = "sql"
    args_model = _SqlArgs

    async def run(self, ctx: ToolContext, args: _SqlArgs) -> ToolResult:
        del ctx, args
        return tool_ok({"rows": []})


class _FakeOllama:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def generate(self, model: str, prompt: str, **kwargs):
        del model, prompt, kwargs
        index = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return {"response": self._responses[index]}


def _user(*roles: str) -> UserContext:
    return UserContext(tenant_id="t1", user_id="u1", roles=frozenset(roles))


@pytest.mark.anyio
async def test_langgraph_adapter_calls_tool_then_answers() -> None:
    registry = ToolRegistry()
    registry.register(_ListBucketsTool())
    executor = ToolExecutor(registry=registry)
    ollama = _FakeOllama(
        [
            json.dumps({"tool_calls": [{"name": "list_buckets", "arguments": {}}]}),
            json.dumps(
                {
                    "final_answer": "В тенанте есть bucket Alpha.",
                    "tool_calls": [],
                }
            ),
        ]
    )
    adapter = LangGraphAgentAdapter(
        ollama_client=ollama,  # type: ignore[arg-type]
        tool_executor=executor,
        tool_registry=registry,
        default_model="test-model",
        max_steps=4,
    )
    result = await adapter.run(
        message="Какие buckets есть?",
        user=_user("viewer"),
        request_id="req-lg-1",
    )
    assert "Alpha" in result.answer
    assert result.provider == "langgraph"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "list_buckets"
    assert result.tool_calls[0]["status"] == "ok"
    assert result.steps == 2


@pytest.mark.anyio
async def test_langgraph_adapter_viewer_sql_denied_in_trace() -> None:
    registry = ToolRegistry()
    registry.register(_SqlTool())
    executor = ToolExecutor(registry=registry)
    ollama = _FakeOllama(
        [
            json.dumps(
                {
                    "tool_calls": [
                        {
                            "name": "execute_readonly_sql",
                            "arguments": {"sql": "SELECT 1"},
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "final_answer": "У роли viewer нет доступа к SQL.",
                    "tool_calls": [],
                }
            ),
        ]
    )
    adapter = LangGraphAgentAdapter(
        ollama_client=ollama,  # type: ignore[arg-type]
        tool_executor=executor,
        tool_registry=registry,
        default_model="test-model",
        max_steps=4,
    )
    result = await adapter.run(
        message="Выполни SELECT 1",
        user=_user("viewer"),
        request_id="req-lg-2",
    )
    assert "viewer" in result.answer.lower() or "доступ" in result.answer.lower()
    assert result.tool_calls[0]["status"] == "denied"
    assert result.provider == "langgraph"


@pytest.mark.anyio
async def test_langgraph_adapter_direct_final_answer() -> None:
    registry = ToolRegistry()
    executor = ToolExecutor(registry=registry)
    ollama = _FakeOllama(
        [json.dumps({"final_answer": "Привет!", "tool_calls": []})]
    )
    adapter = LangGraphAgentAdapter(
        ollama_client=ollama,  # type: ignore[arg-type]
        tool_executor=executor,
        tool_registry=registry,
        default_model="test-model",
    )
    result = await adapter.run(message="Привет", user=_user("admin"))
    assert result.answer == "Привет!"
    assert result.tool_calls == []
    assert result.steps == 1
    assert result.provider == "langgraph"
