from __future__ import annotations

import re

from app.clients.qdrant_store import QdrantStore
from app.models.chat import SourceChunk


def supplement_docx_sources(
    *,
    qdrant_store: QdrantStore,
    scroll_limit: int,
    sources: list[SourceChunk],
    message: str,
    selected_tenant_id: str | None,
    selected_bucket_ids: list[str],
    selected_source_types: list[str],
    selected_document_ids: list[str],
    selected_source_paths: list[str],
    selected_allowed_source_paths: list[str],
    limit: int,
) -> list[SourceChunk]:
    if selected_source_types and "docx" not in selected_source_types:
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
        source_types=["docx"],
        document_ids=selected_document_ids,
        source_paths=selected_source_paths,
        allowed_source_paths=selected_allowed_source_paths,
    )
    if not candidates:
        return []

    exact_terms = _extract_docx_exact_terms(message)
    exact_matches = [
        source
        for source in candidates
        if exact_terms and _docx_exact_match_count(source, exact_terms) > 0
    ]
    exact_matches = sorted(
        exact_matches,
        key=lambda source: (
            -_docx_exact_match_count(source, exact_terms),
            _docx_sort_key(source),
        ),
    )

    from app.services.rag_service import _merge_sources

    neighbor_matches = _docx_neighbor_sources(
        seed_sources=_merge_sources(sources, exact_matches[:limit]),
        candidates=candidates,
        radius=2,
    )
    return _merge_sources(exact_matches[:limit], neighbor_matches[:limit])


def _extract_docx_exact_terms(text: str) -> list[str]:
    raw_terms = re.findall(r"[A-Za-zА-Яа-я_#][A-Za-zА-Яа-я0-9_#.-]{2,}|\b\d{2,}\b", text)
    skipped_terms = {"docx", "document", "документ"}
    terms: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        normalized = term.strip(".,:;()[]{}").lower()
        if not normalized or normalized in skipped_terms:
            continue
        has_latin_or_number = re.search(r"[a-z0-9#]", normalized) is not None
        if not has_latin_or_number:
            continue
        if normalized in seen:
            continue
        terms.append(normalized)
        seen.add(normalized)
    return terms


def _docx_exact_match_count(source: SourceChunk, terms: list[str]) -> int:
    body = _docx_searchable_body(source).lower()
    return sum(1 for term in terms if term in body)


def _docx_searchable_body(source: SourceChunk) -> str:
    skipped_prefixes = ("file:",)
    return "\n".join(
        line
        for line in source.content.splitlines()
        if not line.strip().lower().startswith(skipped_prefixes)
    )


def _docx_neighbor_sources(
    *,
    seed_sources: list[SourceChunk],
    candidates: list[SourceChunk],
    radius: int,
) -> list[SourceChunk]:
    seed_indexes = [
        index
        for source in seed_sources
        if (index := _docx_paragraph_index(source)) is not None
    ]
    if not seed_indexes:
        return []

    neighbors = [
        candidate
        for candidate in candidates
        if _docx_is_neighbor(candidate, seed_indexes=seed_indexes, radius=radius)
    ]
    return sorted(neighbors, key=_docx_sort_key)


def _docx_is_neighbor(
    source: SourceChunk,
    *,
    seed_indexes: list[int],
    radius: int,
) -> bool:
    paragraph_index = _docx_paragraph_index(source)
    if paragraph_index is not None:
        return any(abs(paragraph_index - seed_index) <= radius for seed_index in seed_indexes)

    document_metadata = source.metadata.get("document_metadata") or {}
    try:
        start_index = int(document_metadata.get("paragraph_start_index"))
        end_index = int(document_metadata.get("paragraph_end_index"))
    except (TypeError, ValueError):
        return False
    return any(start_index - radius <= seed_index <= end_index + radius for seed_index in seed_indexes)


def _docx_paragraph_index(source: SourceChunk) -> int | None:
    document_metadata = source.metadata.get("document_metadata") or {}
    try:
        return int(document_metadata.get("paragraph_index"))
    except (TypeError, ValueError):
        return None


def _docx_sort_key(source: SourceChunk) -> tuple[str, int, int, str]:
    document_metadata = source.metadata.get("document_metadata") or {}
    source_path = source.source_path or ""
    block_type = str(document_metadata.get("block_type") or "")
    paragraph_index = _docx_paragraph_index(source)
    if paragraph_index is None:
        try:
            paragraph_index = int(document_metadata.get("paragraph_start_index") or 0)
        except (TypeError, ValueError):
            paragraph_index = 0
    block_priority = 0 if block_type == "paragraph" else 1
    return source_path, paragraph_index, block_priority, source.id


def _rerank_docx_sources(sources: list[SourceChunk], message: str) -> list[SourceChunk]:
    if not any(source.source_type == "docx" for source in sources):
        return sources

    exact_terms = _extract_docx_exact_terms(message)
    ranked = [
        (index, source, _docx_rerank_score(source, exact_terms))
        for index, source in enumerate(sources)
    ]
    ranked = sorted(ranked, key=lambda item: (-item[2], item[0]))
    return [source for _, source, _ in ranked]


def _docx_rerank_score(source: SourceChunk, exact_terms: list[str]) -> float:
    if source.source_type != "docx":
        return source.score or 0.0

    document_metadata = source.metadata.get("document_metadata") or {}
    block_type = document_metadata.get("block_type")
    base_score = source.score if source.score is not None else 0.75
    exact_boost = min(0.2, _docx_exact_match_count(source, exact_terms) * 0.05)
    block_boost = 0.03 if block_type == "paragraph_window" else 0.0
    return base_score + exact_boost + block_boost

