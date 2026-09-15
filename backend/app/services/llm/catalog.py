from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ErrorType, ProviderError


@dataclass(frozen=True)
class ModelCatalogEntry:
    id: str
    provider: str
    label: str


DEFAULT_GEMINI_MODELS: tuple[str, ...] = (
    "gemini-3.6-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
)

DEFAULT_OPENROUTER_MODELS: tuple[str, ...] = ("openai/gpt-4o-mini",)

DEFAULT_LOCAL_MODELS: tuple[str, ...] = (
    "qwen3.5:9b",
    "gemma4:12b",
    "qwen3:14b",
    "qwen2.5-coder:7b",
    "qwen2.5:0.5b",
    "gemma3:12b",
    "nomic-embed-text",
)


class ModelCatalog:
    def __init__(
        self,
        *,
        local_models: tuple[str, ...] | None = None,
        gemini_models: tuple[str, ...] | None = None,
        openrouter_models: tuple[str, ...] | None = None,
        extra_local_models: tuple[str, ...] = (),
        gemini_configured: bool = False,
        openrouter_configured: bool = False,
    ) -> None:
        self._local = frozenset(local_models or DEFAULT_LOCAL_MODELS) | frozenset(extra_local_models)
        self._gemini = frozenset(gemini_models or DEFAULT_GEMINI_MODELS)
        self._openrouter = frozenset(openrouter_models or DEFAULT_OPENROUTER_MODELS)
        self._gemini_configured = gemini_configured
        self._openrouter_configured = openrouter_configured

    def resolve_provider(self, *, model: str, approach: str) -> str:
        if approach == "local_only":
            if model in self._local:
                return "ollama"
            raise ProviderError(
                ErrorType.MODEL_UNAVAILABLE,
                f"Model {model} is not available for local_only.",
                status_code=404,
            )
        if approach == "external":
            if model in self._gemini:
                if not self._gemini_configured:
                    raise ProviderError(
                        ErrorType.MODEL_UNAVAILABLE,
                        "Gemini is not configured.",
                        status_code=503,
                    )
                return "gemini"
            if model in self._openrouter:
                if not self._openrouter_configured:
                    raise ProviderError(
                        ErrorType.MODEL_UNAVAILABLE,
                        "OpenRouter is not configured.",
                        status_code=503,
                    )
                return "openrouter"
            raise ProviderError(
                ErrorType.MODEL_UNAVAILABLE,
                f"Model {model} is not available for external approach.",
                status_code=404,
            )
        if model in self._local:
            return "ollama"
        if model in self._gemini and self._gemini_configured:
            return "gemini"
        if model in self._openrouter and self._openrouter_configured:
            return "openrouter"
        if model in self._local or not model:
            return "ollama"
        raise ProviderError(
            ErrorType.MODEL_UNAVAILABLE,
            f"Model {model} is not in the catalog.",
            status_code=404,
        )

    def list_entries(self) -> list[ModelCatalogEntry]:
        entries: list[ModelCatalogEntry] = [
            ModelCatalogEntry(id=model_id, provider="ollama", label=model_id)
            for model_id in sorted(self._local)
        ]
        if self._gemini_configured:
            entries.extend(
                ModelCatalogEntry(id=model_id, provider="gemini", label=model_id)
                for model_id in sorted(self._gemini)
            )
        if self._openrouter_configured:
            entries.extend(
                ModelCatalogEntry(id=model_id, provider="openrouter", label=model_id)
                for model_id in sorted(self._openrouter)
            )
        return entries
