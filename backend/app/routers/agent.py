from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.errors import ErrorType, ProviderError
from app.dependencies.auth import get_current_user
from app.models.chat import AgentChatRequest, AgentChatResponse
from app.services.access_policy import UserContext
from app.services.agent.orchestrator import AgentOrchestrator
from app.services.agent.langgraph_adapter import LangGraphAgentAdapter
from app.services.chat_history_service import ChatExchangeRecord
from app.services.llm.types import normalize_approach
from app.services.metrics import AppMetrics
from app.services.ollama_load_guard import OllamaOverloadedError


BuildConversationContext = Callable[..., Awaitable[dict[str, object]]]
SaveChatExchange = Callable[..., Awaitable[ChatExchangeRecord | None]]
EnforceRateLimit = Callable[..., Awaitable[None]]
AgentRunner = AgentOrchestrator | LangGraphAgentAdapter


def create_agent_router(
    *,
    agent_orchestrator: AgentOrchestrator,
    build_conversation_context: BuildConversationContext,
    save_chat_exchange: SaveChatExchange,
    enforce_rate_limit: EnforceRateLimit,
    attach_chat_exchange: Callable[[AgentChatResponse, ChatExchangeRecord | None], None],
    metrics: AppMetrics | None = None,
    langgraph_adapter: LangGraphAgentAdapter | None = None,
    agent_langgraph_enabled: bool = False,
) -> APIRouter:
    router = APIRouter(tags=["agent"])

    @router.post("/agent/chat", response_model=AgentChatResponse)
    async def agent_chat(
        request: Request,
        payload: AgentChatRequest,
        user: UserContext = Depends(get_current_user),
    ) -> AgentChatResponse:
        await enforce_rate_limit(request=request, endpoint="agent_chat")
        if normalize_approach(payload.approach) == "external":
            raise ProviderError(
                ErrorType.EXTERNAL_AGENT_NOT_SUPPORTED,
                "External providers are not supported for /agent/chat in this slice. Use hybrid or local_only.",
                status_code=400,
            )
        request_id = request.headers.get("x-request-id") or f"agent_{uuid4().hex[:12]}"
        started_at = perf_counter()
        outcome = "error"
        runner: AgentRunner = (
            langgraph_adapter
            if agent_langgraph_enabled and langgraph_adapter is not None
            else agent_orchestrator
        )
        runtime = (
            "langgraph"
            if agent_langgraph_enabled and langgraph_adapter is not None
            else "handwritten"
        )

        try:
            conversation_context = await build_conversation_context(
                session_id=payload.session_id,
                message=payload.message,
            )
            memory = conversation_context.get("prompt_memory")
            memory_context = memory if isinstance(memory, dict) else None
            retrieval_scope = _agent_retrieval_scope(payload)

            try:
                result = await runner.run(
                    message=payload.message,
                    user=user,
                    request_id=request_id,
                    model=payload.model,
                    memory_context=memory_context,
                    retrieval_scope=retrieval_scope,
                )
            except OllamaOverloadedError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except httpx.ConnectError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Ollama is not reachable. Check that `ollama serve` is running.",
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=exc.response.status_code,
                    detail=exc.response.text,
                ) from exc
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            response = AgentChatResponse(
                model=result.model,
                response=result.answer,
                latency_ms=result.latency_ms,
                provider=result.provider,
                tool_calls=result.tool_calls,
                sources=result.sources,
                steps=result.steps,
                conversation_context=conversation_context,
            )
            chat_exchange = await save_chat_exchange(
                session_id=payload.session_id,
                tenant_id=user.tenant_id,
                user_id=user.user_id,
                user_message=payload.message,
                response=response,
                metadata={
                    "endpoint": "/agent/chat",
                    "model_id": result.model,
                    "approach": payload.approach,
                    "active_bucket_id": payload.active_bucket_id,
                    "bucket_ids": payload.bucket_ids,
                    "document_ids": payload.document_ids,
                    "retrieval_scope": retrieval_scope,
                    "tool_calls": result.tool_calls,
                    "sources": result.sources,
                    "steps": result.steps,
                    "agent_runtime": runtime,
                    "conversation_context": conversation_context,
                },
            )
            attach_chat_exchange(response, chat_exchange)
            outcome = "success"
            return response
        finally:
            if metrics is not None:
                metrics.observe_agent(
                    outcome=outcome,
                    duration_seconds=perf_counter() - started_at,
                    agent_runtime=runtime,
                )

    return router


def _agent_retrieval_scope(payload: AgentChatRequest) -> dict[str, object]:
    bucket_ids = [item.strip() for item in payload.bucket_ids if item and item.strip()]
    document_ids = [item.strip() for item in payload.document_ids if item and item.strip()]
    active = (payload.active_bucket_id or "").strip() or None
    if active and active not in bucket_ids:
        bucket_ids = [active, *bucket_ids]
    scope: dict[str, object] = {}
    if active:
        scope["active_bucket_id"] = active
    if bucket_ids:
        scope["bucket_ids"] = bucket_ids
    if document_ids:
        scope["document_ids"] = document_ids
    return scope
