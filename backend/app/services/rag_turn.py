from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter

from app.clients.qdrant_store import QdrantStore
from app.core.config import get_settings
from app.core.errors import ProviderError
from app.db.models import DocumentAsset
from app.models.chat import RagChatRequest, RagChatResponse, SourceChunk
from app.services.access_policy import UserContext
from app.services.bucket_service import BucketService
from app.services.chat_history_service import ChatHistoryService
from app.services.conversation_context_service import ConversationContextService
from app.services.conversation_memory_service import ConversationMemoryService
from app.services.conversation_summary_service import ConversationSummaryService
from app.services.external_scope import SESSION_SEEN_NON_SYNTHETIC, session_seen_non_synthetic
from app.services.feature_extractor import FeatureExtractor
from app.services.rag_scope import resolve_rag_document_ids
from app.services.rag_service import RagService
from app.services.requested_file_scope import (
    looks_like_file_inventory_question,
    missing_requested_file_answer,
    resolve_requested_files,
)
from app.services.sales_composer import SalesComposer
from app.services.sales_scope import is_sales_rag_scope
from app.services.sticky_document_scope import resolve_sticky_document_scope
from app.services.targeted_image import _build_targeted_image_sources


logger = logging.getLogger(__name__)
settings = get_settings()

bucket_service: BucketService
chat_history_service: ChatHistoryService
conversation_context_service: ConversationContextService
conversation_memory_service: ConversationMemoryService
conversation_summary_service: ConversationSummaryService
feature_extractor: FeatureExtractor
qdrant_store: QdrantStore
rag_service: RagService
sales_composer: SalesComposer


def configure_rag_turn(
    *,
    bucket_service: BucketService,
    chat_history_service: ChatHistoryService,
    conversation_context_service: ConversationContextService,
    conversation_memory_service: ConversationMemoryService,
    conversation_summary_service: ConversationSummaryService,
    feature_extractor: FeatureExtractor,
    qdrant_store: QdrantStore,
    rag_service: RagService,
    sales_composer: SalesComposer,
) -> None:
    globals()["bucket_service"] = bucket_service
    globals()["chat_history_service"] = chat_history_service
    globals()["conversation_context_service"] = conversation_context_service
    globals()["conversation_memory_service"] = conversation_memory_service
    globals()["conversation_summary_service"] = conversation_summary_service
    globals()["feature_extractor"] = feature_extractor
    globals()["qdrant_store"] = qdrant_store
    globals()["rag_service"] = rag_service
    globals()["sales_composer"] = sales_composer


@dataclass(frozen=True)
class RagTurnResult:
    response: RagChatResponse
    effective_bucket_ids: list[str]
    effective_document_ids: list[str]


async def run_rag_turn(
    *,
    payload: RagChatRequest,
    user: UserContext,
    started_at: float,
) -> RagTurnResult:
    effective_bucket_ids = _effective_bucket_ids(payload)
    document_ids, _chat_document_ids = await _document_ids_for_turn(
        user=user,
        session_id=payload.session_id,
        message=payload.message,
        requested_document_ids=payload.document_ids,
    )
    payload = payload.model_copy(update={"document_ids": document_ids})
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
                source_paths=payload.source_paths,
            )
            session_seen = await _session_seen_non_synthetic_flag(
                user=user,
                session_id=payload.session_id,
            )
            try:
                answerer = (
                    sales_composer
                    if is_sales_rag_scope(effective_bucket_ids)
                    else rag_service
                )
                response = await answerer.answer(
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
                    allowed_source_paths=[
                        document.source_path
                        for document in accessible_documents
                        if document.source_path
                        and (
                            not scoped_document_ids
                            or document.id in set(scoped_document_ids)
                        )
                    ],
                    max_sources_per_title=payload.max_sources_per_title,
                    max_sources_per_source_type=payload.max_sources_per_source_type,
                    max_sources_per_source_path=payload.max_sources_per_source_path,
                    memory_context=_as_dict(conversation_context.get("prompt_memory")),
                    additional_sources=targeted_image_sources,
                    approach=payload.approach,
                    session_seen_non_synthetic=session_seen,
                )
            except ProviderError as exc:
                if exc.extra.get("persist_session_seen_non_synthetic"):
                    await _persist_session_seen_non_synthetic(
                        user=user,
                        session_id=payload.session_id,
                    )
                raise
            effective_document_ids = scoped_document_ids
    response.conversation_context = conversation_context
    scope = response.retrieval.get("external_scope")
    if isinstance(scope, dict) and scope.get("persist_session_seen_non_synthetic") is True:
        await _persist_session_seen_non_synthetic(
            user=user,
            session_id=payload.session_id,
        )
    return RagTurnResult(
        response=response,
        effective_bucket_ids=effective_bucket_ids,
        effective_document_ids=effective_document_ids,
    )


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


async def _document_ids_for_turn(
    *,
    user: UserContext,
    session_id: str | None,
    message: str,
    requested_document_ids: list[str],
) -> tuple[list[str], list[str]]:
    metadata = await chat_history_service.get_session_metadata(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        session_id=session_id,
    )
    attached = metadata.get("attached_document_ids")
    attached_document_ids = [
        item.strip()
        for item in attached
        if isinstance(item, str) and item.strip()
    ] if isinstance(attached, list) else []
    active = metadata.get("active_document_id")
    active_document_id = active.strip() if isinstance(active, str) else None
    documents = await bucket_service.list_available_documents(user=user)
    scope = resolve_sticky_document_scope(
        message=message,
        requested_document_ids=requested_document_ids,
        attached_document_ids=attached_document_ids,
        active_document_id=active_document_id,
        documents=documents,
    )
    if (
        scope.narrowed
        and session_id
        and scope.active_document_id
        and scope.active_document_id != active_document_id
    ):
        await chat_history_service.update_session(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            session_id=session_id,
            metadata={"active_document_id": scope.active_document_id},
        )
    if scope.narrowed:
        return scope.document_ids, attached_document_ids
    return requested_document_ids, attached_document_ids


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


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


async def _session_seen_non_synthetic_flag(
    *,
    user: UserContext,
    session_id: str | None,
) -> bool:
    try:
        metadata = await chat_history_service.get_session_metadata(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            session_id=session_id,
        )
    except Exception:
        logger.exception("Failed to read chat session metadata for external scope")
        return False
    return session_seen_non_synthetic(metadata)


async def _persist_session_seen_non_synthetic(
    *,
    user: UserContext,
    session_id: str | None,
) -> None:
    if not session_id:
        return
    try:
        await chat_history_service.update_session(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            session_id=session_id,
            metadata={SESSION_SEEN_NON_SYNTHETIC: True},
        )
    except Exception:
        logger.exception("Failed to persist session_seen_non_synthetic")
