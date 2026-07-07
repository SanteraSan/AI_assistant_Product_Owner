import logging
from time import perf_counter

import httpx
from fastapi import FastAPI, HTTPException

from app.clients.qdrant_store import QdrantStore
from app.core.config import get_settings
from app.db.session import (
    create_engine,
    create_session_factory,
    database_available,
    init_db,
)
from app.models.chat import ChatRequest, ChatResponse, RagChatRequest, RagChatResponse
from app.services.chat_history_service import ChatExchangeRecord, ChatHistoryService
from app.services.conversation_context_service import ConversationContextService
from app.services.conversation_memory_service import ConversationMemoryService
from app.services.conversation_summary_service import ConversationSummaryService
from app.services.feature_extractor import FeatureExtractor
from app.services.ollama_client import OllamaClient
from app.services.query_router import QueryRouter
from app.services.rag_log_service import RagLogService
from app.services.rag_service import RagService


settings = get_settings()
logger = logging.getLogger(__name__)
app = FastAPI(title=settings.app_name)
db_engine = create_engine(settings.postgres_dsn)
db_session_factory = create_session_factory(db_engine)
ollama_client = OllamaClient(
    base_url=settings.ollama_base_url,
    timeout_seconds=settings.request_timeout_seconds,
)
qdrant_store = QdrantStore(
    url=settings.qdrant_url,
    collection_name=settings.qdrant_collection,
)
feature_extractor = FeatureExtractor()
query_router = QueryRouter()
rag_service = RagService(
    ollama_client=ollama_client,
    qdrant_store=qdrant_store,
    feature_extractor=feature_extractor,
    query_router=query_router,
    embedding_model=settings.embedding_model,
    default_model=settings.default_rag_model,
    default_top_k=settings.rag_top_k,
    default_score_threshold=settings.rag_score_threshold,
)
rag_log_service = RagLogService(session_factory=db_session_factory)
chat_history_service = ChatHistoryService(session_factory=db_session_factory)
conversation_context_service = ConversationContextService(
    feature_extractor=feature_extractor,
)
conversation_memory_service = ConversationMemoryService(
    enabled=settings.conversation_memory_enabled,
    token_budget=settings.conversation_memory_token_budget,
    recent_messages_limit=settings.conversation_memory_recent_messages,
)
conversation_summary_service = ConversationSummaryService(
    session_factory=db_session_factory,
    feature_extractor=feature_extractor,
    ollama_client=ollama_client,
    summary_strategy=settings.conversation_summary_strategy,
    summary_model=settings.conversation_summary_model,
    summary_temperature=settings.conversation_summary_temperature,
)


@app.on_event("startup")
async def startup() -> None:
    try:
        await init_db(db_engine)
    except Exception:
        logger.exception("PostgreSQL initialization failed")


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "ollama_available": await ollama_client.health(),
        "default_model": settings.default_model,
        "default_rag_model": settings.default_rag_model,
        "embedding_model": settings.embedding_model,
        "qdrant_collection": settings.qdrant_collection,
        "qdrant_collection_exists": _qdrant_collection_exists(),
        "postgres_available": await database_available(db_engine),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    model = request.model or settings.default_model
    started_at = perf_counter()

    try:
        result = await ollama_client.generate(
            model=model,
            prompt=request.message,
            think=False,
        )
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

    latency_ms = int((perf_counter() - started_at) * 1000)

    response = ChatResponse(
        model=model,
        response=result.get("response", ""),
        latency_ms=latency_ms,
    )
    chat_exchange = await _try_save_chat_exchange(
        session_id=request.session_id,
        user_message=request.message,
        response=response,
        metadata={"endpoint": "/chat"},
    )
    _attach_chat_exchange(response, chat_exchange)
    return response


@app.post("/rag/chat", response_model=RagChatResponse)
async def rag_chat(request: RagChatRequest) -> RagChatResponse:
    if not _qdrant_collection_exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Qdrant collection is not ready. Run "
                "`python -m scripts.ingest_seed_data --recreate` from the backend directory."
            ),
        )

    try:
        conversation_context = await _build_conversation_context(
            session_id=request.session_id,
            message=request.message,
        )
        response = await rag_service.answer(
            message=request.message,
            model=request.model,
            retrieval_query=str(
                conversation_context.get("retrieval_query") or request.message
            ),
            top_k=request.top_k,
            score_threshold=request.score_threshold,
            features=request.features,
            source_types=request.source_types,
            max_sources_per_title=request.max_sources_per_title,
            max_sources_per_source_type=request.max_sources_per_source_type,
            max_sources_per_source_path=request.max_sources_per_source_path,
            memory_context=_as_dict(conversation_context.get("prompt_memory")),
        )
        response.conversation_context = conversation_context
        chat_exchange = await _try_save_chat_exchange(
            session_id=request.session_id,
            user_message=request.message,
            response=response,
            metadata={
                "endpoint": "/rag/chat",
                "collection": response.collection,
                "retrieval": response.retrieval,
                "query_hints": response.query_hints,
                "context_policy": response.context_policy,
                "conversation_context": response.conversation_context,
            },
        )
        _attach_chat_exchange(response, chat_exchange)
        try:
            await rag_log_service.log_response(
                message=request.message,
                response=response,
            )
        except Exception:
            logger.exception("RAG response logging failed")
        return response
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


def _qdrant_collection_exists() -> bool:
    try:
        return qdrant_store.collection_exists()
    except Exception:
        return False


async def _build_conversation_context(
    *,
    session_id: str | None,
    message: str,
) -> dict[str, object]:
    try:
        recent_messages = await chat_history_service.get_recent_messages(
            session_id=session_id,
            limit=max(4, conversation_memory_service.recent_messages_limit),
        )
        summary_context = await conversation_summary_service.prepare_summary(
            session_id=session_id,
        )
        context_decision = conversation_context_service.build_context(
            message=message,
            recent_messages=recent_messages,
            summary_context=summary_context,
        ).to_dict()
        context_decision["prompt_memory"] = conversation_memory_service.build_prompt_memory(
            recent_messages=recent_messages,
            summary_context=context_decision,
        )
        return context_decision
    except Exception:
        logger.exception("Conversation context build failed")
        return {
            "used": False,
            "mode": "error",
            "follow_up_detected": False,
            "topic_switch_detected": False,
            "history_messages_used": 0,
            "retrieval_query": message,
            "carried_features": [],
            "current_features": feature_extractor.extract(message),
            "decision_reason": "error",
            "summary_available": False,
            "summary_used": False,
            "summary_updated": False,
            "summary_message_count": 0,
            "summary_features": [],
            "summary_mode": "error",
            "summary_reason": "conversation_context_build_failed",
            "summary_strategy": settings.conversation_summary_strategy,
            "summary_model": settings.conversation_summary_model,
            "summary_structured": {},
            "summary_fallback_used": False,
            "summary_validation_error": "conversation_context_build_failed",
            "summary_validation_warnings": [],
            "prompt_memory": conversation_memory_service.empty_prompt_memory(
                reason="conversation_context_build_failed"
            ),
        }


async def _try_save_chat_exchange(
    *,
    session_id: str | None,
    user_message: str,
    response: ChatResponse,
    metadata: dict[str, object],
) -> ChatExchangeRecord | None:
    try:
        return await chat_history_service.save_exchange(
            session_id=session_id,
            user_message=user_message,
            assistant_message=response.response,
            model=response.model,
            provider=response.provider,
            latency_ms=response.latency_ms,
            metadata=metadata,
        )
    except Exception:
        logger.exception("Chat history persistence failed")
        return None


def _attach_chat_exchange(
    response: ChatResponse,
    chat_exchange: ChatExchangeRecord | None,
) -> None:
    if chat_exchange is None:
        return
    response.session_id = chat_exchange.session_id
    response.user_message_id = chat_exchange.user_message_id
    response.assistant_message_id = chat_exchange.assistant_message_id


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}
