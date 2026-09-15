import asyncio

import httpx
import pytest

from app.core.errors import ErrorType, ProviderError
from app.services.llm.catalog import ModelCatalog
from app.services.llm.gateway import ModelGateway
from app.services.llm.openai_compatible import OpenAICompatibleProvider
from app.services.ollama_load_guard import OllamaOverloadedError


def _completion(content: str = "cloud") -> dict[str, object]:
    return {
        "id": "cmpl-1",
        "model": "gemini-2.5-flash",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }


class _OkOllama:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, model: str, prompt: str, **kwargs):
        del prompt, kwargs
        self.calls += 1
        return {"response": f"local:{model}", "model": model}


class _OverloadOllama:
    async def generate(self, model: str, prompt: str, **kwargs):
        del prompt, kwargs
        raise OllamaOverloadedError(model=model, operation="generate", timeout_seconds=1)


class _ConnectFailOllama:
    async def generate(self, model: str, prompt: str, **kwargs):
        del model, prompt, kwargs
        raise httpx.ConnectError("offline")


def _gemini(handler) -> tuple[OpenAICompatibleProvider, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    provider = OpenAICompatibleProvider(
        provider_name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="test-key",
        timeout_seconds=5,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(wrapped)),
    )
    return provider, requests


def _catalog() -> ModelCatalog:
    return ModelCatalog(gemini_configured=True, extra_local_models=("qwen3.5:9b",))


def _run(coro):
    return asyncio.run(coro)


def test_hybrid_chat_overload_does_not_call_gemini() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("gemini must not be called for /chat hybrid")

    gemini, requests = _gemini(handler)
    gateway = ModelGateway(ollama_client=_OverloadOllama(), catalog=_catalog(), gemini=gemini)

    async def run() -> None:
        with pytest.raises(OllamaOverloadedError):
            await gateway.generate(
                model="qwen3.5:9b",
                prompt="hi",
                approach="hybrid",
                endpoint="chat",
                allow_external_fallback=True,
            )
        assert requests == []
        await gateway.aclose()

    _run(run())


def test_hybrid_rag_fallback_only_when_allowed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("fallback"))

    gemini, requests = _gemini(handler)
    gateway = ModelGateway(ollama_client=_OverloadOllama(), catalog=_catalog(), gemini=gemini)

    async def run() -> None:
        with pytest.raises(OllamaOverloadedError):
            await gateway.generate(
                model="qwen3.5:9b",
                prompt="hi",
                approach="hybrid",
                endpoint="rag",
                allow_external_fallback=False,
            )
        assert requests == []

        result = await gateway.generate(
            model="qwen3.5:9b",
            prompt="hi",
            approach="hybrid",
            endpoint="rag",
            allow_external_fallback=True,
        )
        assert result.response == "fallback"
        assert result.fallback_from == "ollama"
        assert result.fallback_to == "gemini"
        assert result.provider == "gemini"
        assert result.model == "qwen3.5:9b"
        assert len(requests) == 1
        await gateway.aclose()

    _run(run())


def test_agent_external_errors_without_http() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("gemini must not be called for agent external")

    gemini, requests = _gemini(handler)
    gateway = ModelGateway(ollama_client=_OkOllama(), catalog=_catalog(), gemini=gemini)

    async def run() -> None:
        with pytest.raises(ProviderError) as exc:
            await gateway.generate(
                model="gemini-2.5-flash",
                prompt="hi",
                approach="external",
                endpoint="agent",
            )
        assert exc.value.error_type == ErrorType.EXTERNAL_AGENT_NOT_SUPPORTED
        assert requests == []
        await gateway.aclose()

    _run(run())


def test_openapi_alias_uses_external_provider() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("via-alias"))

    gemini, requests = _gemini(handler)
    gateway = ModelGateway(ollama_client=_OkOllama(), catalog=_catalog(), gemini=gemini)

    async def run() -> None:
        result = await gateway.generate(
            model="gemini-2.5-flash",
            prompt="hi",
            approach="openapi",
            endpoint="chat",
        )
        assert result.response == "via-alias"
        assert result.provider == "gemini"
        assert len(requests) == 1
        await gateway.aclose()

    _run(run())


def test_local_only_does_not_use_gemini_even_if_id_looks_external() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("gemini must not be called for local_only")

    gemini, requests = _gemini(handler)
    ollama = _OkOllama()
    gateway = ModelGateway(ollama_client=ollama, catalog=_catalog(), gemini=gemini)

    async def run() -> None:
        with pytest.raises(ProviderError) as exc:
            await gateway.generate(
                model="gemini-2.5-flash",
                prompt="hi",
                approach="local_only",
                endpoint="rag",
                allow_external_fallback=True,
            )
        assert exc.value.error_type == ErrorType.MODEL_UNAVAILABLE
        assert requests == []
        assert ollama.calls == 0
        await gateway.aclose()

    _run(run())


def test_hybrid_chat_connect_error_stays_local() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("gemini must not be called")

    gemini, requests = _gemini(handler)
    gateway = ModelGateway(ollama_client=_ConnectFailOllama(), catalog=_catalog(), gemini=gemini)

    async def run() -> None:
        with pytest.raises(httpx.ConnectError):
            await gateway.generate(
                model="qwen3.5:9b",
                prompt="hi",
                approach="hybrid",
                endpoint="chat",
            )
        assert requests == []
        await gateway.aclose()

    _run(run())
