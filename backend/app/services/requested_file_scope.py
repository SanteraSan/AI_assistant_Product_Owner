from __future__ import annotations

import re
from dataclasses import dataclass

from app.db.models import DocumentAsset


_FILE_EXTENSIONS = "jpg|jpeg|png|gif|webp|bmp|pdf|docx|doc|xlsx|xls|txt|md|csv"
_REQUESTED_FILE_NAME_PATTERNS = (
    re.compile(rf'(?iu)"([^\n"]+\.(?:{_FILE_EXTENSIONS}))"'),
    re.compile(
        rf"(?iu)(?:файл(?:е|а|у|ом)?|документе?|картинк[аеуи]|изображени[еяю]|image)\s+"
        rf"((?:[\w.-]+(?:\s+[\w.-]+){{0,5}})\.(?:{_FILE_EXTENSIONS}))\b"
    ),
    re.compile(rf"(?iu)\b((?:\d+[\w.-]*(?:\s+[\w.-]+){{0,5}})\.(?:{_FILE_EXTENSIONS}))\b"),
    re.compile(rf"(?iu)\b([A-Za-z0-9_.-]+\.(?:{_FILE_EXTENSIONS}))\b"),
)


@dataclass(frozen=True)
class RequestedFileResolution:
    requested_names: list[str]
    matched_documents: list[DocumentAsset]
    missing_names: list[str]


def extract_requested_file_names(message: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    text = message or ""
    for pattern in _REQUESTED_FILE_NAME_PATTERNS:
        for match in pattern.findall(text):
            normalized = " ".join(str(match).split())
            key = normalized.casefold()
            if not normalized or key in seen:
                continue
            seen.add(key)
            found.append(normalized)
    return found


def resolve_requested_files(
    *,
    message: str,
    documents: list[DocumentAsset],
) -> RequestedFileResolution:
    requested_names = extract_requested_file_names(message)
    if not requested_names:
        return RequestedFileResolution(
            requested_names=[],
            matched_documents=[],
            missing_names=[],
        )

    available = [(document, _document_file_name(document).casefold()) for document in documents]
    matched: list[DocumentAsset] = []
    matched_ids: set[str] = set()
    missing: list[str] = []

    for requested in requested_names:
        requested_key = requested.casefold()
        hit = _best_document_match(requested_key, available)
        if hit is None:
            missing.append(requested)
            continue
        if hit.id in matched_ids:
            continue
        matched_ids.add(hit.id)
        matched.append(hit)

    return RequestedFileResolution(
        requested_names=requested_names,
        matched_documents=matched,
        missing_names=missing,
    )


def find_accessible_document_by_name(
    *,
    file_name: str,
    documents: list[DocumentAsset],
) -> DocumentAsset | None:
    """Match a user-facing file name against already ACL-filtered documents."""
    requested = " ".join(file_name.split()).strip()
    if not requested:
        return None
    available = [(document, _document_file_name(document).casefold()) for document in documents]
    return _best_document_match(requested.casefold(), available)


def missing_requested_file_answer(missing_files: list[str]) -> str:
    if len(missing_files) == 1:
        return (
            f"Файла `{missing_files[0]}` нет в доступных вам документах, "
            "поэтому описать его содержимое нельзя."
        )
    joined = ", ".join(f"`{name}`" for name in missing_files)
    return (
        f"Файлов {joined} нет в доступных вам документах, "
        "поэтому описать их содержимое нельзя."
    )


def looks_like_file_inventory_question(message: str) -> bool:
    normalized = message.lower()
    markers = (
        "какие файл",
        "какой файл",
        "список файл",
        "что за файл",
        "доступные файл",
        "какие документ",
        "доступные документ",
        "что доступно",
    )
    return any(marker in normalized for marker in markers)


def _document_file_name(document: DocumentAsset) -> str:
    return str(document.file_name or document.title or "").strip()


def _best_document_match(
    requested_key: str,
    available: list[tuple[DocumentAsset, str]],
) -> DocumentAsset | None:
    exact = [document for document, name in available if name == requested_key]
    if exact:
        return exact[0]

    # Allow partial matches for spaced names / OCR quirks, but only with a real extension.
    if "." not in requested_key:
        return None
    suffix_hits = [
        document
        for document, name in available
        if name.endswith(requested_key) or requested_key.endswith(name)
    ]
    if len(suffix_hits) == 1:
        return suffix_hits[0]
    return None
