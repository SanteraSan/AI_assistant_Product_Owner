"""Keep chat answers on one active file until the user names another."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.db.models import DocumentAsset
from app.services.requested_file_scope import (
    looks_like_file_inventory_question,
    resolve_requested_files,
)

FILE_SCOPED_SQL_TOOLS = frozenset({"text_to_sql", "execute_readonly_sql"})

_ALL_DOCUMENT_MARKERS = (
    "всем доступ",
    "все доступ",
    "всех доступ",
    "по всем документ",
    "all available",
)
_MIN_STEM_LENGTH = 3


@dataclass(frozen=True)
class StickyDocumentScope:
    document_ids: list[str]
    active_document_id: str | None
    narrowed: bool


def resolve_sticky_document_scope(
    *,
    message: str,
    requested_document_ids: list[str],
    attached_document_ids: list[str],
    active_document_id: str | None,
    documents: list[DocumentAsset],
) -> StickyDocumentScope:
    """Narrow a chat turn to the active file.

    An explicit file name switches the active file. A question without a name
    stays on it. Inventory and "all documents" questions are left unchanged.
    """
    requested = _clean_ids(requested_document_ids)
    attached = _clean_ids(attached_document_ids)
    active = (active_document_id or "").strip() or None
    if looks_like_file_inventory_question(message) or _asks_all_documents(message):
        return StickyDocumentScope(
            document_ids=requested,
            active_document_id=active,
            narrowed=False,
        )

    named = _documents_named_in_message(message, documents)
    if named:
        named_ids = [document.id for document in named]
        return StickyDocumentScope(
            document_ids=named_ids,
            active_document_id=named_ids[-1],
            narrowed=True,
        )

    candidate = _sticky_candidate(
        active_document_id=active,
        attached_document_ids=attached,
        documents=documents,
    )
    if candidate is None:
        return StickyDocumentScope(
            document_ids=requested,
            active_document_id=active,
            narrowed=False,
        )
    return StickyDocumentScope(
        document_ids=[candidate],
        active_document_id=candidate,
        narrowed=True,
    )


def active_file_document_ids(scope: dict[str, object] | None) -> list[str]:
    if not scope:
        return []
    raw = scope.get("document_ids")
    if not isinstance(raw, list):
        return []
    return _clean_ids([item for item in raw if isinstance(item, str)])


def sql_blocked_by_active_file(scope: dict[str, object] | None) -> bool:
    return bool(active_file_document_ids(scope))


def confine_document_ids(
    requested_ids: list[str],
    scope_ids: list[str],
    chat_document_ids: list[str] | None = None,
) -> list[str]:
    """Default to the active file. Another id is allowed only inside this chat."""
    scope = _clean_ids(scope_ids)
    chat = _clean_ids(chat_document_ids or [])
    allowed = list(dict.fromkeys([*scope, *chat]))
    if not allowed:
        return _clean_ids(requested_ids)
    requested = _clean_ids(requested_ids)
    if not requested:
        return scope or allowed[:1]
    picked = [document_id for document_id in requested if document_id in set(allowed)]
    return picked or scope or allowed[:1]


def _asks_all_documents(message: str) -> bool:
    normalized = (message or "").lower()
    return any(marker in normalized for marker in _ALL_DOCUMENT_MARKERS)


def _documents_named_in_message(
    message: str,
    documents: list[DocumentAsset],
) -> list[DocumentAsset]:
    by_extension = resolve_requested_files(message=message, documents=documents)
    hits: list[tuple[int, DocumentAsset]] = [
        (_name_position(message, document), document)
        for document in by_extension.matched_documents
    ]
    seen = {document.id for document in by_extension.matched_documents}
    normalized_message = _normalize_name(message)
    for document in documents:
        if document.id in seen:
            continue
        stem = _normalize_name(_file_stem(document))
        if len(stem) < _MIN_STEM_LENGTH:
            continue
        index = normalized_message.find(stem)
        if index < 0:
            continue
        hits.append((index, document))
        seen.add(document.id)
    hits.sort(key=lambda item: item[0])
    return [document for _index, document in hits]


def _sticky_candidate(
    *,
    active_document_id: str | None,
    attached_document_ids: list[str],
    documents: list[DocumentAsset],
) -> str | None:
    known = {document.id for document in documents}
    if active_document_id and active_document_id in known:
        return active_document_id
    for document_id in reversed(attached_document_ids):
        if document_id in known:
            return document_id
    return None


def _name_position(message: str, document: DocumentAsset) -> int:
    normalized_message = _normalize_name(message)
    stem = _normalize_name(_file_stem(document))
    if stem:
        index = normalized_message.find(stem)
        if index >= 0:
            return index
    return 0


def _file_stem(document: DocumentAsset) -> str:
    file_name = str(document.file_name or document.title or "").strip()
    if "." not in file_name:
        return file_name
    return file_name.rsplit(".", 1)[0]


def _normalize_name(value: str) -> str:
    return re.sub(r"[^\w]", "", (value or "").casefold(), flags=re.UNICODE).replace("_", "")


def _clean_ids(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        document_id = value.strip()
        if not document_id or document_id in seen:
            continue
        seen.add(document_id)
        cleaned.append(document_id)
    return cleaned
