from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ErrorType, ProviderError
from app.core.model_pricing import estimate_cost_usd
from app.services.llm.catalog import ModelCatalog
from app.services.llm.openai_compatible import MODEL_NOT_FOUND_MARKERS, OpenAICompatibleProvider
from app.services.llm.types import GenerationResult, normalize_approach
from app.services.ollama_client import OllamaClient
from app.services.ollama_load_guard import OllamaOverloadedError

_INFRA_HTTP_STATUSES = {429, 500, 502, 503, 504}


class ModelGateway:
    def __init__(
        self,
        *,
        ollama_client: OllamaClient,
        catalog: ModelCatalog,
        gemini: OpenAICompatibleProvider | None = None,
        openrouter: OpenAICompatibleProvider | None = None,
        gemini_default_model: str = "gemini-3.6-flash",
        openrouter_default_model: str = "openai/gpt-4o-mini",
    ) -> None:
        self._ollama = ollama_client
        self._catalog = catalog
        self._gemini = gemini
        self._openrouter = openrouter
        self._gemini_default_model = gemini_default_model
        self._openrouter_default_model = openrouter_default_model

    async def aclose(self) -> None:
        if self._gemini is not None:
            await self._gemini.aclose()
        if self._openrouter is not None:
            await self._openrouter.aclose()

    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        approach: str | None,
        endpoint: str,
        allow_external_fallback: bool = False,
        keep_alive: str | int | None = None,
        options: dict[str, Any] | None = None,
        think: bool | None = False,
    ) -> GenerationResult:
        normalized = normalize_approach(approach)
        if endpoint == "agent" and normalized == "external":
            raise ProviderError(
                ErrorType.EXTERNAL_AGENT_NOT_SUPPORTED,
                "External providers are not supported for /agent/chat in this slice.",
                status_code=400,
            )

        if normalized == "external":
            provider_name = self._catalog.resolve_provider(model=model, approach="external")
            return await self._external_generate(
                provider_name=provider_name,
                model=model,
                prompt=prompt,
                options=options,
            )

        if endpoint == "chat" or not allow_external_fallback or normalized == "local_only":
            return await self._ollama_generate(
                model=model,
                prompt=prompt,
                keep_alive=keep_alive,
                options=options,
                think=think,
            )

        try:
            return await self._ollama_generate(
                model=model,
                prompt=prompt,
                keep_alive=keep_alive,
                options=options,
                think=think,
            )
        except (OllamaOverloadedError, httpx.ConnectError, httpx.TimeoutException) as exc:
            return await self._fallback_or_raise(exc, requested_model=model, prompt=prompt, options=options)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _INFRA_HTTP_STATUSES:
                raise
            return await self._fallback_or_raise(exc, requested_model=model, prompt=prompt, options=options)

    async def _fallback_or_raise(
        self,
        exc: BaseException,
        *,
        requested_model: str,
        prompt: str,
        options: dict[str, Any] | None,
    ) -> GenerationResult:
        fallback = self._fallback_provider()
        if fallback is None:
            raise exc
        result = await fallback.generate(
            model=self._fallback_model(),
            prompt=prompt,
            temperature=_option_float(options, "temperature"),
            top_p=_option_float(options, "top_p"),
        )
        return replace(
            result,
            model=requested_model,
            fallback_from="ollama",
            fallback_to=result.provider,
        )

    async def _ollama_generate(
        self,
        *,
        model: str,
        prompt: str,
        keep_alive: str | int | None,
        options: dict[str, Any] | None,
        think: bool | None,
    ) -> GenerationResult:
        self._catalog.resolve_provider(model=model, approach="local_only")
        try:
            raw = await self._ollama.generate(
                model,
                prompt,
                keep_alive=keep_alive,
                options=options,
                think=think,
            )
        except httpx.HTTPStatusError as exc:
            body = (exc.response.text or "").lower()
            if exc.response.status_code in {400, 404} and any(
                marker in body for marker in MODEL_NOT_FOUND_MARKERS
            ):
                raise ProviderError(
                    ErrorType.MODEL_UNAVAILABLE,
                    exc.response.text or f"Model {model} is unavailable on Ollama.",
                    status_code=404,
                ) from exc
            raise
        response_text = str(raw.get("response") or "")
        prompt_tokens = _estimate_tokens(prompt)
        completion_tokens = _estimate_tokens(response_text)
        return GenerationResult(
            response=response_text,
            model=model,
            provider="ollama",
            provider_response_model_id=str(raw.get("model") or model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_estimated=True,
            finish_reason="stop",
            estimated_cost_usd=estimate_cost_usd(
                provider="ollama",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ),
        )

    async def _external_generate(
        self,
        *,
        provider_name: str,
        model: str,
        prompt: str,
        options: dict[str, Any] | None,
    ) -> GenerationResult:
        provider = self._gemini if provider_name == "gemini" else self._openrouter
        if provider is None:
            raise ProviderError(
                ErrorType.MODEL_UNAVAILABLE,
                f"{provider_name} is not configured.",
                status_code=503,
            )
        return await provider.generate(
            model=model,
            prompt=prompt,
            temperature=_option_float(options, "temperature"),
            top_p=_option_float(options, "top_p"),
        )

    def _fallback_provider(self) -> OpenAICompatibleProvider | None:
        if self._gemini is not None:
            return self._gemini
        return self._openrouter

    def _fallback_model(self) -> str:
        if self._gemini is not None:
            return self._gemini_default_model
        return self._openrouter_default_model

    def health_snapshot(self) -> dict[str, object]:
        return {
            "gemini_key_configured": self._gemini is not None,
            "openrouter_key_configured": self._openrouter is not None,
            "models": [
                {"id": entry.id, "provider": entry.provider, "label": entry.label}
                for entry in self._catalog.list_entries()
            ],
        }


def build_model_gateway(*, settings: Settings, ollama_client: OllamaClient) -> ModelGateway:
    extra_local = tuple(
        model
        for model in (
            settings.default_model,
            settings.default_rag_model,
            settings.embedding_model,
            settings.image_vision_model,
            settings.conversation_summary_model,
            settings.text_to_sql_model,
            settings.text_to_sql_fallback_model,
            settings.agent_default_model,
        )
        if model
    )
    gemini_key = settings.gemini_api_key.strip()
    openrouter_key = settings.openrouter_api_key.strip()
    catalog = ModelCatalog(
        extra_local_models=extra_local,
        gemini_configured=bool(gemini_key),
        openrouter_configured=bool(openrouter_key),
    )
    gemini = (
        OpenAICompatibleProvider(
            provider_name="gemini",
            base_url=settings.gemini_base_url,
            api_key=gemini_key,
            timeout_seconds=settings.external_request_timeout_seconds,
        )
        if gemini_key
        else None
    )
    openrouter = (
        OpenAICompatibleProvider(
            provider_name="openrouter",
            base_url=settings.openrouter_base_url,
            api_key=openrouter_key,
            timeout_seconds=settings.external_request_timeout_seconds,
            extra_headers={
                "HTTP-Referer": settings.openrouter_http_referer,
                "X-Title": settings.openrouter_app_title,
            },
        )
        if openrouter_key
        else None
    )
    return ModelGateway(
        ollama_client=ollama_client,
        catalog=catalog,
        gemini=gemini,
        openrouter=openrouter,
        gemini_default_model=settings.gemini_default_model,
        openrouter_default_model=settings.openrouter_default_model,
    )


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _option_float(options: dict[str, Any] | None, key: str) -> float | None:
    if not options:
        return None
    value = options.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
