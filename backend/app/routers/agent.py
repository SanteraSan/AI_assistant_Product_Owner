from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies.auth import get_current_user
from app.models.chat import AgentChatRequest, AgentChatResponse
from app.services.access_policy import UserContext
from app.services.agent.orchestrator import AgentOrchestrator
from app.services.chat_history_service import ChatExchangeRecord
from app.services.metrics import AppMetrics
from app.services.ollama_load_guard import OllamaOverloadedError


BuildConversationContext = Callable[..., Awaitable[dict[str, object]]]
SaveChatExchange = Callable[..., Awaitable[ChatExchangeRecord | None]]
EnforceRateLimit = Callable[..., Awaitable[None]]


def create_agent_router(
    *,
    agent_orchestrator: AgentOrchestrator,
    build_conversation_context: BuildConversationContext,
    save_chat_exchange: SaveChatExchange,
    enforce_rate_limit: EnforceRateLimit,
    attach_chat_exchange: Callable[[AgentChatResponse, ChatExchangeRecord | None], None],
    metrics: AppMetrics | None = None,
) -> APIRouter:
    router = APIRouter(tags=["agent"])

    @router.post("/agent/chat", response_model=AgentChatResponse)
    async def agent_chat(
        request: Request,
        payload: AgentChatRequest,
        user: UserContext = Depends(get_current_user),
    ) -> AgentChatResponse:
        await enforce_rate_limit(request=request, endpoint="agent_chat")
        request_id = request.headers.get("x-request-id") or f"agent_{uuid4().hex[:12]}"
        started_at = perf_counter()
        outcome = "error"

        try:
            conversation_context = await build_conversation_context(
                session_id=payload.session_id,
                message=payload.message,
            )
            memory = conversation_context.get("prompt_memory")
            memory_context = memory if isinstance(memory, dict) else None

            try:
                result = await agent_orchestrator.run(
                    message=payload.message,
                    user=user,
                    request_id=request_id,
                    model=payload.model,
                    memory_context=memory_context,
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
                    "tool_calls": result.tool_calls,
                    "sources": result.sources,
                    "steps": result.steps,
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
                )

    return router
