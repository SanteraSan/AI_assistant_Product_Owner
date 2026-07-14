"""E6 lab: thin LangGraph adapter beside handwritten AgentOrchestrator.

Calls the same ToolExecutor / ToolRegistry / prompt contract. Default path remains
AgentOrchestrator; enable with AGENT_LANGGRAPH_ENABLED=true.
"""

from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from app.services.access_policy import UserContext
from app.services.agent.orchestrator import (
    AgentRunResult,
    _build_agent_prompt,
    _collect_sources,
    _latency_ms,
)
from app.services.agent.tool_loop import parse_tool_loop_response
from app.services.ollama_client import OllamaClient
from app.services.tools.executor import ToolExecutor
from app.services.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentGraphState(TypedDict, total=False):
    message: str
    request_id: str
    model: str
    memory_context: dict[str, object] | None
    transcript: list[dict[str, Any]]
    tool_calls_audit: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    step: int
    max_steps: int
    answer: str
    done: bool
    pending_response_text: str
    pending_tool_calls: list[dict[str, Any]]
    pending_final_answer: str | None
    needs_repair: bool
    # UserContext kept in-process (no checkpoint); not serialized across processes.
    user: UserContext


class LangGraphAgentAdapter:
    """StateGraph tool loop that reuses TaskFlow tools + RBAC."""

    def __init__(
        self,
        *,
        ollama_client: OllamaClient,
        tool_executor: ToolExecutor,
        tool_registry: ToolRegistry,
        default_model: str,
        max_steps: int = 4,
    ) -> None:
        self._ollama_client = ollama_client
        self._tool_executor = tool_executor
        self._tool_registry = tool_registry
        self._default_model = default_model
        self._max_steps = max_steps
        self._graph = self._compile_graph()

    def _compile_graph(self):
        graph = StateGraph(AgentGraphState)
        graph.add_node("call_model", self._call_model)
        graph.add_node("execute_tools", self._execute_tools)
        graph.add_node("finalize", self._finalize)
        graph.set_entry_point("call_model")
        graph.add_conditional_edges(
            "call_model",
            self._after_model,
            {
                "execute_tools": "execute_tools",
                "call_model": "call_model",
                "finalize": "finalize",
            },
        )
        graph.add_conditional_edges(
            "execute_tools",
            self._after_tools,
            {
                "call_model": "call_model",
                "finalize": "finalize",
            },
        )
        graph.add_edge("finalize", END)
        return graph.compile()

    async def run(
        self,
        *,
        message: str,
        user: UserContext,
        request_id: str | None = None,
        model: str | None = None,
        memory_context: dict[str, object] | None = None,
    ) -> AgentRunResult:
        started = perf_counter()
        selected_model = (model or self._default_model).strip()
        req_id = request_id or f"agent_lg_{uuid4().hex[:12]}"
        initial: AgentGraphState = {
            "message": message,
            "user": user,
            "request_id": req_id,
            "model": selected_model,
            "memory_context": memory_context,
            "transcript": [{"role": "user", "content": message}],
            "tool_calls_audit": [],
            "sources": [],
            "step": 0,
            "max_steps": self._max_steps,
            "answer": "",
            "done": False,
            "pending_response_text": "",
            "pending_tool_calls": [],
            "pending_final_answer": None,
            "needs_repair": False,
        }
        final_state = await self._graph.ainvoke(initial)
        return AgentRunResult(
            answer=str(final_state.get("answer") or "Агент не вернул final_answer."),
            model=selected_model,
            latency_ms=_latency_ms(started),
            tool_calls=list(final_state.get("tool_calls_audit") or []),
            sources=list(final_state.get("sources") or []),
            steps=int(final_state.get("step") or 0),
            provider="langgraph",
        )

    async def _call_model(self, state: AgentGraphState) -> dict[str, Any]:
        step = int(state.get("step") or 0) + 1
        max_steps = int(state.get("max_steps") or self._max_steps)
        transcript = list(state.get("transcript") or [])
        if state.get("needs_repair"):
            transcript.append(
                {
                    "role": "system",
                    "content": (
                        "Previous response was not valid JSON. "
                        "Reply with JSON only: "
                        '{"tool_calls":[...]} or {"final_answer":"...","tool_calls":[]}.'
                    ),
                }
            )

        prompt = _build_agent_prompt(
            tool_specs=self._tool_registry.list_specs(),
            memory_context=state.get("memory_context"),
            transcript=transcript,
        )
        raw = await self._ollama_client.generate(
            model=str(state.get("model") or self._default_model),
            prompt=prompt,
            think=False,
            options={"temperature": 0.1, "top_p": 0.9},
        )
        response_text = str(raw.get("response") or "").strip()
        parsed = parse_tool_loop_response(response_text)

        if parsed.error and not parsed.tool_calls and not parsed.final_answer:
            if step >= max_steps:
                return {
                    "step": step,
                    "transcript": transcript,
                    "answer": response_text or "Не удалось разобрать ответ агента.",
                    "done": True,
                    "needs_repair": False,
                    "pending_tool_calls": [],
                    "pending_final_answer": None,
                    "pending_response_text": response_text,
                }
            return {
                "step": step,
                "transcript": transcript,
                "done": False,
                "needs_repair": True,
                "pending_tool_calls": [],
                "pending_final_answer": None,
                "pending_response_text": response_text,
            }

        tool_calls_payload = [
            {"name": call.name, "arguments": call.arguments} for call in parsed.tool_calls
        ]
        updates: dict[str, Any] = {
            "step": step,
            "transcript": transcript,
            "done": False,
            "needs_repair": False,
            "pending_response_text": response_text,
            "pending_tool_calls": tool_calls_payload,
            "pending_final_answer": parsed.final_answer,
        }
        # Direct final answer without tools — mark done for finalize.
        if not tool_calls_payload and parsed.final_answer:
            updates["answer"] = parsed.final_answer
            updates["done"] = True
        elif not tool_calls_payload and step >= max_steps:
            updates["answer"] = response_text or "Агент не вернул final_answer."
            updates["done"] = True
        return updates

    async def _execute_tools(self, state: AgentGraphState) -> dict[str, Any]:
        user = state["user"]
        req_id = str(state.get("request_id") or "")
        transcript = list(state.get("transcript") or [])
        tool_calls_audit = list(state.get("tool_calls_audit") or [])
        sources = list(state.get("sources") or [])
        response_text = str(state.get("pending_response_text") or "")
        pending_calls = list(state.get("pending_tool_calls") or [])
        pending_final = state.get("pending_final_answer")
        step = int(state.get("step") or 0)
        max_steps = int(state.get("max_steps") or self._max_steps)

        tool_results_for_model: list[dict[str, Any]] = []
        for call in pending_calls:
            execution = await self._tool_executor.execute(
                name=str(call.get("name") or ""),
                arguments=dict(call.get("arguments") or {}),
                user=user,
                request_id=req_id,
            )
            tool_calls_audit.append(execution.audit_entry)
            _collect_sources(execution.result.data, sources)
            tool_results_for_model.append(
                {
                    "name": call.get("name"),
                    "arguments": call.get("arguments") or {},
                    "result": execution.result.to_llm_payload(),
                }
            )

        transcript.append({"role": "assistant", "content": response_text})
        transcript.append(
            {
                "role": "tool",
                "content": json.dumps(tool_results_for_model, ensure_ascii=False),
            }
        )

        if pending_final:
            return {
                "transcript": transcript,
                "tool_calls_audit": tool_calls_audit,
                "sources": sources,
                "answer": str(pending_final),
                "done": True,
                "pending_tool_calls": [],
                "pending_final_answer": None,
            }
        if step >= max_steps:
            return {
                "transcript": transcript,
                "tool_calls_audit": tool_calls_audit,
                "sources": sources,
                "answer": "Достигнут лимит шагов агента без final_answer.",
                "done": True,
                "pending_tool_calls": [],
                "pending_final_answer": None,
            }
        return {
            "transcript": transcript,
            "tool_calls_audit": tool_calls_audit,
            "sources": sources,
            "done": False,
            "pending_tool_calls": [],
            "pending_final_answer": None,
        }

    async def _finalize(self, state: AgentGraphState) -> dict[str, Any]:
        if state.get("answer"):
            return {"done": True}
        pending_final = state.get("pending_final_answer")
        if pending_final:
            return {"answer": str(pending_final), "done": True}
        response_text = str(state.get("pending_response_text") or "")
        return {
            "answer": response_text or "Агент не вернул final_answer.",
            "done": True,
        }

    def _after_model(
        self, state: AgentGraphState
    ) -> Literal["execute_tools", "call_model", "finalize"]:
        if state.get("done"):
            return "finalize"
        if state.get("needs_repair"):
            return "call_model"
        if state.get("pending_tool_calls"):
            return "execute_tools"
        return "finalize"

    def _after_tools(
        self, state: AgentGraphState
    ) -> Literal["call_model", "finalize"]:
        if state.get("done"):
            return "finalize"
        return "call_model"
