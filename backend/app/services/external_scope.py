from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.core.errors import ErrorType, ProviderError
from app.services.llm.types import normalize_approach

SESSION_SEEN_NON_SYNTHETIC = "session_seen_non_synthetic"


@dataclass(frozen=True)
class ExternalScopeDecision:
    allow_external_generation: bool
    allow_external_fallback: bool
    persist_session_seen_non_synthetic: bool
    deny_reason: str | None = None


def is_synthetic_metadata(metadata: Mapping[str, object] | None) -> bool:
    if not metadata:
        return False
    if metadata.get("synthetic") is True:
        return True
    nested = metadata.get("document_metadata")
    if isinstance(nested, Mapping) and nested.get("synthetic") is True:
        return True
    return False


def strip_client_synthetic_flag(metadata: Mapping[str, object] | None) -> dict[str, object]:
    """Uploads must never carry synthetic=true from the client."""
    if not metadata:
        return {}
    cleaned = dict(metadata)
    cleaned.pop("synthetic", None)
    nested = cleaned.get("document_metadata")
    if isinstance(nested, Mapping):
        nested_cleaned = dict(nested)
        nested_cleaned.pop("synthetic", None)
        cleaned["document_metadata"] = nested_cleaned
    return cleaned


def sources_include_non_synthetic(sources: Sequence[object]) -> bool:
    for source in sources:
        metadata = getattr(source, "metadata", None)
        if not isinstance(metadata, Mapping):
            return True
        if not is_synthetic_metadata(metadata):
            return True
    return False


def session_seen_non_synthetic(metadata: Mapping[str, object] | None) -> bool:
    if not metadata:
        return False
    return metadata.get(SESSION_SEEN_NON_SYNTHETIC) is True


def decide_external_scope(
    *,
    approach: str | None,
    endpoint: str,
    session_seen_non_synthetic_flag: bool,
    retrieved_non_synthetic: bool,
) -> ExternalScopeDecision:
    """Default-deny cloud generation. User message is not classified here."""
    normalized = normalize_approach(approach)
    persist = retrieved_non_synthetic or session_seen_non_synthetic_flag
    blocked = persist
    deny_reason: str | None = None
    if retrieved_non_synthetic:
        deny_reason = "retrieved_non_synthetic"
    elif session_seen_non_synthetic_flag:
        deny_reason = "session_memory"

    if blocked and normalized == "external":
        raise ProviderError(
            ErrorType.EXTERNAL_SCOPE_NOT_SYNTHETIC,
            "External generation is blocked because this session already saw non-synthetic evidence. Open a new chat.",
            status_code=403,
            extra={
                "reason": deny_reason or "retrieved_non_synthetic",
                "persist_session_seen_non_synthetic": True,
            },
        )

    allow_fallback = (
        normalized == "hybrid" and endpoint == "rag" and not blocked
    )
    allow_external = normalized == "external" and not blocked
    return ExternalScopeDecision(
        allow_external_generation=allow_external,
        allow_external_fallback=allow_fallback,
        persist_session_seen_non_synthetic=persist,
        deny_reason=deny_reason,
    )
