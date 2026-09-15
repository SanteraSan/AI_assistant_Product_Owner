from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.errors import ErrorType, ProviderError
from app.core.model_pricing import estimate_cost_usd
from app.services.llm.finish_reason import normalize_finish_reason
from app.services.llm.types import GenerationResult

MODEL_NOT_FOUND_MARKERS = (
    "model not found",
    "no such model",
    "is not found",
    "does not exist",
    "unknown model",
    "no longer available",
    "not available to new users",
)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        max_tokens: int = 2048,
        extra_headers: dict[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_tokens = max_tokens
        self._extra_headers = extra_headers or {}
        self._client = http_client
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> GenerationResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self._max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p

        response = await self._post_with_retry(payload)
        return self._parse_completion(model=model, payload=response)

    async def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: ProviderError | None = None
        for attempt in range(2):
            try:
                response = await self._http_client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        **self._extra_headers,
                    },
                )
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    ErrorType.EXTERNAL_PROVIDER_UNAVAILABLE,
                    f"{self._provider_name} timed out.",
                    status_code=503,
                ) from exc
            except httpx.ConnectError as exc:
                raise ProviderError(
                    ErrorType.EXTERNAL_PROVIDER_UNAVAILABLE,
                    f"{self._provider_name} is not reachable.",
                    status_code=503,
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    ErrorType.EXTERNAL_PROVIDER_UNAVAILABLE,
                    str(exc),
                    status_code=502,
                ) from exc

            if response.status_code in {429, 503} and attempt == 0:
                await asyncio.sleep(0.25 * (2**attempt))
                last_error = self._error_from_response(response)
                continue
            if response.status_code >= 400:
                raise self._error_from_response(response)
            try:
                data = response.json()
            except ValueError as exc:
                raise ProviderError(
                    ErrorType.PROVIDER_INVALID_RESPONSE,
                    f"{self._provider_name} returned non-JSON.",
                    status_code=502,
                ) from exc
            if not isinstance(data, dict):
                raise ProviderError(
                    ErrorType.PROVIDER_INVALID_RESPONSE,
                    f"{self._provider_name} returned a non-object JSON body.",
                    status_code=502,
                )
            return data

        raise last_error or ProviderError(
            ErrorType.EXTERNAL_PROVIDER_UNAVAILABLE,
            f"{self._provider_name} failed after retry.",
            status_code=503,
        )

    def _error_from_response(self, response: httpx.Response) -> ProviderError:
        body = response.text
        lowered = body.lower()
        if response.status_code == 429:
            return ProviderError(
                ErrorType.EXTERNAL_PROVIDER_RATE_LIMITED,
                body or f"{self._provider_name} rate limited.",
                status_code=429,
            )
        if response.status_code in {400, 404} and any(
            marker in lowered for marker in MODEL_NOT_FOUND_MARKERS
        ):
            return ProviderError(
                ErrorType.MODEL_UNAVAILABLE,
                body or f"Model is unavailable on {self._provider_name}.",
                status_code=404,
            )
        if response.status_code >= 500:
            return ProviderError(
                ErrorType.EXTERNAL_PROVIDER_UNAVAILABLE,
                body or f"{self._provider_name} unavailable.",
                status_code=503,
            )
        return ProviderError(
            ErrorType.EXTERNAL_PROVIDER_ERROR,
            body or f"{self._provider_name} returned HTTP {response.status_code}.",
            status_code=response.status_code if 400 <= response.status_code < 500 else 502,
            extra={"provider_status": response.status_code},
        )

    def _parse_completion(self, *, model: str, payload: dict[str, Any]) -> GenerationResult:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError(
                ErrorType.PROVIDER_INVALID_RESPONSE,
                f"{self._provider_name} response had no choices.",
                status_code=502,
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise ProviderError(
                ErrorType.PROVIDER_INVALID_RESPONSE,
                f"{self._provider_name} choice was not an object.",
                status_code=502,
            )
        message = first.get("message")
        content = ""
        if isinstance(message, dict):
            raw_content = message.get("content")
            content = raw_content if isinstance(raw_content, str) else ""
        finish_reason = normalize_finish_reason(
            str(first.get("finish_reason") or "") or None
        )
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        prompt_tokens = _optional_int(usage.get("prompt_tokens") if isinstance(usage, dict) else None)
        completion_tokens = _optional_int(
            usage.get("completion_tokens") if isinstance(usage, dict) else None
        )
        cost_estimated = prompt_tokens is None and completion_tokens is None
        reported_model = payload.get("model")
        reported = str(reported_model) if isinstance(reported_model, str) and reported_model else None
        return GenerationResult(
            response=content,
            model=model,
            provider=self._provider_name,
            provider_response_model_id=reported,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_estimated=cost_estimated,
            finish_reason=finish_reason,
            estimated_cost_usd=estimate_cost_usd(
                provider=self._provider_name,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ),
        )

    @property
    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True
        return self._client


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
