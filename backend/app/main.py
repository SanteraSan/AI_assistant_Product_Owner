import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.clients.qdrant_store import QdrantStore
from app.core.config import get_settings
from app.db.session import (
    create_engine,
    create_session_factory,
    database_available,
    init_db,
)
from app.models.chat import ChatRequest, ChatResponse, RagChatRequest, RagChatResponse
from app.routers.buckets import create_bucket_router
from app.services.bucket_service import BucketService
from app.services.chat_history_service import ChatExchangeRecord, ChatHistoryService
from app.services.conversation_context_service import ConversationContextService
from app.services.conversation_memory_service import ConversationMemoryService
from app.services.conversation_summary_service import ConversationSummaryService
from app.services.document_indexing_service import DocumentIndexingService
from app.services.feature_extractor import FeatureExtractor
from app.services.ollama_client import OllamaClient
from app.services.ollama_load_guard import OllamaLoadGuard, OllamaOverloadedError
from app.services.query_router import QueryRouter
from app.services.rate_limiter import RedisRateLimiter
from app.services.rag_log_service import RagLogService
from app.services.rag_service import RagService
from app.services.redis_service import RedisService


settings = get_settings()
logger = logging.getLogger(__name__)
db_engine = create_engine(settings.postgres_dsn)
db_session_factory = create_session_factory(db_engine)
redis_service = RedisService(settings.redis_url) if settings.redis_enabled else None
rate_limiter = (
    RedisRateLimiter(
        redis_service=redis_service,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
        fail_open=settings.rate_limit_fail_open,
    )
    if redis_service is not None and settings.rate_limit_enabled
    else None
)
ollama_load_guard = OllamaLoadGuard(
    max_concurrency=settings.ollama_max_concurrency,
    timeout_seconds=settings.ollama_queue_timeout_seconds,
)
ollama_client = OllamaClient(
    base_url=settings.ollama_base_url,
    timeout_seconds=settings.request_timeout_seconds,
    load_guard=ollama_load_guard,
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
    candidate_multiplier=settings.rag_candidate_multiplier,
    generation_keep_alive=settings.rag_generation_keep_alive,
    generation_temperature=settings.rag_generation_temperature,
    generation_top_p=settings.rag_generation_top_p,
    excel_supplement_scroll_limit=settings.excel_supplement_scroll_limit,
    docx_supplement_scroll_limit=settings.docx_supplement_scroll_limit,
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
bucket_service = BucketService(
    session_factory=db_session_factory,
    raw_data_dir=settings.raw_data_dir,
)
document_indexing_service = DocumentIndexingService(
    session_factory=db_session_factory,
    qdrant_store=qdrant_store,
    ollama_client=ollama_client,
    embedding_model=settings.embedding_model,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        await init_db(
            db_engine,
            auto_create=settings.database_auto_create_tables,
        )
    except Exception:
        logger.exception("PostgreSQL initialization failed")
    try:
        yield
    finally:
        await ollama_client.aclose()
        if redis_service is not None:
            await redis_service.aclose()
        await db_engine.dispose()


def create_app() -> FastAPI:
    fastapi_app = FastAPI(title=settings.app_name, lifespan=lifespan)
    if settings.cors_allowed_origins:
        fastapi_app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    return fastapi_app


app = create_app()
app.include_router(
    create_bucket_router(
        bucket_service=bucket_service,
        document_indexing_service=document_indexing_service,
        default_tenant_id=settings.default_tenant_id,
    )
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = _request_id_from_header(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = _request_id_from_request(request)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error_type": "http_error",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    request_id = _request_id_from_request(request)
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "error_type": "validation_error",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(OllamaOverloadedError)
async def ollama_overloaded_exception_handler(
    request: Request,
    exc: OllamaOverloadedError,
) -> JSONResponse:
    request_id = _request_id_from_request(request)
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "error_type": "ollama_overloaded",
            "request_id": request_id,
            "model": exc.model,
            "operation": exc.operation,
        },
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id_from_request(request)
    logger.exception("Unhandled request error", extra={"request_id": request_id})
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error_type": "internal_error",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


@app.get("/health")
async def health() -> dict[str, object]:
    readiness = await _readiness_snapshot()
    return {
        "status": "ok",
        "readiness_status": readiness["status"],
        "ollama_available": readiness["dependencies"]["ollama_available"],
        "default_model": settings.default_model,
        "default_rag_model": settings.default_rag_model,
        "embedding_model": settings.embedding_model,
        "qdrant_collection": settings.qdrant_collection,
        "qdrant_collection_exists": readiness["dependencies"]["qdrant_collection_exists"],
        "postgres_available": readiness["dependencies"]["postgres_available"],
        "database_auto_create_tables": settings.database_auto_create_tables,
        "limits": _limits_snapshot(),
    }


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready() -> dict[str, object]:
    snapshot = await _readiness_snapshot()
    if snapshot["status"] != "ready":
        raise HTTPException(status_code=503, detail=snapshot)
    return snapshot


@app.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    _enforce_chat_request_limits(payload)
    await _enforce_rate_limit(request=request, endpoint="chat")
    model = payload.model or settings.default_model
    started_at = perf_counter()

    try:
        result = await ollama_client.generate(
            model=model,
            prompt=payload.message,
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
        session_id=payload.session_id,
        user_message=payload.message,
        response=response,
        metadata={"endpoint": "/chat"},
    )
    _attach_chat_exchange(response, chat_exchange)
    return response


@app.post("/rag/chat", response_model=RagChatResponse)
async def rag_chat(request: Request, payload: RagChatRequest) -> RagChatResponse:
    _enforce_rag_request_limits(payload)
    await _enforce_rate_limit(request=request, endpoint="rag_chat")
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
            session_id=payload.session_id,
            message=payload.message,
        )
        response = await rag_service.answer(
            message=payload.message,
            model=payload.model,
            retrieval_query=str(
                conversation_context.get("retrieval_query") or payload.message
            ),
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
            tenant_id=payload.tenant_id or settings.default_tenant_id,
            bucket_ids=payload.bucket_ids,
            features=payload.features,
            source_types=payload.source_types,
            document_ids=payload.document_ids,
            source_paths=payload.source_paths,
            max_sources_per_title=payload.max_sources_per_title,
            max_sources_per_source_type=payload.max_sources_per_source_type,
            max_sources_per_source_path=payload.max_sources_per_source_path,
            memory_context=_as_dict(conversation_context.get("prompt_memory")),
        )
        response.conversation_context = conversation_context
        chat_exchange = await _try_save_chat_exchange(
            session_id=payload.session_id,
            user_message=payload.message,
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
                message=payload.message,
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


def _request_id_from_header(value: str | None) -> str:
    normalized = (value or "").strip()
    if not normalized or len(normalized) > 128:
        return str(uuid4())
    return normalized


def _request_id_from_request(request: Request) -> str:
    return str(getattr(request.state, "request_id", "") or uuid4())


async def _readiness_snapshot() -> dict[str, object]:
    dependencies = {
        "postgres_available": await database_available(db_engine),
        "qdrant_collection_exists": _qdrant_collection_exists(),
        "ollama_available": await ollama_client.health(),
    }
    if settings.redis_enabled and redis_service is not None:
        dependencies["redis_available"] = await redis_service.health()
    ready = all(dependencies.values())
    return {
        "status": "ready" if ready else "degraded",
        "dependencies": dependencies,
        "models": {
            "default_model": settings.default_model,
            "default_rag_model": settings.default_rag_model,
            "embedding_model": settings.embedding_model,
            "image_vision_model": settings.image_vision_model,
        },
        "limits": _limits_snapshot(),
        "redis_enabled": settings.redis_enabled,
        "rate_limit_enabled": settings.rate_limit_enabled,
    }


def _limits_snapshot() -> dict[str, int | float]:
    return {
        "max_chat_message_chars": settings.max_chat_message_chars,
        "max_rag_top_k": settings.max_rag_top_k,
        "max_filter_values": settings.max_filter_values,
        "max_filter_value_chars": settings.max_filter_value_chars,
        "rate_limit_requests": settings.rate_limit_requests,
        "rate_limit_window_seconds": settings.rate_limit_window_seconds,
        "ollama_max_concurrency": settings.ollama_max_concurrency,
        "ollama_queue_timeout_seconds": settings.ollama_queue_timeout_seconds,
    }


def _enforce_chat_request_limits(request: ChatRequest) -> None:
    if len(request.message) > settings.max_chat_message_chars:
        raise HTTPException(
            status_code=413,
            detail=f"message exceeds {settings.max_chat_message_chars} characters",
        )


def _enforce_rag_request_limits(request: RagChatRequest) -> None:
    _enforce_chat_request_limits(request)
    if request.top_k is not None and request.top_k > settings.max_rag_top_k:
        raise HTTPException(
            status_code=422,
            detail=f"top_k must not exceed {settings.max_rag_top_k}",
        )

    for field_name in (
        "bucket_ids",
        "features",
        "source_types",
        "document_ids",
        "source_paths",
    ):
        values = getattr(request, field_name)
        _enforce_filter_values_limit(field_name=field_name, values=values)


def _enforce_filter_values_limit(*, field_name: str, values: list[str]) -> None:
    if len(values) > settings.max_filter_values:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must not contain more than {settings.max_filter_values} values",
        )
    oversized_values = [
        value for value in values if len(value) > settings.max_filter_value_chars
    ]
    if oversized_values:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{field_name} values must not exceed "
                f"{settings.max_filter_value_chars} characters"
            ),
        )


async def _enforce_rate_limit(*, request: Request, endpoint: str) -> None:
    if rate_limiter is None:
        return
    decision = await rate_limiter.check(
        scope=_rate_limit_scope(request=request, endpoint=endpoint),
    )
    request.state.rate_limit = decision
    if decision.allowed:
        return
    raise HTTPException(
        status_code=429,
        detail={
            "message": "Rate limit exceeded",
            "limit": decision.limit,
            "window_seconds": decision.window_seconds,
            "reason": decision.reason,
        },
    )


def _rate_limit_scope(*, request: Request, endpoint: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{endpoint}:{client_host}"


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
        return _conversation_context_error(message=message)


def _conversation_context_error(*, message: str) -> dict[str, object]:
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
