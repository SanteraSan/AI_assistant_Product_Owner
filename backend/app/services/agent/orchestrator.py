from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.services.access_policy import UserContext
from app.services.agent.tool_loop import parse_tool_loop_response
from app.services.ollama_client import OllamaClient
from app.services.tools.executor import ToolExecutor
from app.services.tools.registry import ToolRegistry


@dataclass(frozen=True)
class AgentRunResult:
    answer: str
    model: str
    latency_ms: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    provider: str = "ollama"


class AgentOrchestrator:
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

    async def run(
        self,
        *,
        message: str,
        user: UserContext,
        request_id: str | None = None,
        model: str | None = None,
        memory_context: dict[str, object] | None = None,
        retrieval_scope: dict[str, object] | None = None,
    ) -> AgentRunResult:
        started = perf_counter()
        selected_model = (model or self._default_model).strip()
        req_id = request_id or f"agent_{uuid4().hex[:12]}"
        tool_calls_audit: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        transcript: list[dict[str, Any]] = [{"role": "user", "content": message}]
        tool_extras = dict(retrieval_scope or {})

        for step in range(1, self._max_steps + 1):
            prompt = _build_agent_prompt(
                tool_specs=self._tool_registry.list_specs(),
                memory_context=memory_context,
                retrieval_scope=retrieval_scope,
                transcript=transcript,
            )
            raw = await self._ollama_client.generate(
                model=selected_model,
                prompt=prompt,
                think=False,
                options={"temperature": 0.1, "top_p": 0.9},
            )
            response_text = str(raw.get("response") or "").strip()
            parsed = parse_tool_loop_response(response_text)

            if parsed.error and not parsed.tool_calls and not parsed.final_answer:
                # Repair pass: treat plain text as final answer on last step.
                if step >= self._max_steps:
                    return AgentRunResult(
                        answer=response_text or "Не удалось разобрать ответ агента.",
                        model=selected_model,
                        latency_ms=_latency_ms(started),
                        tool_calls=tool_calls_audit,
                        sources=sources,
                        steps=step,
                    )
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
                continue

            if parsed.tool_calls:
                tool_results_for_model: list[dict[str, Any]] = []
                for call in parsed.tool_calls:
                    execution = await self._tool_executor.execute(
                        name=call.name,
                        arguments=call.arguments,
                        user=user,
                        request_id=req_id,
                        extras=tool_extras,
                    )
                    tool_calls_audit.append(execution.audit_entry)
                    _collect_sources(execution.result.data, sources)
                    tool_results_for_model.append(
                        {
                            "name": call.name,
                            "arguments": call.arguments,
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
                if parsed.final_answer:
                    return AgentRunResult(
                        answer=parsed.final_answer,
                        model=selected_model,
                        latency_ms=_latency_ms(started),
                        tool_calls=tool_calls_audit,
                        sources=sources,
                        steps=step,
                    )
                continue

            if parsed.final_answer:
                return AgentRunResult(
                    answer=parsed.final_answer,
                    model=selected_model,
                    latency_ms=_latency_ms(started),
                    tool_calls=tool_calls_audit,
                    sources=sources,
                    steps=step,
                )

            # Empty tool_calls without final_answer
            if step >= self._max_steps:
                return AgentRunResult(
                    answer=response_text or "Агент не вернул final_answer.",
                    model=selected_model,
                    latency_ms=_latency_ms(started),
                    tool_calls=tool_calls_audit,
                    sources=sources,
                    steps=step,
                )

        return AgentRunResult(
            answer="Достигнут лимит шагов агента без final_answer.",
            model=selected_model,
            latency_ms=_latency_ms(started),
            tool_calls=tool_calls_audit,
            sources=sources,
            steps=self._max_steps,
        )


def _build_agent_prompt(
    *,
    tool_specs: list[dict[str, Any]],
    memory_context: dict[str, object] | None,
    retrieval_scope: dict[str, object] | None,
    transcript: list[dict[str, Any]],
) -> str:
    tools_json = json.dumps(tool_specs, ensure_ascii=False, indent=2)
    memory_block = ""
    if memory_context:
        memory_block = (
            "\nConversation memory (context, not evidence):\n"
            f"{json.dumps(memory_context, ensure_ascii=False)}\n"
        )
    scope_block = ""
    if retrieval_scope:
        scope_block = (
            "\nUI retrieval scope (prefer for tools; not evidence by itself):\n"
            f"{json.dumps(retrieval_scope, ensure_ascii=False)}\n"
        )
    transcript_text = "\n".join(
        f"{item['role'].upper()}: {item['content']}" for item in transcript
    )
    return f"""Ты агент TaskFlow AI. Можешь вызывать tools или дать финальный ответ.

Правила:
- Отвечай ТОЛЬКО одним JSON-объектом.
- Чтобы вызвать tools: {{"tool_calls":[{{"name":"...","arguments":{{...}}}}]}}
- Чтобы закончить: {{"final_answer":"...","tool_calls":[]}}
- Evidence только из tool results (особенно rag_search / analyze_image / SQL). Memory — не evidence.
- Не выдумывай документы, SQL-результаты или содержимое картинок.
- Если tool вернул denied/invalid_input — объясни ограничение или попробуй другой tool.
- Вопросы про список файлов в бакете: list_bucket_documents (не list_buckets).
- Вопросы «что на картинке / какого цвета / что изображено»: analyze_image.
- Вопросы про статус/доступность файла по имени (moto.jpg, AGENTS.md): вызывай
  get_document_status с arguments.file_name. Не проси UUID, если имя файла уже известно.
- document_id передавай только когда пользователь дал UUID.
- Если UI scope задаёт bucket_ids/document_ids — используй их (или оставь пустыми, tools подставят scope).

Доступные tools:
{tools_json}
{memory_block}{scope_block}
Диалог:
{transcript_text}

JSON:"""


def _collect_sources(data: dict[str, Any] | None, sink: list[dict[str, Any]]) -> None:
    if not data:
        return
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list):
        return
    seen = {item.get("id") for item in sink if isinstance(item, dict)}
    for source in raw_sources:
        if not isinstance(source, dict):
            continue
        source_id = source.get("id")
        if source_id in seen:
            continue
        sink.append(
            {
                "id": str(source_id or uuid4()),
                "title": source.get("title") or source.get("source_path") or "Источник",
                "source_type": source.get("source_type") or "unknown",
                "source_path": source.get("source_path"),
                "score": source.get("score"),
            }
        )
        seen.add(source_id)


def _latency_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)
