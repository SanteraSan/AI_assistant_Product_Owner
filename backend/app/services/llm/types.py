from __future__ import annotations

from dataclasses import dataclass


def normalize_approach(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in {"", "hybrid"}:
        return "hybrid"
    if value == "openapi":
        return "external"
    if value in {"external", "local_only"}:
        return value
    return "hybrid"


@dataclass(frozen=True)
class GenerationResult:
    response: str
    model: str
    provider: str
    provider_response_model_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_estimated: bool = False
    finish_reason: str | None = None
    fallback_from: str | None = None
    fallback_to: str | None = None
    estimated_cost_usd: float | None = None

    def as_ollama_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"response": self.response, "model": self.model}
        if self.finish_reason is not None:
            payload["finish_reason"] = self.finish_reason
        return payload
