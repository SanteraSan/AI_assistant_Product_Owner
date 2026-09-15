import asyncio

import httpx
import pytest

from app.core.errors import ErrorType, ProviderError
from app.services.llm.openai_compatible import OpenAICompatibleProvider


def _completion(
    *,
    content: str = "ok",
    model: str = "gemini-2.5-flash",
    finish_reason: str = "stop",
    usage: dict[str, int] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "cmpl-1",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def _provider(handler, *, provider_name: str = "gemini") -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(
        provider_name=provider_name,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="test-key",
        timeout_seconds=5,
        http_client=client,
    )


def _run(coro):
    return asyncio.run(coro)


def test_parses_usage_and_reported_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        assert str(request.url).endswith("/chat/completions")
        return httpx.Response(
            200,
            json=_completion(
                content="hello",
                model="gemini-2.5-flash-preview",
                usage={"prompt_tokens": 11, "completion_tokens": 7},
            ),
        )

    provider = _provider(handler)

    async def run() -> None:
        result = await provider.generate(model="gemini-2.5-flash", prompt="hi")
        assert result.response == "hello"
        assert result.provider == "gemini"
        assert result.provider_response_model_id == "gemini-2.5-flash-preview"
        assert result.prompt_tokens == 11
        assert result.completion_tokens == 7
        assert result.cost_estimated is False
        assert result.estimated_cost_usd is not None
        assert result.finish_reason == "stop"
        await provider.aclose()

    _run(run())


def test_max_tokens_finish_reason_normalizes_to_length() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(finish_reason="MAX_TOKENS"))

    provider = _provider(handler)

    async def run() -> None:
        result = await provider.generate(model="gemini-2.5-flash", prompt="hi")
        assert result.finish_reason == "length"
        await provider.aclose()

    _run(run())


def test_safety_finish_reason_stays_raw() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(finish_reason="SAFETY"))

    provider = _provider(handler)

    async def run() -> None:
        result = await provider.generate(model="gemini-2.5-flash", prompt="hi")
        assert result.finish_reason == "SAFETY"
        await provider.aclose()

    _run(run())


def test_missing_usage_marks_cost_estimated() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion())

    provider = _provider(handler)

    async def run() -> None:
        result = await provider.generate(model="gemini-2.5-flash", prompt="hi")
        assert result.cost_estimated is True
        assert result.prompt_tokens is None
        await provider.aclose()

    _run(run())


def test_model_not_found_body_maps_to_model_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="model not found: nope")

    provider = _provider(handler)

    async def run() -> None:
        with pytest.raises(ProviderError) as exc:
            await provider.generate(model="missing", prompt="hi")
        assert exc.value.error_type == ErrorType.MODEL_UNAVAILABLE
        assert exc.value.status_code == 404
        await provider.aclose()

    _run(run())


def test_retired_model_body_maps_to_model_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            text=(
                "This model models/gemini-2.5-flash is no longer available "
                "to new users. Please update your code to use models/gemini-3.6-flash"
            ),
        )

    provider = _provider(handler)

    async def run() -> None:
        with pytest.raises(ProviderError) as exc:
            await provider.generate(model="gemini-2.5-flash", prompt="hi")
        assert exc.value.error_type == ErrorType.MODEL_UNAVAILABLE
        await provider.aclose()

    _run(run())


def test_generic_404_is_provider_error_not_model_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no route to host path")

    provider = _provider(handler)

    async def run() -> None:
        with pytest.raises(ProviderError) as exc:
            await provider.generate(model="gemini-2.5-flash", prompt="hi")
        assert exc.value.error_type == ErrorType.EXTERNAL_PROVIDER_ERROR
        await provider.aclose()

    _run(run())


def test_invalid_json_is_provider_invalid_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>nope</html>")

    provider = _provider(handler)

    async def run() -> None:
        with pytest.raises(ProviderError) as exc:
            await provider.generate(model="gemini-2.5-flash", prompt="hi")
        assert exc.value.error_type == ErrorType.PROVIDER_INVALID_RESPONSE
        await provider.aclose()

    _run(run())


def test_missing_choices_is_invalid_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "gemini-2.5-flash"})

    provider = _provider(handler)

    async def run() -> None:
        with pytest.raises(ProviderError) as exc:
            await provider.generate(model="gemini-2.5-flash", prompt="hi")
        assert exc.value.error_type == ErrorType.PROVIDER_INVALID_RESPONSE
        await provider.aclose()

    _run(run())


def test_retries_once_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("app.services.llm.openai_compatible.asyncio.sleep", no_sleep)

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json=_completion(content="after-retry"))

    provider = _provider(handler)

    async def run() -> None:
        result = await provider.generate(model="gemini-2.5-flash", prompt="hi")
        assert result.response == "after-retry"
        assert calls["n"] == 2
        await provider.aclose()

    _run(run())


def test_persistent_429_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("app.services.llm.openai_compatible.asyncio.sleep", no_sleep)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="still limited")

    provider = _provider(handler)

    async def run() -> None:
        with pytest.raises(ProviderError) as exc:
            await provider.generate(model="gemini-2.5-flash", prompt="hi")
        assert exc.value.error_type == ErrorType.EXTERNAL_PROVIDER_RATE_LIMITED
        await provider.aclose()

    _run(run())
