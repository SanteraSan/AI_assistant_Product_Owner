"""HeadHunter-style resume sections for indexing and employer retrieval.

This is a template split, not a general document segmenter. A resume is cut on
employment date headers and on the fixed headings «Навыки» and «Обо мне».
Other PDFs stay page-sized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeVar

_MONTH = (
    r"(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]|июн\w*|июл\w*|"
    r"август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)"
)
_DATE_HEADER = re.compile(
    rf"{_MONTH}\s+20\d{{2}}\s*[—–\-]\s*(?:\n\s*)?{_MONTH}\s+20\d{{2}}",
    re.IGNORECASE,
)
_HEADING = re.compile(
    r"(?im)^(?P<heading>Образование|Навыки|Опыт вождения|Дополнительная информация)\s*$"
    r"|^(?P<about>Обо мне)\b"
)
_MONTH_LINE = re.compile(rf"^{_MONTH}\s+20\d{{2}}\s*[—–\-]?$", re.IGNORECASE)
_DURATION = re.compile(
    r"^\d+\s+(?:год|года|лет|месяц|месяца|месяцев)\b",
    re.IGNORECASE,
)
_LEGAL_FORM = re.compile(r"^(?:ооо|оао|зао|пао|ао|ип)\s+")
_RESUME_SECTION_EXCERPT_LIMIT = 8000
_RESUME_EMBED_MAX_CHARS = 2200

_T = TypeVar("_T")


@dataclass(frozen=True)
class ResumeSection:
    kind: str
    title: str
    content: str
    organization: str
    page_number: int


def split_hh_resume(pages: list[str]) -> list[ResumeSection] | None:
    """Return resume sections when the text has at least two job date ranges."""
    cleaned_pages = [_normalize_spaces(page).strip() for page in pages]
    if sum(1 for _ in _DATE_HEADER.finditer("\n".join(cleaned_pages))) < 2:
        return None

    offsets: list[int] = []
    cursor = 0
    pieces: list[str] = []
    for page in cleaned_pages:
        offsets.append(cursor)
        pieces.append(page)
        cursor += len(page) + 1
    full_text = "\n".join(pieces)
    markers = _markers(full_text)
    if sum(1 for kind, _start in markers if kind == "employment") < 2:
        return None

    sections: list[ResumeSection] = []
    bounds = [0, *[start for _kind, start in markers], len(full_text)]
    labels = ["profile", *[kind for kind, _start in markers]]
    for kind, start, end in zip(labels, bounds[:-1], bounds[1:], strict=True):
        content = full_text[start:end].strip()
        if not content:
            continue
        organization = _organization(content) if kind == "employment" else ""
        title = organization or _title_for_kind(kind)
        sections.append(
            ResumeSection(
                kind=kind,
                title=title,
                content=content,
                organization=organization,
                page_number=_page_number(offsets, start),
            )
        )
    return sections or None


def prefer_named_resume_employer(query: str, sources: list[_T]) -> list[_T]:
    """Keep only the job block whose organization is named in the query."""
    named = _normalized_query(query)
    if not named:
        return sources
    matched = [
        source
        for source in sources
        if _section_kind(source) == "employment" and _organization_in_query(_section_organization(source), named)
    ]
    if not matched:
        return sources
    return matched


def resume_embedding_parts(
    content: str,
    *,
    section_kind: str,
    organization: str,
    max_chars: int = _RESUME_EMBED_MAX_CHARS,
) -> list[str]:
    """Split a resume block so nomic-embed-text can embed it.

    nomic-embed-text is loaded with a 2048-token context. A job of about
    5600 characters returns HTTP 500. Shorter jobs stay whole. A long job
    keeps the technology lines on every piece.
    """
    normalized = content.strip()
    if len(normalized) <= max_chars:
        return [normalized] if normalized else []
    anchor = _technology_anchor(normalized, organization) if section_kind == "employment" else ""
    if len(anchor) >= max_chars:
        anchor = ""
    body_limit = max_chars - len(anchor) - 1 if anchor else max_chars
    parts = _split_for_embed(normalized, max_chars=body_limit)
    if not anchor:
        return parts
    headed = [part if anchor in part else f"{anchor}\n{part}" for part in parts]
    return [part[:max_chars] for part in headed if part.strip()]


def resume_excerpt(content: str, *, section_kind: str, limit: int) -> str:
    if section_kind in {"employment", "skills", "about", "education", "profile", "other"}:
        return content[:_RESUME_SECTION_EXCERPT_LIMIT]
    return content[:limit]


def _markers(full_text: str) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for match in _DATE_HEADER.finditer(full_text):
        found.append(("employment", match.start()))
    for match in _HEADING.finditer(full_text):
        if match.group("about"):
            found.append(("about", match.start()))
            continue
        heading = match.group("heading").lower()
        if heading == "образование":
            kind = "education"
        elif heading == "навыки":
            kind = "skills"
        else:
            kind = "other"
        found.append((kind, match.start()))
    found.sort(key=lambda item: item[1])
    return found


def _technology_anchor(content: str, organization: str) -> str:
    lines = content.splitlines()
    picked: list[str] = []
    if organization.strip():
        picked.append(f"Организация: {organization.strip()}")
    for index, line in enumerate(lines):
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("основные технологии") or lowered.startswith("технологии"):
            picked.append(stripped)
            if index + 1 < len(lines) and lines[index + 1].strip():
                picked.append(lines[index + 1].strip())
            break
    return "\n".join(picked)


def _split_for_embed(text: str, *, max_chars: int) -> list[str]:
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk = text[start:end].strip()
        if chunk:
            parts.append(chunk)
        if end == len(text):
            break
        start = end
    return parts


def _organization(block: str) -> str:
    passed_header = False
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not passed_header:
            passed_header = True
            continue
        if _DATE_HEADER.search(line) or _MONTH_LINE.match(line) or _DURATION.match(line):
            continue
        if re.fullmatch(r"[—–\-]+", line):
            continue
        return line
    return ""


def _title_for_kind(kind: str) -> str:
    return {
        "profile": "Шапка резюме",
        "education": "Образование",
        "skills": "Навыки",
        "about": "Обо мне",
        "other": "Дополнительно",
    }.get(kind, kind)


def _page_number(offsets: list[int], start: int) -> int:
    page_number = 1
    for index, offset in enumerate(offsets, start=1):
        if offset <= start:
            page_number = index
    return page_number


def _normalize_spaces(text: str) -> str:
    return (text or "").replace("\u00a0", " ").replace("\u202f", " ")


def _normalized_query(query: str) -> str:
    return _fold(query)


def _organization_in_query(organization: str, query: str) -> bool:
    alias = _LEGAL_FORM.sub("", _fold(organization)).strip()
    alias = alias.split(" - ")[0].strip()
    return len(alias) >= 4 and alias in query


def _fold(text: str) -> str:
    folded = (text or "").lower().replace("ё", "е")
    folded = folded.replace("«", " ").replace("»", " ").replace('"', " ")
    folded = re.sub(r"\s+", " ", folded)
    return folded.strip()


def _section_metadata(source: object) -> dict[str, object]:
    metadata = getattr(source, "metadata", None)
    if not isinstance(metadata, dict):
        return {}
    nested = metadata.get("document_metadata")
    if isinstance(nested, dict):
        return nested
    return metadata


def _section_kind(source: object) -> str:
    return str(_section_metadata(source).get("resume_section") or "")


def _section_organization(source: object) -> str:
    return str(_section_metadata(source).get("organization") or "")
