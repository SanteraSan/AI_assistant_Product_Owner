import logging
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.clients.qdrant_store import QdrantStore
from app.core.config import get_settings
from app.core.errors import ProviderError
from app.core.log_redaction import install_secret_redaction_filter, redact_secrets
from app.db.session import (
    create_engine,
    create_session_factory,
    database_available,
    init_db,
)
from app.dependencies.auth import get_current_user
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    RagChatRequest,
    RagChatResponse,
    reveal_provider_api_key,
)
from app.routers.agent import create_agent_router
from app.routers.buckets import create_bucket_router
from app.routers.chat import create_chat_router
from app.routers.integrations import create_integrations_router
from app.services.access_policy import UserContext
from app.services.agent.orchestrator import AgentOrchestrator
from app.services.agent.langgraph_adapter import LangGraphAgentAdapter
from app.services.bucket_service import BucketService
from app.services.chat_history_service import ChatExchangeRecord, ChatHistoryService
from app.services.conversation_context_service import ConversationContextService
from app.services.conversation_memory_service import ConversationMemoryService
from app.services.conversation_summary_service import ConversationSummaryService
from app.services.document_indexing_service import DocumentIndexingService
from app.services.external_db_sync_service import ExternalDbSyncService
from app.services.external_scope import decide_external_scope
from app.services.feature_extractor import FeatureExtractor
from app.services.feedback_counts import FeedbackCountService
from app.services.indexing_event_publisher import IndexingEventPublisher
from app.services.indexing_job_dispatcher import IndexingJobDispatcher
from app.services.integration_ingest_service import IntegrationIngestService
from app.services.llm import build_model_gateway
from app.services.metrics import AppMetrics, metrics_http_middleware, prometheus_response
from app.services.object_storage import build_object_storage, resolve_upload_root
from app.services.ollama_client import OllamaClient
from app.services.ollama_load_guard import OllamaLoadGuard, OllamaOverloadedError
from app.services.query_router import QueryRouter
from app.services.rate_limiter import RedisRateLimiter
from app.services.rag_log_service import RagLogService
from app.services.rag_service import RagService
from app.services.rag_turn import (
    _build_conversation_context,
    _document_ids_for_turn,
    _session_seen_non_synthetic_flag,
    configure_rag_turn,
    run_rag_turn,
)
from app.services.redis_service import RedisService
from app.services.sales_composer import SalesComposer
from app.services.sales_deal_repository import PostgresDealCardRepository
from app.services.sql_execution_service import SqlExecutionService
from app.services.sql_schema_card import parse_allowed_tables
from app.services.text_to_sql_service import TextToSqlService
from app.services.targeted_image import configure_targeted_image
from app.services.tools import ToolExecutor, build_default_tool_registry


settings = get_settings()
logger = logging.getLogger(__name__)
app_metrics = AppMetrics(enabled=settings.metrics_enabled)
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
model_gateway = build_model_gateway(settings=settings, ollama_client=ollama_client)
qdrant_store = QdrantStore(
    url=settings.qdrant_url,
    collection_name=settings.qdrant_collection,
    check_compatibility=settings.qdrant_check_compatibility,
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
    model_gateway=model_gateway,
)
sales_composer = SalesComposer(
    rag_service=rag_service,
    deal_repository=PostgresDealCardRepository(db_session_factory),
    model_gateway=model_gateway,
    default_model=settings.default_rag_model,
    generation_keep_alive=settings.rag_generation_keep_alive,
    generation_temperature=settings.rag_generation_temperature,
    generation_top_p=settings.rag_generation_top_p,
    collection_name=settings.qdrant_collection,
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
object_storage = build_object_storage(
    enabled=settings.object_storage_enabled,
    upload_root=resolve_upload_root(settings.raw_data_dir),
    endpoint_url=settings.object_storage_endpoint,
    access_key=settings.object_storage_access_key,
    secret_key=settings.object_storage_secret_key,
    bucket=settings.object_storage_bucket,
    region=settings.object_storage_region,
)
bucket_service = BucketService(
    session_factory=db_session_factory,
    raw_data_dir=settings.raw_data_dir,
    object_storage=object_storage,
)
feedback_count_service = FeedbackCountService(session_factory=db_session_factory)
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
    ollama_client=ollama_client,
    object_storage=object_storage,
    image_vision_enabled=settings.image_vision_enabled,
    image_vision_model=settings.image_vision_model,
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
langgraph_agent_adapter = (
    LangGraphAgentAdapter(
        ollama_client=ollama_client,
        tool_executor=tool_executor,
        tool_registry=tool_registry,
        default_model=settings.agent_default_model or settings.default_rag_model,
        max_steps=settings.agent_max_steps,
    )
    if settings.agent_langgraph_enabled
    else None
)
indexing_event_publisher = (
    IndexingEventPublisher(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        topic=settings.kafka_indexing_topic,
        document_events_topic=settings.kafka_document_events_topic,
    )
    if settings.kafka_enabled
    else None
)
document_indexing_service = DocumentIndexingService(
    session_factory=db_session_factory,
    qdrant_store=qdrant_store,
    ollama_client=ollama_client,
    embedding_model=settings.embedding_model,
    image_vision_enabled=settings.image_vision_enabled,
    image_vision_model=settings.image_vision_model,
    event_publisher=indexing_event_publisher,
    object_storage=object_storage,
    metrics=app_metrics,
)
integration_ingest_service = IntegrationIngestService(
    bucket_service=bucket_service,
    default_bucket_name=settings.integrations_default_bucket_name,
)
external_db_sync_service = ExternalDbSyncService(
    session_factory=db_session_factory,
    external_postgres_dsn=settings.external_postgres_dsn,
)
indexing_job_dispatcher = IndexingJobDispatcher(
    kafka_enabled=settings.kafka_enabled,
    document_indexing_service=document_indexing_service,
    indexing_event_publisher=indexing_event_publisher,
)
configure_rag_turn(
    bucket_service=bucket_service,
    chat_history_service=chat_history_service,
    conversation_context_service=conversation_context_service,
    conversation_memory_service=conversation_memory_service,
    conversation_summary_service=conversation_summary_service,
    feature_extractor=feature_extractor,
    qdrant_store=qdrant_store,
    rag_service=rag_service,
    sales_composer=sales_composer,
)
configure_targeted_image(
    bucket_service=bucket_service,
    object_storage=object_storage,
    ollama_client=ollama_client,
    qdrant_store=qdrant_store,
    feature_extractor=feature_extractor,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    install_secret_redaction_filter()
    try:
        await init_db(
            db_engine,
            auto_create=settings.database_auto_create_tables,
        )
    except Exception:
        logger.exception("PostgreSQL initialization failed")
    if indexing_event_publisher is not None:
        try:
            await indexing_event_publisher.start()
        except Exception:
            logger.exception("Kafka indexing producer failed to start")
    try:
        yield
    finally:
        if indexing_event_publisher is not None:
            await indexing_event_publisher.stop()
        await ollama_client.aclose()
        await model_gateway.aclose()
        if redis_service is not None:
            await redis_service.aclose()
        await db_engine.dispose()


def create_app() -> FastAPI:
    install_secret_redaction_filter()
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
        indexing_job_dispatcher=indexing_job_dispatcher,
        default_tenant_id=settings.default_tenant_id,
        feedback_count_service=feedback_count_service,
    )
)
app.include_router(create_chat_router(history_service=chat_history_service))
app.include_router(
    create_integrations_router(
        integration_ingest_service=integration_ingest_service,
        external_db_sync_service=external_db_sync_service,
        document_indexing_service=document_indexing_service,
        indexing_job_dispatcher=indexing_job_dispatcher,
    )
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = _request_id_from_header(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def http_metrics_middleware(request: Request, call_next):
    return await metrics_http_middleware(request, call_next, app_metrics)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = _request_id_from_request(request)
    detail = redact_secrets(exc.detail) if isinstance(exc.detail, str) else exc.detail
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": detail,
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
    # exc.body is the raw payload and can contain provider_api_key. Do not return it.
    return JSONResponse(
        status_code=422,
        content={
            "detail": _redact_validation_errors(exc.errors()),
            "error_type": "validation_error",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(ProviderError)
async def provider_exception_handler(request: Request, exc: ProviderError) -> JSONResponse:
    request_id = _request_id_from_request(request)
    extra = {
        key: value
        for key, value in exc.extra.items()
        if key != "persist_session_seen_non_synthetic"
    }
    detail = redact_secrets(exc.detail) if isinstance(exc.detail, str) else exc.detail
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": detail,
            "error_type": exc.error_type.value,
            "request_id": request_id,
            **extra,
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
        **model_gateway.health_snapshot(),
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


@app.get("/metrics")
async def metrics_prometheus():
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="metrics disabled")
    return prometheus_response(app_metrics)


@app.get("/metrics/summary")
async def metrics_summary() -> dict[str, object]:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="metrics disabled")
    return app_metrics.summary()


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
    seen = await _session_seen_non_synthetic_flag(
        user=user,
        session_id=payload.session_id,
    )
    decide_external_scope(
        approach=payload.approach,
        endpoint="chat",
        session_seen_non_synthetic_flag=seen,
        retrieved_non_synthetic=False,
    )

    try:
        result = await model_gateway.generate(
            model=model,
            prompt=payload.message,
            approach=payload.approach,
            endpoint="chat",
            allow_external_fallback=False,
            think=False,
            provider_api_key=reveal_provider_api_key(payload.provider_api_key),
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
        response=result.response,
        latency_ms=latency_ms,
        provider=result.provider,
        provider_response_model_id=result.provider_response_model_id,
        fallback_from=result.fallback_from,
        fallback_to=result.fallback_to,
        finish_reason=result.finish_reason,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_estimated=result.cost_estimated,
        estimated_cost_usd=result.estimated_cost_usd,
    )
    chat_exchange = await _try_save_chat_exchange(
        session_id=payload.session_id,
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        user_message=payload.message,
        response=response,
        metadata={"endpoint": "/chat", "model_id": model, "approach": payload.approach},
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
        outcome = "error"
        turn = await run_rag_turn(
            payload=payload,
            user=user,
            started_at=started_at,
        )
        response = turn.response
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
                "bucket_ids": turn.effective_bucket_ids,
                "document_ids": turn.effective_document_ids,
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
        outcome = "success"
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
    finally:
        app_metrics.observe_rag(
            outcome=outcome,
            duration_seconds=perf_counter() - started_at,
        )


# A 422 for another field still carries the raw body in `input`.
_SECRET_FIELD_NAMES = frozenset(
    {
        "provider_api_key",
        "api_key",
        "gemini_api_key",
        "openrouter_api_key",
        "x-api-key",
        "x-goog-api-key",
    }
)


def _redact_validation_errors(errors: list[object]) -> list[object]:
    prepared: list[object] = []
    for error in errors:
        if not isinstance(error, dict):
            prepared.append(error)
            continue
        item = dict(error)
        loc = item.get("loc")
        if isinstance(loc, (list, tuple)) and any(part == "provider_api_key" for part in loc):
            item["input"] = "***"
        prepared.append(item)
    redacted = _redact_nested_strings(prepared)
    if isinstance(redacted, list):
        return redacted
    return prepared


def _redact_nested_strings(value: object) -> object:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in _SECRET_FIELD_NAMES:
                redacted[key] = "***"
                continue
            redacted[key] = _redact_nested_strings(item)
        return redacted
    if isinstance(value, list):
        return [_redact_nested_strings(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_nested_strings(item) for item in value)
    return value


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
    features = {
        "kafka_enabled": settings.kafka_enabled,
        "object_storage_enabled": settings.object_storage_enabled,
        "metrics_enabled": settings.metrics_enabled,
        "agent_langgraph_enabled": settings.agent_langgraph_enabled,
    }
    if settings.kafka_enabled:
        dependencies["kafka_reachable"] = await _kafka_bootstrap_reachable()
    if settings.object_storage_enabled:
        dependencies["object_storage_reachable"] = await _object_storage_reachable()
    ready = all(bool(value) for value in dependencies.values())
    return {
        "status": "ready" if ready else "degraded",
        "dependencies": dependencies,
        "features": features,
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


async def _kafka_bootstrap_reachable() -> bool:
    try:
        from aiokafka import AIOKafkaProducer

        producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
        await producer.start()
        await producer.stop()
        return True
    except Exception:
        logger.debug("Kafka bootstrap probe failed", exc_info=True)
        return False


async def _object_storage_reachable() -> bool:
    try:
        ref = await asyncio.to_thread(
            object_storage.put,
            "__taskflow_health_probe__",
            b"ok",
        )
        await asyncio.to_thread(object_storage.delete, ref)
        return True
    except Exception:
        logger.debug("Object storage probe failed", exc_info=True)
        return False


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


def _attach_chat_exchange(
    response: ChatResponse,
    chat_exchange: ChatExchangeRecord | None,
) -> None:
    if chat_exchange is None:
        return
    response.session_id = chat_exchange.session_id
    response.user_message_id = chat_exchange.user_message_id
    response.assistant_message_id = chat_exchange.assistant_message_id


app.include_router(
    create_agent_router(
        agent_orchestrator=agent_orchestrator,
        build_conversation_context=_build_conversation_context,
        resolve_document_ids=_document_ids_for_turn,
        save_chat_exchange=_try_save_chat_exchange,
        enforce_rate_limit=_enforce_rate_limit,
        attach_chat_exchange=_attach_chat_exchange,
        metrics=app_metrics,
        langgraph_adapter=langgraph_agent_adapter,
        agent_langgraph_enabled=settings.agent_langgraph_enabled,
    )
)
