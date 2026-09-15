from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

_SEPARATOR_RE = re.compile(r"[\s_-]+")


def normalize_deal_code(value: str) -> str:
    """Canonical deal token: lowercase, trim, collapse spaces/underscores/hyphens."""
    collapsed = _SEPARATOR_RE.sub("-", value.strip().lower())
    return collapsed.strip("-")


@dataclass(frozen=True)
class DealIdentity:
    deal_code: str
    bucket_id: str
    title: str
    aliases: tuple[str, ...] = ()


def resolve_deal_from_message(
    message: str,
    deals: Sequence[DealIdentity],
) -> DealIdentity | None:
    """Exact/normalized match on deal_code, aliases, or fixture title. No LLM-NER."""
    haystack = normalize_deal_code(message)
    if not haystack:
        return None

    scored: list[tuple[int, DealIdentity]] = []
    for deal in deals:
        needles = [deal.deal_code, deal.title, *deal.aliases]
        best = 0
        for raw in needles:
            needle = normalize_deal_code(raw)
            if needle and needle in haystack:
                best = max(best, len(needle))
        if best:
            scored.append((best, deal))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    best_len = scored[0][0]
    unique: dict[str, DealIdentity] = {}
    for length, deal in scored:
        if length != best_len:
            continue
        unique[f"{deal.bucket_id}:{deal.deal_code}"] = deal
    if len(unique) != 1:
        return None
    return next(iter(unique.values()))
