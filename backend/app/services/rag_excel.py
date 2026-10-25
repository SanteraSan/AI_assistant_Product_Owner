from __future__ import annotations

import re

from app.clients.qdrant_store import QdrantStore
from app.models.chat import SourceChunk


def supplement_excel_sources(
    *,
    qdrant_store: QdrantStore,
    scroll_limit: int,
    message: str,
    selected_tenant_id: str | None,
    selected_bucket_ids: list[str],
    selected_source_types: list[str],
    selected_document_ids: list[str],
    selected_source_paths: list[str],
    selected_allowed_source_paths: list[str],
    limit: int,
) -> list[SourceChunk]:
    if selected_source_types and "excel_row" not in selected_source_types:
        return []
    if (
        not selected_bucket_ids
        and not selected_document_ids
        and not selected_source_paths
        and not selected_allowed_source_paths
    ):
        return []

    candidates = qdrant_store.scroll(
        limit=scroll_limit,
        tenant_id=selected_tenant_id,
        bucket_ids=selected_bucket_ids,
        source_types=["excel_row"],
        document_ids=selected_document_ids,
        source_paths=selected_source_paths,
        allowed_source_paths=selected_allowed_source_paths,
    )
    if not candidates:
        return []

    exact_terms = _extract_excel_exact_terms(message)
    exact_matches = [
        source
        for source in candidates
        if exact_terms and _excel_exact_match_count(source, exact_terms) > 0
    ]
    exact_matches = sorted(
        exact_matches,
        key=lambda source: (
            -_excel_exact_match_count(source, exact_terms),
            _excel_row_number(source),
        ),
    )

    header_matches: list[SourceChunk] = []
    if _looks_like_document_header_question(message):
        header_matches = [
            source
            for source in candidates
            if _excel_row_number(source) <= 12
        ]
        header_matches = sorted(header_matches, key=_excel_row_number)

    from app.services.rag_service import _merge_sources

    return _merge_sources(exact_matches[:limit], header_matches[:limit])


def supplement_excel_visual_sources(
    *,
    qdrant_store: QdrantStore,
    scroll_limit: int,
    message: str,
    selected_tenant_id: str | None,
    selected_bucket_ids: list[str],
    selected_source_types: list[str],
    selected_document_ids: list[str],
    selected_source_paths: list[str],
    selected_allowed_source_paths: list[str],
    limit: int,
) -> list[SourceChunk]:
    if selected_source_types and "image_digest" not in selected_source_types:
        return []
    if (
        not selected_bucket_ids
        and not selected_document_ids
        and not selected_source_paths
        and not selected_allowed_source_paths
    ):
        return []

    candidates = qdrant_store.scroll(
        limit=scroll_limit,
        tenant_id=selected_tenant_id,
        bucket_ids=selected_bucket_ids,
        source_types=["image_digest"],
        document_ids=selected_document_ids,
        source_paths=selected_source_paths,
        allowed_source_paths=selected_allowed_source_paths,
    )
    if not candidates:
        return []

    exact_terms = _extract_excel_exact_terms(message)
    exact_matches = [
        source
        for source in candidates
        if _is_xlsx_anchor_image_source(source)
        and exact_terms
        and _excel_exact_match_count(source, exact_terms) > 0
    ]
    exact_matches = sorted(
        exact_matches,
        key=lambda source: (
            -_excel_exact_match_count(source, exact_terms),
            _excel_anchor_row_number(source),
            _excel_embedded_image_index(source),
        ),
    )
    return exact_matches[:limit]


def _extract_exact_numeric_terms(text: str) -> list[str]:
    return re.findall(r"\b\d{6,}\b", text)


def _extract_excel_exact_terms(text: str) -> list[str]:
    raw_terms = re.findall(
        r"[A-Za-zА-Яа-яЁё_#][A-Za-zА-Яа-яЁё0-9_#.-]{2,}|\b\d+(?:[,.]\d+)?\b",
        text,
    )
    skipped_terms = {
        "xls",
        "xlsx",
        "excel",
        "hard_for_analis",
        "известно",
        "город",
        "срок",
        "годности",
        "объем",
        "объём",
        "цену",
        "цена",
        "кегу",
        "какой",
        "какая",
        "какие",
        "какую",
        "что",
        "про",
        "написано",
        "изображено",
        "картинке",
        "картинка",
        "продукта",
        "продукт",
        "указано",
        "алкоголь",
        "плотность",
    }
    terms: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        normalized = term.strip(".,:;()[]{}").lower()
        if not normalized or normalized in skipped_terms:
            continue
        is_numeric = _is_excel_numeric_term(normalized)
        if is_numeric and len(re.sub(r"\D", "", normalized)) < 2:
            continue
        if not is_numeric and len(normalized) < 4:
            continue
        if normalized in seen:
            continue
        terms.append(normalized)
        seen.add(normalized)
    return terms


def _is_excel_numeric_term(term: str) -> bool:
    return re.fullmatch(r"\d+(?:[,.]\d+)?", term) is not None


def _excel_exact_match_count(source: SourceChunk, terms: list[str]) -> int:
    body = source.content.lower()
    return sum(1 for term in terms if _excel_term_in_body(term, body))


def _excel_term_in_body(term: str, body: str) -> bool:
    if term in body:
        return True
    if "," in term:
        return term.replace(",", ".") in body
    if "." in term:
        return term.replace(".", ",") in body
    return False


def _looks_like_document_header_question(text: str) -> bool:
    normalized = text.lower()
    markers = (
        "организац",
        "дата",
        "документ",
        "реквизит",
        "компан",
        "company",
        "document",
    )
    return any(marker in normalized for marker in markers)


def _excel_row_number(source: SourceChunk) -> int:
    document_metadata = source.metadata.get("document_metadata") or {}
    try:
        return int(document_metadata.get("excel_row_number") or 0)
    except (TypeError, ValueError):
        return 0


def _is_xlsx_anchor_image_source(source: SourceChunk) -> bool:
    document_metadata = source.metadata.get("document_metadata") or {}
    return (
        source.source_type == "image_digest"
        and document_metadata.get("parent_source_type") == "xlsx"
        and document_metadata.get("anchor_type") == "xlsx_cell"
    )


def _excel_anchor_row_number(source: SourceChunk) -> int:
    document_metadata = source.metadata.get("document_metadata") or {}
    try:
        return int(document_metadata.get("anchor_row") or 0)
    except (TypeError, ValueError):
        return 0


def _excel_embedded_image_index(source: SourceChunk) -> int:
    document_metadata = source.metadata.get("document_metadata") or {}
    try:
        return int(document_metadata.get("embedded_image_index") or 0)
    except (TypeError, ValueError):
        return 0

