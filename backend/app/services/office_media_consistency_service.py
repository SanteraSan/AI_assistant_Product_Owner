from collections import defaultdict
from pathlib import Path

from app.services.document_loader import RawDocument, _features_from_text, _stable_document_id

OFFICE_MEDIA_CONSISTENCY_SOURCE_TYPE = "office_media_consistency"
CONSISTENCY_STATUS_POTENTIAL_MISMATCH = "potential_mismatch"
CONSISTENCY_STATUS_REVIEW_NEEDED = "review_needed"


def build_office_media_consistency_documents(
    documents: list[RawDocument],
) -> list[RawDocument]:
    document_text_by_path = _document_text_by_path(documents)
    visual_documents = _embedded_visual_documents(documents)
    ocr_by_key = _embedded_visual_documents_by_key(
        documents,
        source_type="image_ocr",
    )

    consistency_documents: list[RawDocument] = []
    for visual_document in visual_documents:
        embedded_key = _embedded_key(visual_document)
        if embedded_key is None:
            continue

        document_text = document_text_by_path.get(visual_document.source_path, "")
        if not document_text.strip():
            continue

        ocr_document = ocr_by_key.get(embedded_key)
        visual_text = "\n".join(
            value
            for value in [
                visual_document.content,
                ocr_document.content if ocr_document else "",
            ]
            if value.strip()
        )
        status = _consistency_status(document_text=document_text, visual_text=visual_text)
        reason = _consistency_reason(status=status, document_text=document_text, visual_text=visual_text)
        parent_source_type = str(visual_document.metadata.get("parent_source_type") or "")
        embedded_path = str(visual_document.metadata.get("embedded_path") or "")
        embedded_image_index = int(visual_document.metadata.get("embedded_image_index") or 0)

        content = "\n".join(
            [
                f"File: {visual_document.source_path}",
                f"Embedded image: {embedded_path}",
                "Block type: office_media_consistency",
                f"Consistency status: {status}",
                f"Consistency reason: {reason}",
                "Document text evidence:",
                _compact_excerpt(document_text, max_chars=900),
                "Embedded image digest evidence:",
                visual_document.content,
                "Embedded image OCR evidence:",
                ocr_document.content if ocr_document else "not available",
            ]
        )
        consistency_documents.append(
            RawDocument(
                id=(
                    f"{_stable_document_id_from_source_path(visual_document.source_path)}:"
                    f"embedded_image:{embedded_image_index}:media_consistency"
                ),
                title=(
                    f"{visual_document.title or 'Office media'} - consistency review"
                ),
                content=content,
                source_type=OFFICE_MEDIA_CONSISTENCY_SOURCE_TYPE,
                source_path=visual_document.source_path,
                domain=visual_document.domain,
                feature=_features_from_text(content),
                metadata={
                    "file_name": visual_document.metadata.get("file_name"),
                    "block_type": OFFICE_MEDIA_CONSISTENCY_SOURCE_TYPE,
                    "parent_source_type": parent_source_type,
                    "embedded_path": embedded_path,
                    "embedded_image_index": embedded_image_index,
                    "compared_source_types": [
                        "docx" if parent_source_type == "docx" else "excel_row",
                        "image_digest",
                        "image_ocr",
                    ],
                    "consistency_status": status,
                    "consistency_reason": reason,
                },
                tenant_id=visual_document.tenant_id,
                bucket_id=visual_document.bucket_id,
            )
        )

    return consistency_documents


def _document_text_by_path(documents: list[RawDocument]) -> dict[str, str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for document in documents:
        if document.source_type in {"docx", "excel_row", "excel_chart"}:
            grouped[document.source_path].append(document.content)
    return {
        source_path: "\n\n".join(chunks)
        for source_path, chunks in grouped.items()
    }


def _embedded_visual_documents(documents: list[RawDocument]) -> list[RawDocument]:
    return [
        document
        for document in documents
        if document.source_type == "image_digest"
        and document.metadata.get("embedded_path")
    ]


def _embedded_visual_documents_by_key(
    documents: list[RawDocument],
    *,
    source_type: str,
) -> dict[tuple[str, str, int], RawDocument]:
    keyed_documents: dict[tuple[str, str, int], RawDocument] = {}
    for document in documents:
        if document.source_type != source_type:
            continue
        key = _embedded_key(document)
        if key is not None:
            keyed_documents[key] = document
    return keyed_documents


def _embedded_key(document: RawDocument) -> tuple[str, str, int] | None:
    embedded_path = document.metadata.get("embedded_path")
    embedded_image_index = document.metadata.get("embedded_image_index")
    if not embedded_path or embedded_image_index is None:
        return None
    return (
        document.source_path,
        str(embedded_path),
        int(embedded_image_index),
    )


def _consistency_status(*, document_text: str, visual_text: str) -> str:
    document_text_lower = document_text.lower()
    visual_text_lower = visual_text.lower()
    document_mentions_gradient = "gradient" in document_text_lower or "градиент" in document_text_lower
    visual_mentions_chart = any(
        marker in visual_text_lower
        for marker in ("график", "диаграм", "chart", "profit", "прибыл")
    )
    if document_mentions_gradient and visual_mentions_chart:
        return CONSISTENCY_STATUS_POTENTIAL_MISMATCH
    return CONSISTENCY_STATUS_REVIEW_NEEDED


def _consistency_reason(*, status: str, document_text: str, visual_text: str) -> str:
    if status == CONSISTENCY_STATUS_POTENTIAL_MISMATCH:
        return (
            "Document text mentions a gradient image, while embedded image "
            "evidence mentions a profit chart."
        )
    return (
        "Document text and embedded image evidence were combined for review, "
        "but no deterministic mismatch rule fired."
    )


def _compact_excerpt(text: str, *, max_chars: int = 1600) -> str:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars].rstrip()}..."


def _stable_document_id_from_source_path(source_path: str) -> str:
    return _stable_document_id(Path(source_path))
