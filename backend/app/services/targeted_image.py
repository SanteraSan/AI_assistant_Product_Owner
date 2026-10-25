from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

from app.clients.qdrant_store import QdrantStore
from app.core.config import get_settings
from app.db.models import DocumentAsset
from app.models.chat import SourceChunk
from app.services.access_policy import UserContext
from app.services.bucket_service import PERSONAL_INDEX_BUCKET_ID, BucketService
from app.services.document_indexing_service import IMAGE_SOURCE_TYPES
from app.services.feature_extractor import FeatureExtractor
from app.services.image_digest_service import build_targeted_image_digest
from app.services.object_storage import ObjectStorage, display_name_from_ref
from app.services.ollama_client import OllamaClient


logger = logging.getLogger(__name__)
settings = get_settings()

bucket_service: BucketService
object_storage: ObjectStorage
ollama_client: OllamaClient
qdrant_store: QdrantStore
feature_extractor: FeatureExtractor


def configure_targeted_image(
    *,
    bucket_service: BucketService,
    object_storage: ObjectStorage,
    ollama_client: OllamaClient,
    qdrant_store: QdrantStore,
    feature_extractor: FeatureExtractor,
) -> None:
    module = globals()
    module["bucket_service"] = bucket_service
    module["object_storage"] = object_storage
    module["ollama_client"] = ollama_client
    module["qdrant_store"] = qdrant_store
    module["feature_extractor"] = feature_extractor


async def _build_targeted_image_sources(
    *,
    message: str,
    user: UserContext,
    document_ids: list[str],
    bucket_ids: list[str],
    bucket_documents: list[DocumentAsset],
    source_paths: list[str] | None = None,
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
    documents = _limit_targeted_image_documents(documents, source_paths or [])
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


def _limit_targeted_image_documents(
    documents: list[tuple[DocumentAsset, str]],
    source_paths: list[str],
) -> list[tuple[DocumentAsset, str]]:
    """An explicit source_path pin must not be replaced by other bucket images."""
    pinned = {path.strip() for path in source_paths if path and path.strip()}
    if not pinned:
        return documents
    return [
        item
        for item in documents
        if (item[0].source_path or "").strip() in pinned
    ]


async def _build_targeted_image_source(
    *,
    document: DocumentAsset,
    bucket_id: str,
    message: str,
) -> SourceChunk | None:
    if not object_storage.exists(document.source_path):
        return None

    previous_digest = _previous_image_digest(document=document, bucket_id=bucket_id)
    with TemporaryDirectory(prefix="targeted-vision-") as temporary_dir_name:
        temporary_path = Path(temporary_dir_name) / display_name_from_ref(document.source_path)
        object_storage.materialize(document.source_path, temporary_path)
        digest = await build_targeted_image_digest(
            temporary_path,
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
    has_visual_attribute = _contains_visual_attribute(normalized, visual_attribute_markers)
    return (
        any(marker in normalized for marker in reanalysis_markers)
        and (
            has_visual_attribute
            or any(marker in normalized for marker in image_markers)
        )
    ) or has_visual_attribute


def _contains_visual_attribute(normalized: str, markers: tuple[str, ...]) -> bool:
    for marker in markers:
        if marker == "материал":
            if _contains_material_attribute(normalized):
                return True
            continue
        if marker in normalized:
            return True
    return False


def _contains_material_attribute(normalized: str) -> bool:
    """Visual 'what material', not the supplies stem in «покупки материалов»."""
    start = 0
    needle = "материал"
    while True:
        index = normalized.find(needle, start)
        if index < 0:
            return False
        end = index + len(needle)
        if normalized.startswith("ов", end):
            start = end
            continue
        return True


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
