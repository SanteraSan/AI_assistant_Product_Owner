import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path
from time import perf_counter
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.clients.qdrant_store import QdrantStore
from app.core.config import get_settings
from app.db.models import ChatMessage, ChatSession, DocumentAsset
from app.db.session import (
    create_engine,
    create_session_factory,
    database_available,
    init_db,
)
from app.dependencies.auth import get_current_user
from app.models.chat import (
    ChatAttachmentCreateRequest,
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
    ChatSessionUpdateRequest,
    RagChatRequest,
    RagChatResponse,
    SourceChunk,
)
from app.routers.agent import create_agent_router
from app.routers.buckets import create_bucket_router
from app.services.access_policy import UserContext
from app.services.agent.orchestrator import AgentOrchestrator
from app.services.bucket_service import PERSONAL_INDEX_BUCKET_ID, BucketService
from app.services.chat_history_service import ChatExchangeRecord, ChatHistoryService
from app.services.conversation_context_service import ConversationContextService
from app.services.conversation_memory_service import ConversationMemoryService
from app.services.conversation_summary_service import ConversationSummaryService
from app.services.document_indexing_service import IMAGE_SOURCE_TYPES, DocumentIndexingService
from app.services.feature_extractor import FeatureExtractor
from app.services.image_digest_service import build_targeted_image_digest
from app.services.ollama_client import OllamaClient
from app.services.ollama_load_guard import OllamaLoadGuard, OllamaOverloadedError
from app.services.query_router import QueryRouter
from app.services.rag_scope import resolve_rag_document_ids
from app.services.requested_file_scope import (
    looks_like_file_inventory_question,
    missing_requested_file_answer,
    resolve_requested_files,
)
from app.services.rate_limiter import RedisRateLimiter
from app.services.rag_log_service import RagLogService
from app.services.rag_service import RagService
from app.services.redis_service import RedisService
from app.services.sql_execution_service import SqlExecutionService
from app.services.sql_schema_card import parse_allowed_tables
from app.services.text_to_sql_service import TextToSqlService
from app.services.tools import ToolExecutor, build_default_tool_registry


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
_sql_allowed_tables = parse_allowed_tables(settings.sql_tool_allowed_tables)
sql_execution_service = SqlExecutionService(
    postgres_dsn=settings.postgres_dsn,
    allowed_tables=_sql_allowed_tables,
    row_limit=settings.sql_tool_row_limit,
    timeout_seconds=settings.sql_tool_timeout_seconds,
)
text_to_sql_service = TextToSqlService(
    ollama_client=ollama_client,
    sql_execution_service=sql_execution_service,
    preferred_model=settings.text_to_sql_model,
    fallback_model=settings.text_to_sql_fallback_model,
    allowed_tables=_sql_allowed_tables,
)
tool_registry = build_default_tool_registry(
    bucket_service=bucket_service,
    rag_service=rag_service,
    sql_execution_service=sql_execution_service,
    text_to_sql_service=text_to_sql_service,
    sql_tools_enabled=settings.sql_tool_enabled,
)
tool_executor = ToolExecutor(
    registry=tool_registry,
    session_factory=db_session_factory,
)
agent_orchestrator = AgentOrchestrator(
    ollama_client=ollama_client,
    tool_executor=tool_executor,
    tool_registry=tool_registry,
    default_model=settings.agent_default_model or settings.default_rag_model,
    max_steps=settings.agent_max_steps,
)
document_indexing_service = DocumentIndexingService(
    session_factory=db_session_factory,
    qdrant_store=qdrant_store,
    ollama_client=ollama_client,
    embedding_model=settings.embedding_model,
    image_vision_enabled=settings.image_vision_enabled,
    image_vision_model=settings.image_vision_model,
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


@app.get("/chat/sessions", response_model=list[ChatSessionResponse])
async def list_chat_sessions(
    user: UserContext = Depends(get_current_user),
) -> list[ChatSessionResponse]:
    sessions = await chat_history_service.list_sessions(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
    )
    return [_chat_session_response(session) for session in sessions]


@app.post("/chat/sessions", response_model=ChatSessionResponse, status_code=201)
async def create_chat_session(
    payload: ChatSessionCreateRequest,
    user: UserContext = Depends(get_current_user),
) -> ChatSessionResponse:
    session = await chat_history_service.create_session(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        title=payload.title,
        active_bucket_id=payload.active_bucket_id,
        model_id=payload.model_id,
        approach=payload.approach,
        metadata=payload.metadata,
    )
    return _chat_session_response(session)


@app.patch("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_chat_session(
    session_id: str,
    payload: ChatSessionUpdateRequest,
    user: UserContext = Depends(get_current_user),
) -> ChatSessionResponse:
    session = await chat_history_service.update_session(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        session_id=session_id,
        title=payload.title,
        active_bucket_id=payload.active_bucket_id,
        model_id=payload.model_id,
        approach=payload.approach,
        metadata=payload.metadata,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return _chat_session_response(session)


@app.delete("/chat/sessions/{session_id}", status_code=204)
async def delete_chat_session(
    session_id: str,
    user: UserContext = Depends(get_current_user),
) -> None:
    deleted = await chat_history_service.delete_session(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        session_id=session_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session not found.")


@app.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def list_chat_session_messages(
    session_id: str,
    user: UserContext = Depends(get_current_user),
) -> list[ChatMessageResponse]:
    messages = await chat_history_service.list_messages(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        session_id=session_id,
    )
    return [_chat_message_response(message) for message in messages]


@app.post(
    "/chat/sessions/{session_id}/attachments",
    response_model=ChatMessageResponse,
    status_code=201,
)
async def create_chat_attachment_message(
    session_id: str,
    payload: ChatAttachmentCreateRequest,
    user: UserContext = Depends(get_current_user),
) -> ChatMessageResponse:
    message = await chat_history_service.save_attachment_message(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        session_id=session_id,
        document_id=payload.document_id,
        file_name=payload.file_name,
        source_type=payload.source_type,
        status=payload.status,
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return _chat_message_response(message)


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    payload: ChatRequest,
    user: UserContext = Depends(get_current_user),
) -> ChatResponse:
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
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        user_message=payload.message,
        response=response,
        metadata={"endpoint": "/chat", "model_id": model},
    )
    _attach_chat_exchange(response, chat_exchange)
    return response


@app.post("/rag/chat", response_model=RagChatResponse)
async def rag_chat(
    request: Request,
    payload: RagChatRequest,
    user: UserContext = Depends(get_current_user),
) -> RagChatResponse:
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
        started_at = perf_counter()
        effective_bucket_ids = _effective_bucket_ids(payload)
        bucket_documents = await _bucket_documents_for_context(
            user=user,
            bucket_ids=effective_bucket_ids,
        )
        effective_document_ids = await resolve_rag_document_ids(
            user=user,
            bucket_service=bucket_service,
            requested_document_ids=payload.document_ids,
            bucket_documents=bucket_documents,
        )
        accessible_documents = await _accessible_documents_for_rag(
            user=user,
            bucket_documents=bucket_documents,
            effective_document_ids=effective_document_ids,
        )
        conversation_context = await _build_conversation_context(
            session_id=payload.session_id,
            message=payload.message,
        )
        if looks_like_file_inventory_question(payload.message):
            response = _file_inventory_response(
                model=payload.model or settings.default_rag_model,
                bucket_ids=effective_bucket_ids,
                documents=accessible_documents,
                latency_ms=int((perf_counter() - started_at) * 1000),
            )
        else:
            requested_files = resolve_requested_files(
                message=payload.message,
                documents=accessible_documents,
            )
            if requested_files.missing_names and not requested_files.matched_documents:
                response = RagChatResponse(
                    model=payload.model or settings.default_rag_model,
                    response=missing_requested_file_answer(requested_files.missing_names),
                    latency_ms=int((perf_counter() - started_at) * 1000),
                    collection=qdrant_store.collection_name,
                    sources=[],
                    score_threshold=None,
                    retrieval={
                        "mode": "requested_file_scope_refusal",
                        "missing_requested_files": requested_files.missing_names,
                        "document_ids": effective_document_ids,
                        "final_top_k": 0,
                    },
                )
            else:
                scoped_document_ids = effective_document_ids
                if requested_files.matched_documents:
                    scoped_document_ids = [
                        document.id for document in requested_files.matched_documents
                    ]
                targeted_image_sources = await _build_targeted_image_sources(
                    message=payload.message,
                    user=user,
                    document_ids=scoped_document_ids,
                    bucket_ids=effective_bucket_ids,
                    bucket_documents=bucket_documents,
                )
                response = await rag_service.answer(
                    message=payload.message,
                    model=payload.model,
                    retrieval_query=str(
                        conversation_context.get("retrieval_query") or payload.message
                    ),
                    top_k=payload.top_k,
                    score_threshold=payload.score_threshold,
                    tenant_id=user.tenant_id,
                    bucket_ids=effective_bucket_ids,
                    features=payload.features,
                    source_types=payload.source_types,
                    document_ids=scoped_document_ids,
                    source_paths=payload.source_paths,
                    max_sources_per_title=payload.max_sources_per_title,
                    max_sources_per_source_type=payload.max_sources_per_source_type,
                    max_sources_per_source_path=payload.max_sources_per_source_path,
                    memory_context=_as_dict(conversation_context.get("prompt_memory")),
                    additional_sources=targeted_image_sources,
                )
                effective_document_ids = scoped_document_ids
        response.conversation_context = conversation_context
        chat_exchange = await _try_save_chat_exchange(
            session_id=payload.session_id,
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            user_message=payload.message,
            response=response,
            metadata={
                "endpoint": "/rag/chat",
                "collection": response.collection,
                "model_id": response.model,
                "approach": payload.approach,
                "active_bucket_id": payload.active_bucket_id,
                "bucket_ids": effective_bucket_ids,
                "document_ids": effective_document_ids,
                "sources": [
                    {
                        "id": source.id,
                        "score": source.score,
                        "title": source.title,
                        "source_type": source.source_type,
                        "source_path": source.source_path,
                    }
                    for source in response.sources
                ],
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


def _effective_bucket_ids(payload: RagChatRequest) -> list[str]:
    values = [*payload.bucket_ids]
    if payload.active_bucket_id:
        values.append(payload.active_bucket_id)
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


async def _bucket_documents_for_context(
    *,
    user: UserContext,
    bucket_ids: list[str],
) -> list[DocumentAsset]:
    documents: list[DocumentAsset] = []
    seen: set[str] = set()
    for bucket_id in bucket_ids:
        rows = await bucket_service.list_documents(user=user, bucket_id=bucket_id)
        if rows is None:
            continue
        for document, _bucket_link in rows:
            if document.id in seen:
                continue
            seen.add(document.id)
            documents.append(document)
    return documents


def _document_ids(documents: list[DocumentAsset]) -> list[str]:
    return [document.id for document in documents if document.status == "indexed"]


def _looks_like_bucket_file_inventory_question(message: str) -> bool:
    return looks_like_file_inventory_question(message)


async def _accessible_documents_for_rag(
    *,
    user: UserContext,
    bucket_documents: list[DocumentAsset],
    effective_document_ids: list[str],
) -> list[DocumentAsset]:
    if bucket_documents:
        allowed_ids = set(effective_document_ids)
        return [
            document
            for document in bucket_documents
            if document.id in allowed_ids or not allowed_ids
        ]
    if not effective_document_ids:
        return []
    available = await bucket_service.list_available_documents(user=user)
    allowed_ids = set(effective_document_ids)
    return [document for document in available if document.id in allowed_ids]


def _file_inventory_response(
    *,
    model: str,
    bucket_ids: list[str],
    documents: list[DocumentAsset],
    latency_ms: int,
) -> RagChatResponse:
    indexed_documents = [document for document in documents if document.status == "indexed"]
    scope_label = "выбранном bucket" if bucket_ids else "доступных документах"
    if not indexed_documents:
        answer = f"В {scope_label} нет доступных файлов."
    else:
        lines = [
            f"- `{document.file_name}` — status `{document.status}`"
            for document in indexed_documents
        ]
        answer = f"В {scope_label} доступны файлы:\n" + "\n".join(lines)
    source_content = "\n".join(
        f"{document.file_name} | status={document.status} | document_id={document.id}"
        for document in indexed_documents
    ) or "Документы не найдены."
    return RagChatResponse(
        model=model,
        response=answer,
        latency_ms=latency_ms,
        collection=qdrant_store.collection_name,
        sources=[
            SourceChunk(
                id="file-inventory",
                score=None,
                title="Accessible file inventory",
                source_type="bucket_metadata",
                source_path=None,
                content=source_content,
                metadata={"bucket_ids": bucket_ids},
            )
        ],
        score_threshold=None,
        retrieval={
            "mode": "file_inventory",
            "bucket_ids": bucket_ids,
            "document_ids": [document.id for document in indexed_documents],
            "final_top_k": len(indexed_documents),
        },
    )


def _bucket_file_inventory_response(
    *,
    message: str,
    model: str,
    bucket_ids: list[str],
    documents: list[DocumentAsset],
    latency_ms: int,
) -> RagChatResponse:
    del message
    return _file_inventory_response(
        model=model,
        bucket_ids=bucket_ids,
        documents=documents,
        latency_ms=latency_ms,
    )


async def _build_targeted_image_sources(
    *,
    message: str,
    user: UserContext,
    document_ids: list[str],
    bucket_ids: list[str],
    bucket_documents: list[DocumentAsset],
) -> list[SourceChunk]:
    if not settings.image_vision_enabled or not settings.image_vision_model.strip():
        return []
    if not _looks_like_targeted_image_reanalysis(message):
        return []

    documents = await _targeted_image_documents(
        user=user,
        document_ids=document_ids,
        bucket_ids=bucket_ids,
        bucket_documents=bucket_documents,
    )
    if not documents:
        return []

    sources: list[SourceChunk] = []
    for document, bucket_id in documents[:3]:
        try:
            source = await _build_targeted_image_source(
                document=document,
                bucket_id=bucket_id,
                message=message,
            )
        except Exception:
            logger.exception("Targeted image re-analysis failed")
            continue
        if source is not None:
            sources.append(source)
    return sources


async def _targeted_image_documents(
    *,
    user: UserContext,
    document_ids: list[str],
    bucket_ids: list[str],
    bucket_documents: list[DocumentAsset],
) -> list[tuple[DocumentAsset, str]]:
    documents: list[tuple[DocumentAsset, str]] = []
    seen: set[str] = set()

    if document_ids:
        bucket_id = bucket_ids[0] if bucket_ids else PERSONAL_INDEX_BUCKET_ID
        for document_id in document_ids:
            document = await bucket_service.get_document(user=user, document_id=document_id)
            if document is None or document.id in seen:
                continue
            if _is_indexed_image_document(document):
                documents.append((document, bucket_id))
                seen.add(document.id)
        return documents

    bucket_id = bucket_ids[0] if bucket_ids else PERSONAL_INDEX_BUCKET_ID
    for document in bucket_documents:
        if document.id in seen:
            continue
        if _is_indexed_image_document(document):
            documents.append((document, bucket_id))
            seen.add(document.id)
    return documents


async def _build_targeted_image_source(
    *,
    document: DocumentAsset,
    bucket_id: str,
    message: str,
) -> SourceChunk | None:
    source_path = Path(document.source_path)
    if not source_path.is_file():
        return None

    previous_digest = _previous_image_digest(document=document, bucket_id=bucket_id)
    digest = await build_targeted_image_digest(
        source_path,
        question=message,
        ollama_client=ollama_client,
        vision_model=settings.image_vision_model,
        previous_digest=previous_digest,
    )
    content = str(digest.get("content") or "").strip()
    if not content:
        return None

    evidence_content = "\n".join(
        [
            f"File: {document.file_name}",
            "Block type: image_targeted_digest",
            f"Focused question: {message.strip()}",
            "Targeted vision digest:",
            content,
        ]
    )
    features = feature_extractor.extract(f"{message}\n{content}")
    point_id = _targeted_image_point_id(
        document_id=document.id,
        bucket_id=bucket_id,
        question=message,
        vision_model=settings.image_vision_model,
    )
    document_metadata = {
        "document_asset_id": document.id,
        "document_file_name": document.file_name,
        "document_visibility": document.visibility,
        "prompt_question": message.strip(),
        "block_type": "image_targeted_digest",
        "digest_type": "targeted_visual_answer",
        "vision_model": settings.image_vision_model,
        "image_width": digest.get("image_width"),
        "image_height": digest.get("image_height"),
        "image_format": digest.get("image_format"),
    }
    payload = {
        "document_id": document.id,
        "tenant_id": document.tenant_id,
        "bucket_id": bucket_id,
        "chunk_id": point_id,
        "chunk_index": 0,
        "domain": "uploaded_image",
        "source_type": "image_targeted_digest",
        "source_path": document.source_path,
        "processing_status": "indexed",
        "title": f"{document.file_name} - targeted image analysis",
        "content": evidence_content,
        "feature": features,
        "document_metadata": document_metadata,
        "language": "ru",
    }
    vector = await ollama_client.embed(settings.embedding_model, evidence_content)
    qdrant_store.ensure_collection(vector_size=len(vector), recreate=False)
    qdrant_store.upsert_chunks([(point_id, vector, payload)])
    return SourceChunk(
        id=point_id,
        score=None,
        title=str(payload["title"]),
        source_type="image_targeted_digest",
        source_path=document.source_path,
        feature=features,
        content=evidence_content,
        metadata={
            "document_id": document.id,
            "tenant_id": document.tenant_id,
            "bucket_id": bucket_id,
            "chunk_id": point_id,
            "chunk_index": 0,
            "domain": "uploaded_image",
            "processing_status": "indexed",
            "document_metadata": document_metadata,
            "language": "ru",
        },
    )


def _previous_image_digest(*, document: DocumentAsset, bucket_id: str) -> str | None:
    sources = qdrant_store.scroll(
        limit=1,
        tenant_id=document.tenant_id,
        bucket_ids=[bucket_id],
        source_types=["image_digest"],
        document_ids=[document.id],
    )
    if not sources:
        return None
    return sources[0].content


def _looks_like_targeted_image_reanalysis(message: str) -> bool:
    normalized = message.lower()
    reanalysis_markers = (
        "повторно проанализ",
        "проанализируй повторно",
        "проанализируй еще",
        "проанализируй ещё",
        "посмотри еще",
        "посмотри ещё",
        "ещё раз",
        "еще раз",
        "уточни",
        "детальнее",
        "подробнее",
    )
    visual_attribute_markers = (
        "цвет",
        "оттен",
        "форма",
        "размер",
        "располож",
        "слева",
        "справа",
        "сверху",
        "снизу",
        "фон",
        "материал",
        "ствол",
        "дерев",
        "листв",
        "видно",
        "выгляд",
    )
    image_markers = (
        "картин",
        "изображ",
        "фото",
        "picture",
        "image",
        "photo",
    )
    return (
        any(marker in normalized for marker in reanalysis_markers)
        and (
            any(marker in normalized for marker in visual_attribute_markers)
            or any(marker in normalized for marker in image_markers)
        )
    ) or any(marker in normalized for marker in visual_attribute_markers)


def _is_indexed_image_document(document: DocumentAsset) -> bool:
    return (
        document.status == "indexed"
        and document.source_type.lower() in IMAGE_SOURCE_TYPES
    )


def _targeted_image_point_id(
    *,
    document_id: str,
    bucket_id: str,
    question: str,
    vision_model: str,
) -> str:
    normalized_question = " ".join(question.lower().split())
    return str(
        uuid5(
            NAMESPACE_URL,
            f"image-targeted-digest:{document_id}:{bucket_id}:{vision_model}:{normalized_question}",
        )
    )


async def _try_save_chat_exchange(
    *,
    session_id: str | None,
    tenant_id: str | None,
    user_id: str | None,
    user_message: str,
    response: ChatResponse,
    metadata: dict[str, object],
) -> ChatExchangeRecord | None:
    try:
        return await chat_history_service.save_exchange(
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
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


def _chat_session_response(session: ChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=session.id,
        title=session.title or "Untitled chat",
        tenant_id=session.tenant_id,
        owner_user_id=session.owner_user_id,
        active_bucket_id=session.active_bucket_id,
        model_id=session.model_id,
        approach=session.approach,
        metadata=session.metadata_json or {},
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


def _chat_message_response(message: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        model=message.model,
        provider=message.provider,
        latency_ms=message.latency_ms,
        metadata=message.metadata_json or {},
        created_at=message.created_at.isoformat(),
    )


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


app.include_router(
    create_agent_router(
        agent_orchestrator=agent_orchestrator,
        build_conversation_context=_build_conversation_context,
        save_chat_exchange=_try_save_chat_exchange,
        enforce_rate_limit=_enforce_rate_limit,
        attach_chat_exchange=_attach_chat_exchange,
    )
)