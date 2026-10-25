"""Stage 5: browser provider key overrides the server client and stays out of logs.

No live Gemini, OpenRouter, or Ollama. No rows in the working database.
"""

from __future__ import annotations

import asyncio
import inspect
import io
import json
import logging
from typing import Any

import httpx
import pytest

from app.core.errors import ErrorType, ProviderError
from app.core.log_redaction import (
    SecretRedactionFilter,
    install_secret_redaction_filter,
    redact_secrets,
)
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    RagChatRequest,
    RagChatResponse,
    SourceChunk,
    reveal_provider_api_key,
)
from app.services.access_policy import UserContext
from app.services.conversation_context_service import ConversationContextService
from app.services.conversation_memory_service import ConversationMemoryService
from app.services.conversation_summary_service import _empty_summary_context
from app.services.feature_extractor import FeatureExtractor
from app.services.llm.catalog import ModelCatalog
from app.services.llm.gateway import ModelGateway
from app.services.llm.openai_compatible import OpenAICompatibleProvider
from app.services.llm.types import GenerationResult
from app.services.metrics import AppMetrics
from app.services.ollama_load_guard import OllamaOverloadedError
from app.services.rag_log_service import RagLogService
from app.services.rag_service import RagSearchResult, RagService
from app.services.rag_turn import configure_rag_turn, run_rag_turn
from app.services.sales_composer import SalesComposer
from app.services import rag_turn as rag_turn_module
from tests.auth_helpers import auth_headers

# Secrets are disjoint from the question and the model answer on purpose.
CLIENT_KEY = "tf-stage5-client-7kQm9p"
SERVER_KEY = "tf-stage5-server-4nLx2v"
NEIGHBOR_API_KEY = "tf-stage5-neighbor-8hQp3s"
LONG_KEY = "tf-stage5-toolong-marker" + ("a" * 512)
QUESTION = "Сколько открытых багов за неделю?"
ANSWER = "Семь критичных багов в отчёте."
SCOPE_DETAIL = (
    "External generation is blocked because this session already saw "
    "non-synthetic evidence. Open a new chat."
)
AGENT_GATEWAY_DETAIL = (
    "External providers are not supported for /agent/chat in this slice."
)
AGENT_ROUTER_DETAIL = (
    "External providers are not supported for /agent/chat in this slice. "
    "Use hybrid or local_only."
)
USER_TENANT = "local_demo"
FOREIGN_TENANT = "tenant-foreign-stage5"
FOREIGN_BUCKET = "bucket-foreign-stage5"
FOREIGN_DOCUMENT = "doc-foreign-stage5"
_LOGGER_NAMES = (
    "",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "httpx",
    "httpcore",
    "app",
)
_TURN_NAMES = (
    "bucket_service",
    "chat_history_service",
    "conversation_context_service",
    "conversation_memory_service",
    "conversation_summary_service",
    "feature_extractor",
    "qdrant_store",
    "rag_service",
    "sales_composer",
)

assert CLIENT_KEY not in QUESTION and CLIENT_KEY not in ANSWER
assert SERVER_KEY not in QUESTION and SERVER_KEY not in ANSWER
assert NEIGHBOR_API_KEY not in QUESTION and NEIGHBOR_API_KEY not in ANSWER
assert LONG_KEY not in QUESTION and LONG_KEY not in ANSWER
assert len(LONG_KEY) > 512


def _run(coro):
    return asyncio.run(coro)


def _completion(content: str = ANSWER) -> dict[str, object]:
    return {
        "id": "cmpl-stage5",
        "model": "gemini-2.5-flash",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 3},
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


class _SpyProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.generate_calls = 0

    async def generate(self, **kwargs: Any) -> GenerationResult:
        self.generate_calls += 1
        return await super().generate(**kwargs)


class _RecordingProvider(OpenAICompatibleProvider):
    instances: list["_RecordingProvider"] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.closed = False
        self.client_at_close: httpx.AsyncClient | None = None
        _RecordingProvider.instances.append(self)

    async def aclose(self) -> None:
        self.closed = True
        if self._client is not None:
            self.client_at_close = self._client
        await super().aclose()


class _HttpProxy:
    """Stand-in for the httpx module inside the provider, not the global client."""

    def __init__(self, async_client: Any) -> None:
        self.AsyncClient = async_client

    def __getattr__(self, name: str) -> Any:
        return getattr(httpx, name)


class _FakeHttp:
    def __init__(self) -> None:
        self.posts = 0
        self.is_closed = False

    async def post(self, *args: object, **kwargs: object) -> httpx.Response:
        del args, kwargs
        self.posts += 1
        return httpx.Response(200, json=_completion())

    async def aclose(self) -> None:
        self.is_closed = True


def _server_provider(
    provider_name: str,
    requests: list[httpx.Request],
    handler,
) -> tuple[_SpyProvider, httpx.AsyncClient]:
    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    provider = _SpyProvider(
        provider_name=provider_name,
        base_url=f"https://{provider_name}.example.invalid/v1",
        api_key=SERVER_KEY,
        timeout_seconds=5,
        http_client=client,
    )
    return provider, client


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_provider_http(monkeypatch: pytest.MonkeyPatch, async_client: Any) -> None:
    import app.services.llm.openai_compatible as provider_module

    monkeypatch.setattr(provider_module, "httpx", _HttpProxy(async_client))


def _patch_ephemeral_http(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        del args
        return _REAL_ASYNC_CLIENT(
            transport=httpx.MockTransport(wrapped),
            timeout=kwargs.get("timeout"),
        )

    _patch_provider_http(monkeypatch, factory)
    return requests


def _patch_recording_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _RecordingProvider.instances.clear()
    monkeypatch.setattr(
        "app.services.llm.gateway.OpenAICompatibleProvider",
        _RecordingProvider,
    )


def _forbid_provider_http(monkeypatch: pytest.MonkeyPatch) -> list[_FakeHttp]:
    created: list[_FakeHttp] = []

    def factory(*args: object, **kwargs: object) -> _FakeHttp:
        del args, kwargs
        client = _FakeHttp()
        created.append(client)
        return client

    _patch_provider_http(monkeypatch, factory)
    monkeypatch.setattr(
        "app.services.llm.gateway.OpenAICompatibleProvider",
        _RecordingProvider,
    )
    _RecordingProvider.instances.clear()
    return created


async def _shutdown(gateway: ModelGateway, *clients: httpx.AsyncClient) -> None:
    await gateway.aclose()
    for client in clients:
        await client.aclose()


def _reachable(root: object) -> tuple[set[int], list[str]]:
    seen: set[int] = set()
    strings: list[str] = []

    def walk(value: object, depth: int) -> None:
        if isinstance(value, str):
            strings.append(value)
            return
        if isinstance(value, bytes):
            strings.append(value.decode("utf-8", errors="replace"))
            return
        if value is None or isinstance(value, (int, float, bool)):
            return
        if isinstance(value, type) or callable(value):
            return
        marker = id(value)
        if marker in seen or depth > 8:
            return
        seen.add(marker)
        if isinstance(value, dict):
            for key, item in value.items():
                walk(key, depth + 1)
                walk(item, depth + 1)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                walk(item, depth + 1)
            return
        payload = getattr(value, "__dict__", None)
        if isinstance(payload, dict):
            walk(payload, depth + 1)

    walk(root, 0)
    return seen, strings


def _assert_gateway_has_no_client_key(gateway: ModelGateway) -> None:
    _seen, strings = _reachable(gateway)
    blob = "\n".join(strings)
    assert CLIENT_KEY not in blob
    assert "provider_api_key" not in gateway.__dict__


def _auth(request: httpx.Request) -> str:
    return request.headers["Authorization"]


def _search_result(sources: list[SourceChunk]) -> RagSearchResult:
    return RagSearchResult(
        sources=sources,
        features=[],
        source_types=[],
        score_threshold=None,
        retrieval={"mode": "stage5"},
        query_hints={},
        latency_ms=1,
    )


def _chunk(*, synthetic: bool) -> SourceChunk:
    metadata: dict[str, object] = {"synthetic": True} if synthetic else {}
    content = "Синтетический фрагмент." if synthetic else "Обычный фрагмент документа."
    return SourceChunk(id="src-stage5", content=content, metadata=metadata)


class _CountingGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate(self, **kwargs: object) -> GenerationResult:
        self.calls.append(dict(kwargs))
        return GenerationResult(
            response=ANSWER,
            model=str(kwargs.get("model") or "gemini-2.5-flash"),
            provider="gemini",
        )


def _rag_service(gateway: _CountingGateway) -> RagService:
    service = RagService(
        ollama_client=_OkOllama(),  # type: ignore[arg-type]
        qdrant_store=type("Q", (), {"collection_name": "documents"})(),  # type: ignore[arg-type]
        feature_extractor=FeatureExtractor(),
        query_router=object(),  # type: ignore[arg-type]
        embedding_model="nomic-embed-text",
        default_model="gemini-2.5-flash",
        default_top_k=4,
        default_score_threshold=None,
        candidate_multiplier=2,
        generation_keep_alive="10m",
        generation_temperature=0.1,
        generation_top_p=0.9,
        excel_supplement_scroll_limit=1,
        docx_supplement_scroll_limit=1,
        model_gateway=gateway,  # type: ignore[arg-type]
    )
    return service


async def _expect_scope_denial(call) -> ProviderError:
    try:
        await call()
    except ProviderError as exc:
        assert exc.error_type == ErrorType.EXTERNAL_SCOPE_NOT_SYNTHETIC
        assert exc.status_code == 403
        assert exc.detail == SCOPE_DETAIL
        assert CLIENT_KEY not in exc.detail
        return exc
    raise AssertionError("expected EXTERNAL_SCOPE_NOT_SYNTHETIC before generate")


def _filter_counts() -> dict[str, int]:
    found: dict[str, int] = {}
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        found[name] = sum(isinstance(item, SecretRedactionFilter) for item in logger.filters)
        for index, handler in enumerate(logger.handlers):
            found[f"{name}#{index}"] = sum(
                isinstance(item, SecretRedactionFilter) for item in handler.filters
            )
    return found


async def _post_json(
    path: str,
    payload: dict[str, object],
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    from app import main as main_module

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=payload, headers=headers)


def _assert_secrets_absent(text: str, *secrets: str) -> None:
    for secret in secrets:
        assert secret not in text


@pytest.mark.parametrize(
    ("model", "provider_name"),
    [
        ("gemini-2.5-flash", "gemini"),
        ("openai/gpt-4o-mini", "openrouter"),
    ],
)
def test_external_without_client_key_reuses_server_client(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    provider_name: str,
) -> None:
    """Assertion 1: no client key reuses the long-lived server client."""

    gemini_requests: list[httpx.Request] = []
    openrouter_requests: list[httpx.Request] = []
    gemini, gemini_client = _server_provider(
        "gemini",
        gemini_requests,
        lambda _request: httpx.Response(200, json=_completion()),
    )
    openrouter, openrouter_client = _server_provider(
        "openrouter",
        openrouter_requests,
        lambda _request: httpx.Response(200, json=_completion()),
    )
    _patch_recording_provider(monkeypatch)
    _patch_ephemeral_http(
        monkeypatch,
        lambda _request: (_ for _ in ()).throw(AssertionError("ephemeral HTTP")),
    )
    gateway = ModelGateway(
        ollama_client=_OkOllama(),  # type: ignore[arg-type]
        catalog=ModelCatalog(gemini_configured=True, openrouter_configured=True),
        gemini=gemini,
        openrouter=openrouter,
    )
    gemini_before = gateway._gemini
    openrouter_before = gateway._openrouter

    async def run() -> None:
        result = await gateway.generate(
            model=model,
            prompt=QUESTION,
            approach="external",
            endpoint="chat",
            provider_api_key=None,
        )
        assert result.response == ANSWER
        assert gemini.generate_calls == (1 if provider_name == "gemini" else 0)
        assert openrouter.generate_calls == (1 if provider_name == "openrouter" else 0)
        requests = gemini_requests if provider_name == "gemini" else openrouter_requests
        assert len(requests) == 1
        assert _auth(requests[0]) == f"Bearer {SERVER_KEY}"
        assert gateway._gemini is gemini_before
        assert gateway._openrouter is openrouter_before
        assert _RecordingProvider.instances == []
        _assert_gateway_has_no_client_key(gateway)
        await _shutdown(gateway, gemini_client, openrouter_client)

    _run(run())


def test_client_key_overrides_without_replacing_long_lived_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assertion 2: client key is sent once, then a call without a key uses the server key."""

    gemini_requests: list[httpx.Request] = []
    openrouter_requests: list[httpx.Request] = []
    gemini, gemini_client = _server_provider(
        "gemini",
        gemini_requests,
        lambda _request: httpx.Response(200, json=_completion()),
    )
    openrouter, openrouter_client = _server_provider(
        "openrouter",
        openrouter_requests,
        lambda _request: httpx.Response(200, json=_completion()),
    )
    ephemeral_requests = _patch_ephemeral_http(
        monkeypatch,
        lambda _request: httpx.Response(200, json=_completion()),
    )
    _patch_recording_provider(monkeypatch)
    gateway = ModelGateway(
        ollama_client=_OkOllama(),  # type: ignore[arg-type]
        catalog=ModelCatalog(gemini_configured=True, openrouter_configured=True),
        gemini=gemini,
        openrouter=openrouter,
    )
    gemini_before = gateway._gemini
    openrouter_before = gateway._openrouter

    async def run() -> None:
        for model in ("gemini-2.5-flash", "openai/gpt-4o-mini"):
            result = await gateway.generate(
                model=model,
                prompt=QUESTION,
                approach="external",
                endpoint="chat",
                provider_api_key=CLIENT_KEY,
            )
            assert result.response == ANSWER
        assert gemini.generate_calls == 0
        assert openrouter.generate_calls == 0
        assert [_auth(item) for item in ephemeral_requests] == [
            f"Bearer {CLIENT_KEY}",
            f"Bearer {CLIENT_KEY}",
        ]
        assert gemini_requests == []
        assert openrouter_requests == []
        assert gateway._gemini is gemini_before
        assert gateway._openrouter is openrouter_before
        assert all(item.closed for item in _RecordingProvider.instances)
        seen, _strings = _reachable(gateway)
        for ephemeral in _RecordingProvider.instances:
            assert id(ephemeral) not in seen
        _assert_gateway_has_no_client_key(gateway)

        again = await gateway.generate(
            model="gemini-2.5-flash",
            prompt=QUESTION,
            approach="external",
            endpoint="rag",
            provider_api_key=None,
        )
        assert again.response == ANSWER
        assert gemini.generate_calls == 1
        assert openrouter.generate_calls == 0
        assert len(gemini_requests) == 1
        assert _auth(gemini_requests[0]) == f"Bearer {SERVER_KEY}"
        assert len(ephemeral_requests) == 2
        assert gateway._gemini is gemini_before
        assert gateway._openrouter is openrouter_before
        await _shutdown(gateway, gemini_client, openrouter_client)

    _run(run())


def test_missing_server_client_without_key_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assertion 3: no key and no server client is 503, with no provider HTTP."""

    created = _forbid_provider_http(monkeypatch)

    async def run() -> None:
        cases = (
            (False, "gemini-2.5-flash", "Gemini is not configured."),
            (False, "openai/gpt-4o-mini", "OpenRouter is not configured."),
            (True, "gemini-2.5-flash", "gemini is not configured."),
            (True, "openai/gpt-4o-mini", "openrouter is not configured."),
        )
        for configured, model, detail in cases:
            gateway = ModelGateway(
                ollama_client=_OkOllama(),  # type: ignore[arg-type]
                catalog=ModelCatalog(
                    gemini_configured=configured,
                    openrouter_configured=configured,
                ),
                gemini=None,
                openrouter=None,
            )
            with pytest.raises(ProviderError) as exc:
                await gateway.generate(
                    model=model,
                    prompt=QUESTION,
                    approach="external",
                    endpoint="chat",
                    provider_api_key=None,
                )
            assert exc.value.status_code == 503
            assert exc.value.error_type == ErrorType.MODEL_UNAVAILABLE
            assert exc.value.detail == detail
            assert "is not configured" in exc.value.detail
            await gateway.aclose()
        assert created == []
        assert _RecordingProvider.instances == []
        assert all(item.posts == 0 for item in created)

    _run(run())


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize(
    ("model", "provider_name"),
    [
        ("gemini-2.5-flash", "gemini"),
        ("openai/gpt-4o-mini", "openrouter"),
    ],
)
def test_client_key_without_server_client_is_not_retained(
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
    model: str,
    provider_name: str,
) -> None:
    """Assertion 4: one ephemeral call, then the gateway keeps no reference to it."""

    def handler(_request: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(400, text='{"error":"bad request"}')
        return httpx.Response(200, json=_completion())

    ephemeral_requests = _patch_ephemeral_http(monkeypatch, handler)
    _patch_recording_provider(monkeypatch)
    gateway = ModelGateway(
        ollama_client=_OkOllama(),  # type: ignore[arg-type]
        catalog=ModelCatalog(gemini_configured=False, openrouter_configured=False),
        gemini=None,
        openrouter=None,
    )

    async def run() -> None:
        if fail:
            with pytest.raises(ProviderError) as exc:
                await gateway.generate(
                    model=model,
                    prompt=QUESTION,
                    approach="external",
                    endpoint="chat",
                    provider_api_key=CLIENT_KEY,
                )
            assert CLIENT_KEY not in exc.value.detail
        else:
            result = await gateway.generate(
                model=model,
                prompt=QUESTION,
                approach="external",
                endpoint="chat",
                provider_api_key=CLIENT_KEY,
            )
            assert result.response == ANSWER
            assert result.provider == provider_name
        assert len(ephemeral_requests) == 1
        assert _auth(ephemeral_requests[0]) == f"Bearer {CLIENT_KEY}"
        assert len(_RecordingProvider.instances) == 1
        ephemeral = _RecordingProvider.instances[0]
        assert ephemeral.closed is True
        assert ephemeral.client_at_close is not None
        assert ephemeral.client_at_close.is_closed is True
        assert gateway._gemini is None
        assert gateway._openrouter is None
        seen, _strings = _reachable(gateway)
        assert id(ephemeral) not in seen
        _assert_gateway_has_no_client_key(gateway)
        await gateway.aclose()

    _run(run())


def test_hybrid_and_local_only_do_not_send_the_client_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assertion 5: hybrid and local_only ignore the client key; RAG fallback uses the server key."""

    requests: list[httpx.Request] = []
    gemini, gemini_client = _server_provider(
        "gemini",
        requests,
        lambda _request: httpx.Response(200, json=_completion("fallback-answer")),
    )
    _patch_recording_provider(monkeypatch)
    _patch_ephemeral_http(
        monkeypatch,
        lambda _request: (_ for _ in ()).throw(AssertionError("ephemeral HTTP")),
    )
    ollama = _OkOllama()
    overload = _OverloadOllama()
    catalog = ModelCatalog(gemini_configured=True, extra_local_models=("qwen3.5:9b",))

    async def run() -> None:
        quiet = ModelGateway(ollama_client=ollama, catalog=catalog, gemini=gemini)
        await quiet.generate(
            model="qwen3.5:9b",
            prompt=QUESTION,
            approach="hybrid",
            endpoint="rag",
            allow_external_fallback=True,
            provider_api_key=CLIENT_KEY,
        )
        await quiet.generate(
            model="qwen3.5:9b",
            prompt=QUESTION,
            approach="local_only",
            endpoint="rag",
            allow_external_fallback=True,
            provider_api_key=CLIENT_KEY,
        )
        with pytest.raises(ProviderError) as local_external:
            await quiet.generate(
                model="gemini-2.5-flash",
                prompt=QUESTION,
                approach="local_only",
                endpoint="rag",
                allow_external_fallback=True,
                provider_api_key=CLIENT_KEY,
            )
        assert local_external.value.error_type == ErrorType.MODEL_UNAVAILABLE
        blocked = ModelGateway(ollama_client=overload, catalog=catalog, gemini=gemini)
        with pytest.raises(OllamaOverloadedError):
            await blocked.generate(
                model="qwen3.5:9b",
                prompt=QUESTION,
                approach="hybrid",
                endpoint="chat",
                allow_external_fallback=True,
                provider_api_key=CLIENT_KEY,
            )
        with pytest.raises(OllamaOverloadedError):
            await blocked.generate(
                model="qwen3.5:9b",
                prompt=QUESTION,
                approach="local_only",
                endpoint="rag",
                allow_external_fallback=True,
                provider_api_key=CLIENT_KEY,
            )
        with pytest.raises(OllamaOverloadedError):
            await blocked.generate(
                model="qwen3.5:9b",
                prompt=QUESTION,
                approach="hybrid",
                endpoint="rag",
                allow_external_fallback=False,
                provider_api_key=CLIENT_KEY,
            )
        assert requests == []
        assert ollama.calls == 2
        assert _RecordingProvider.instances == []

        fallback = ModelGateway(ollama_client=overload, catalog=catalog, gemini=gemini)
        gemini_before = fallback._gemini
        result = await fallback.generate(
            model="qwen3.5:9b",
            prompt=QUESTION,
            approach="hybrid",
            endpoint="rag",
            allow_external_fallback=True,
            provider_api_key=CLIENT_KEY,
        )
        assert result.fallback_from == "ollama"
        assert result.fallback_to == "gemini"
        assert len(requests) == 1
        assert _auth(requests[0]) == f"Bearer {SERVER_KEY}"
        assert CLIENT_KEY not in requests[0].content.decode()
        assert gemini.generate_calls == 1
        assert fallback._gemini is gemini_before
        assert _RecordingProvider.instances == []
        _assert_gateway_has_no_client_key(fallback)
        await _shutdown(quiet, gemini_client)
        await blocked.aclose()
        await fallback.aclose()

    _run(run())


def test_agent_external_does_not_create_client_or_leak_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assertion 6: gateway agent+external returns 400 and does not build a client."""

    requests: list[httpx.Request] = []
    gemini, gemini_client = _server_provider(
        "gemini",
        requests,
        lambda _request: httpx.Response(200, json=_completion()),
    )
    _patch_recording_provider(monkeypatch)
    gateway = ModelGateway(
        ollama_client=_OkOllama(),  # type: ignore[arg-type]
        catalog=ModelCatalog(gemini_configured=True),
        gemini=gemini,
    )

    async def run() -> None:
        for approach in ("external", "openapi"):
            with pytest.raises(ProviderError) as exc:
                await gateway.generate(
                    model="gemini-2.5-flash",
                    prompt=QUESTION,
                    approach=approach,
                    endpoint="agent",
                    provider_api_key=CLIENT_KEY,
                )
            assert exc.value.status_code == 400
            assert exc.value.error_type == ErrorType.EXTERNAL_AGENT_NOT_SUPPORTED
            assert exc.value.detail == AGENT_GATEWAY_DETAIL
            assert CLIENT_KEY not in exc.value.detail
        assert gemini.generate_calls == 0
        assert requests == []
        assert _RecordingProvider.instances == []
        await _shutdown(gateway, gemini_client)

    _run(run())


def test_agent_router_rejects_external_before_model(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Assertion 6: the agent router still refuses before the model runs."""

    from app import main as main_module

    caplog.set_level(logging.DEBUG)

    async def _forbidden_run(**_kwargs: object) -> None:
        raise AssertionError("agent model must not run")

    async def _forbidden_generate(**_kwargs: object) -> None:
        raise AssertionError("gateway must not generate")

    monkeypatch.setattr(main_module, "rate_limiter", None)
    monkeypatch.setattr(main_module.agent_orchestrator, "run", _forbidden_run)
    monkeypatch.setattr(main_module.model_gateway, "generate", _forbidden_generate)
    if main_module.langgraph_agent_adapter is not None:
        monkeypatch.setattr(main_module.langgraph_agent_adapter, "run", _forbidden_run)

    async def run() -> None:
        for approach in ("external", "openapi"):
            response = await _post_json(
                "/agent/chat",
                {
                    "message": QUESTION,
                    "approach": approach,
                    "model": "gemini-2.5-flash",
                    "provider_api_key": CLIENT_KEY,
                },
                headers=auth_headers(),
            )
            body = response.json()
            assert response.status_code == 400
            assert body["error_type"] == "external_agent_not_supported"
            assert body["detail"] == AGENT_ROUTER_DETAIL
            assert CLIENT_KEY not in response.text
        _assert_secrets_absent(caplog.text, CLIENT_KEY)

    _run(run())


def test_external_scope_blocks_rag_and_sales_before_generate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Assertion 7: non-synthetic evidence still denies external generation before the model."""

    caplog.set_level(logging.DEBUG)

    async def run() -> None:
        rag_gateway = _CountingGateway()
        rag = _rag_service(rag_gateway)

        async def non_synthetic_search(**_kwargs: object) -> RagSearchResult:
            return _search_result([_chunk(synthetic=False)])

        async def synthetic_search(**_kwargs: object) -> RagSearchResult:
            return _search_result([_chunk(synthetic=True)])

        rag.search = non_synthetic_search  # type: ignore[method-assign]
        denial = await _expect_scope_denial(
            lambda: rag.answer(
                QUESTION,
                approach="external",
                provider_api_key=CLIENT_KEY,
                session_seen_non_synthetic=False,
            )
        )
        assert denial.extra["reason"] == "retrieved_non_synthetic"
        assert rag_gateway.calls == []

        rag.search = synthetic_search  # type: ignore[method-assign]
        denial = await _expect_scope_denial(
            lambda: rag.answer(
                QUESTION,
                approach="external",
                provider_api_key=CLIENT_KEY,
                session_seen_non_synthetic=True,
            )
        )
        assert denial.extra["reason"] == "session_memory"
        assert rag_gateway.calls == []

        allowed = await rag.answer(
            QUESTION,
            approach="external",
            provider_api_key=CLIENT_KEY,
            session_seen_non_synthetic=False,
        )
        assert allowed.response == ANSWER
        assert len(rag_gateway.calls) == 1
        assert rag_gateway.calls[0]["provider_api_key"] == CLIENT_KEY
        assert "provider_api_key" not in allowed.model_dump()

        sales_gateway = _CountingGateway()

        class _Repo:
            async def list_identities(self, **_kwargs: object) -> list[object]:
                return []

            async def get_card(self, **_kwargs: object) -> None:
                raise AssertionError("deal card must not be loaded")

        class _SalesRag:
            def __init__(self) -> None:
                self.synthetic = False

            async def search(self, **_kwargs: object) -> RagSearchResult:
                return _search_result([_chunk(synthetic=self.synthetic)])

        sales_rag = _SalesRag()
        composer = SalesComposer(
            rag_service=sales_rag,  # type: ignore[arg-type]
            deal_repository=_Repo(),  # type: ignore[arg-type]
            model_gateway=sales_gateway,  # type: ignore[arg-type]
            default_model="gemini-2.5-flash",
            generation_keep_alive="10m",
            generation_temperature=0.1,
            generation_top_p=0.9,
            collection_name="documents",
        )
        sales_rag.synthetic = False
        denial = await _expect_scope_denial(
            lambda: composer.answer(
                QUESTION,
                approach="external",
                tenant_id=USER_TENANT,
                bucket_ids=["taskflow_seed"],
                provider_api_key=CLIENT_KEY,
            )
        )
        assert denial.extra["reason"] == "retrieved_non_synthetic"
        sales_rag.synthetic = True
        denial = await _expect_scope_denial(
            lambda: composer.answer(
                QUESTION,
                approach="external",
                tenant_id=USER_TENANT,
                bucket_ids=["taskflow_seed"],
                provider_api_key=CLIENT_KEY,
                session_seen_non_synthetic=True,
            )
        )
        assert denial.extra["reason"] == "session_memory"
        assert sales_gateway.calls == []
        _assert_secrets_absent(caplog.text, CLIENT_KEY, SERVER_KEY)

    _run(run())


def test_redaction_hides_key_but_keeps_the_log_record() -> None:
    """Assertion 8: secrets are redacted, the record is kept, and install is idempotent."""

    bearer_line = f"счётчик багов Authorization: Bearer {CLIENT_KEY} конец"
    dict_repr = "{'Authorization': 'Bearer " + CLIENT_KEY + "', 'note': 'соседний текст'}"
    json_line = (
        '{"provider_api_key":"' + CLIENT_KEY + '","note":"счётчик багов"}'
    )
    redacted_bearer = redact_secrets(bearer_line)
    redacted_dict = redact_secrets(dict_repr)
    redacted_json = redact_secrets(json_line)
    assert CLIENT_KEY not in redacted_bearer
    assert CLIENT_KEY not in redacted_dict
    assert CLIENT_KEY not in redacted_json
    assert "счётчик багов" in redacted_bearer
    assert "конец" in redacted_bearer
    assert "соседний текст" in redacted_dict
    assert "счётчик багов" in redacted_json
    assert "***" in redacted_bearer
    assert "***" in redacted_dict
    assert "***" in redacted_json

    record = logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="счётчик багов Authorization: Bearer %s конец",
        args=(CLIENT_KEY,),
        exc_info=None,
    )
    assert SecretRedactionFilter().filter(record) is True
    rendered = record.getMessage()
    assert CLIENT_KEY not in rendered
    assert "счётчик багов" in rendered
    assert "конец" in rendered

    install_secret_redaction_filter()
    once = _filter_counts()
    install_secret_redaction_filter()
    assert _filter_counts() == once
    assert all(count <= 1 for count in once.values())
    assert once["app"] == 1

    logger = logging.getLogger("app")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    previous_level = logger.level
    previous_propagate = logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logger.info("%s", bearer_line)
        logger.info("%s", dict_repr)
        logger.info("%s", json_line)
        logger.info(
            "счётчик багов %s конец",
            {"Authorization": f"Bearer {CLIENT_KEY}", "note": "соседний текст"},
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate

    written = stream.getvalue()
    assert written.strip() != ""
    assert CLIENT_KEY not in written
    assert "счётчик багов" in written
    assert "конец" in written
    assert "соседний текст" in written
    assert _filter_counts() == once


def test_validation_error_does_not_echo_provider_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Assertion 9: 422 replaces provider_api_key and a neighboring api_key with ***."""

    caplog.set_level(logging.DEBUG)
    headers = auth_headers()

    async def run() -> None:
        for path in ("/chat", "/rag/chat"):
            response = await _post_json(
                path,
                {"message": QUESTION, "provider_api_key": LONG_KEY},
                headers=headers,
            )
            assert response.status_code == 422, response.text
            errors = [
                item
                for item in response.json()["detail"]
                if isinstance(item, dict) and "provider_api_key" in item.get("loc", [])
            ]
            assert len(errors) == 1
            assert errors[0]["input"] == "***"
            assert "tf-stage5-toolong-marker" not in response.text
            assert LONG_KEY not in response.text

        nested = await _post_json(
            "/chat",
            {
                "message": {
                    "provider_api_key": CLIENT_KEY,
                    "api_key": NEIGHBOR_API_KEY,
                    "note": "соседнее поле",
                },
                "provider_api_key": CLIENT_KEY,
                "approach": "external",
            },
            headers=headers,
        )
        assert nested.status_code == 422, nested.text
        message_errors = [
            item
            for item in nested.json()["detail"]
            if isinstance(item, dict) and "message" in item.get("loc", [])
        ]
        assert message_errors
        leaked = message_errors[0]["input"]
        assert leaked["provider_api_key"] == "***"
        assert leaked["api_key"] == "***"
        assert leaked["note"] == "соседнее поле"
        _assert_secrets_absent(nested.text, CLIENT_KEY, NEIGHBOR_API_KEY)

        approach = 'prefix "api_key":"' + NEIGHBOR_API_KEY + '" ' + ("x" * 40)
        assert len(approach) > 64
        sibling = await _post_json(
            "/chat",
            {
                "message": QUESTION,
                "approach": approach,
                "provider_api_key": CLIENT_KEY,
            },
            headers=headers,
        )
        assert sibling.status_code == 422, sibling.text
        _assert_secrets_absent(sibling.text, CLIENT_KEY, NEIGHBOR_API_KEY)
        _assert_secrets_absent(caplog.text, CLIENT_KEY, NEIGHBOR_API_KEY, LONG_KEY)

    _run(run())


def test_provider_echo_is_redacted_in_http_detail(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Assertion 9: a provider body that echoes the key is returned with ***."""

    from app import main as main_module

    caplog.set_level(logging.DEBUG)
    server_requests: list[httpx.Request] = []

    def server_handler(_request: httpx.Request) -> httpx.Response:
        body = (
            '{"note":"provider echo","provider_api_key":"'
            + SERVER_KEY
            + '"} Authorization: Bearer '
            + SERVER_KEY
        )
        return httpx.Response(400, text=body)

    gemini, gemini_client = _server_provider("gemini", server_requests, server_handler)
    ephemeral_requests = _patch_ephemeral_http(
        monkeypatch,
        lambda _request: httpx.Response(
            400,
            text=(
                '{"note":"provider echo","provider_api_key":"'
                + CLIENT_KEY
                + '"} Authorization: Bearer '
                + CLIENT_KEY
            ),
        ),
    )
    gateway = ModelGateway(
        ollama_client=_OkOllama(),  # type: ignore[arg-type]
        catalog=ModelCatalog(gemini_configured=True, openrouter_configured=False),
        gemini=gemini,
    )
    monkeypatch.setattr(main_module, "model_gateway", gateway)
    monkeypatch.setattr(main_module, "rate_limiter", None)

    async def run() -> None:
        try:
            server_response = await _post_json(
                "/chat",
                {
                    "message": QUESTION,
                    "approach": "external",
                    "model": "gemini-2.5-flash",
                },
                headers=auth_headers(),
            )
            assert server_response.status_code == 400, server_response.text
            server_body = server_response.json()
            assert server_body["error_type"] == "external_provider_error"
            assert "provider echo" in server_body["detail"]
            assert "***" in server_body["detail"]
            _assert_secrets_absent(server_response.text, SERVER_KEY, CLIENT_KEY)
            assert len(server_requests) == 1
            assert _auth(server_requests[0]) == f"Bearer {SERVER_KEY}"

            client_response = await _post_json(
                "/chat",
                {
                    "message": QUESTION,
                    "approach": "external",
                    "model": "gemini-2.5-flash",
                    "provider_api_key": CLIENT_KEY,
                },
                headers=auth_headers(),
            )
            assert client_response.status_code == 400, client_response.text
            client_body = client_response.json()
            assert "provider echo" in client_body["detail"]
            assert "***" in client_body["detail"]
            _assert_secrets_absent(client_response.text, CLIENT_KEY, SERVER_KEY)
            assert len(ephemeral_requests) == 1
            assert _auth(ephemeral_requests[0]) == f"Bearer {CLIENT_KEY}"
            assert len(server_requests) == 1
            assert gateway._gemini is gemini
            _assert_secrets_absent(caplog.text, CLIENT_KEY, SERVER_KEY)
        finally:
            await _shutdown(gateway, gemini_client)

    _run(run())


def test_responses_logs_and_metrics_have_no_key_field() -> None:
    """Assertion 10: response models, RAG logs, and metrics have no slot for the key."""

    assert "provider_api_key" not in ChatResponse.model_fields
    assert "api_key" not in ChatResponse.model_fields
    assert "provider_api_key" not in RagChatResponse.model_fields
    chat = ChatResponse(
        model="gemini-2.5-flash",
        response=ANSWER,
        latency_ms=1,
        provider="gemini",
    )
    rag_response = RagChatResponse(
        model="gemini-2.5-flash",
        response=ANSWER,
        latency_ms=3,
        provider="gemini",
        collection="documents",
        sources=[
            SourceChunk(
                id="src-1",
                content=ANSWER,
                title="Отчёт",
                source_type="feedback",
                source_path="feedback/bugs.txt",
                metadata={"synthetic": True},
            )
        ],
        features=["feedback"],
        source_types=["feedback"],
        retrieval={"mode": "stage5"},
        prompt_tokens_estimate=4,
    )
    assert "provider_api_key" not in chat.model_dump()
    assert "provider_api_key" not in rag_response.model_dump()
    _assert_secrets_absent(chat.model_dump_json(), CLIENT_KEY, SERVER_KEY)
    _assert_secrets_absent(rag_response.model_dump_json(), CLIENT_KEY, SERVER_KEY)
    assert "provider_api_key" not in inspect.signature(RagLogService.log_response).parameters

    class _Session:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, obj: object) -> None:
            self.added.append(obj)

        async def commit(self) -> None:
            return None

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    session = _Session()
    service = RagLogService(session_factory=lambda: session)  # type: ignore[arg-type]

    async def run() -> None:
        await service.log_response(message=QUESTION, response=rag_response)

    _run(run())
    assert len(session.added) == 1
    stored = session.added[0]
    column_names = {column.key for column in stored.__table__.columns}  # type: ignore[attr-defined]
    assert "provider_api_key" not in column_names
    assert "api_key" not in column_names
    blobs = [
        f"{column.key}={getattr(stored, column.key)!r}"
        for column in stored.__table__.columns  # type: ignore[attr-defined]
    ]
    for source in stored.sources:  # type: ignore[attr-defined]
        blobs.extend(
            f"{column.key}={getattr(source, column.key)!r}"
            for column in source.__table__.columns
        )
    _assert_secrets_absent("\n".join(blobs), CLIENT_KEY, SERVER_KEY, NEIGHBOR_API_KEY)

    metrics = AppMetrics(enabled=True)
    assert "provider_api_key" not in inspect.signature(AppMetrics.observe_rag).parameters
    assert "provider_api_key" not in inspect.signature(AppMetrics.observe_http).parameters
    metrics.observe_rag(outcome="success", duration_seconds=0.2)
    metrics.observe_http(
        method="POST",
        path="/rag/chat",
        status_code=200,
        duration_seconds=0.1,
    )
    rendered = metrics.render_prometheus().decode("utf-8")
    summary = json.dumps(metrics.summary())
    _assert_secrets_absent(rendered, CLIENT_KEY, SERVER_KEY, NEIGHBOR_API_KEY)
    _assert_secrets_absent(summary, CLIENT_KEY, SERVER_KEY, NEIGHBOR_API_KEY)
    assert "provider_api_key" not in rendered


def test_blank_and_whitespace_key_stay_on_server_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assertion 10: an empty or whitespace key is an absent key, not an empty Bearer."""

    for blank in ("", "   ", "\n\t ", " " * 600, None):
        chat = ChatRequest(message=QUESTION, provider_api_key=blank)
        rag = RagChatRequest(message=QUESTION, provider_api_key=blank)
        assert chat.provider_api_key is None
        assert rag.provider_api_key is None
        assert reveal_provider_api_key(chat.provider_api_key) is None
        assert reveal_provider_api_key(rag.provider_api_key) is None

    requests: list[httpx.Request] = []
    gemini, gemini_client = _server_provider(
        "gemini",
        requests,
        lambda _request: httpx.Response(200, json=_completion()),
    )
    gateway = ModelGateway(
        ollama_client=_OkOllama(),  # type: ignore[arg-type]
        catalog=ModelCatalog(gemini_configured=True),
        gemini=gemini,
    )

    async def gateway_run() -> None:
        for blank in ("", "   ", "\n\t ", None):
            result = await gateway.generate(
                model="gemini-2.5-flash",
                prompt=QUESTION,
                approach="external",
                endpoint="chat",
                provider_api_key=blank,
            )
            assert result.response == ANSWER
        assert len(requests) == 4
        for request in requests:
            assert _auth(request) == f"Bearer {SERVER_KEY}"
            assert _auth(request) not in {"Bearer", "Bearer ", "Bearer    "}
        await _shutdown(gateway, gemini_client)

    _run(gateway_run())

    from app import main as main_module

    captured: list[object] = []

    class _FakeGateway:
        async def generate(self, **kwargs: object) -> GenerationResult:
            captured.append(kwargs.get("provider_api_key"))
            return GenerationResult(
                response=ANSWER,
                model=str(kwargs["model"]),
                provider="gemini",
            )

    async def _no_save(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(main_module, "model_gateway", _FakeGateway())
    monkeypatch.setattr(main_module, "rate_limiter", None)
    monkeypatch.setattr(main_module, "_try_save_chat_exchange", _no_save)

    async def http_run() -> None:
        for blank in ("", "   ", " " * 600):
            response = await _post_json(
                "/chat",
                {
                    "message": QUESTION,
                    "approach": "external",
                    "model": "gemini-2.5-flash",
                    "provider_api_key": blank,
                },
                headers=auth_headers(),
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["response"] == ANSWER
            assert "provider_api_key" not in body
            assert "api_key" not in body
        assert captured == [None, None, None]

    _run(http_run())


def test_provider_key_does_not_open_foreign_tenant(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A browser key does not switch tenant or open another tenant's bucket."""

    caplog.set_level(logging.DEBUG)
    saved = {name: getattr(rag_turn_module, name, None) for name in _TURN_NAMES}
    list_calls: list[tuple[str, str]] = []
    document_calls: list[tuple[str, str]] = []
    answer_calls: list[dict[str, object]] = []
    sales_calls = {"n": 0}

    class _Buckets:
        async def list_documents(self, *, user: UserContext, bucket_id: str):
            assert user.tenant_id == USER_TENANT
            list_calls.append((user.tenant_id, bucket_id))
            return None

        async def list_available_documents(self, *, user: UserContext) -> list[object]:
            assert user.tenant_id == USER_TENANT
            return []

        async def get_document(self, *, user: UserContext, document_id: str):
            assert user.tenant_id == USER_TENANT
            document_calls.append((user.tenant_id, document_id))
            return None

    class _History:
        async def get_session_metadata(self, *, tenant_id: str, user_id: str | None, session_id: str | None):
            del user_id, session_id
            assert tenant_id == USER_TENANT
            return {}

        async def get_recent_messages(self, *, session_id: str | None, limit: int) -> list[object]:
            del session_id, limit
            return []

        async def update_session(self, **_kwargs: object) -> None:
            raise AssertionError("session must not be updated")

    class _Summary:
        async def prepare_summary(self, *, session_id: str | None):
            del session_id
            return _empty_summary_context("no_session")

    class _Rag:
        async def answer(self, **kwargs: object) -> RagChatResponse:
            answer_calls.append(dict(kwargs))
            return RagChatResponse(
                model="gemini-2.5-flash",
                response=ANSWER,
                latency_ms=1,
                collection="documents",
                sources=[],
                retrieval={"external_scope": {"persist_session_seen_non_synthetic": False}},
            )

    class _Sales:
        async def answer(self, **_kwargs: object) -> None:
            sales_calls["n"] += 1
            raise AssertionError("sales composer must not run")

    feature_extractor = FeatureExtractor()
    try:
        configure_rag_turn(
            bucket_service=_Buckets(),  # type: ignore[arg-type]
            chat_history_service=_History(),  # type: ignore[arg-type]
            conversation_context_service=ConversationContextService(
                feature_extractor=feature_extractor
            ),
            conversation_memory_service=ConversationMemoryService(),
            conversation_summary_service=_Summary(),  # type: ignore[arg-type]
            feature_extractor=feature_extractor,
            qdrant_store=type("Q", (), {"collection_name": "documents"})(),  # type: ignore[arg-type]
            rag_service=_Rag(),  # type: ignore[arg-type]
            sales_composer=_Sales(),  # type: ignore[arg-type]
        )

        async def run() -> None:
            payload = RagChatRequest(
                message=QUESTION,
                approach="external",
                model="gemini-2.5-flash",
                tenant_id=FOREIGN_TENANT,
                bucket_ids=[FOREIGN_BUCKET],
                document_ids=[FOREIGN_DOCUMENT],
                provider_api_key=CLIENT_KEY,
            )
            result = await run_rag_turn(
                payload=payload,
                user=UserContext(
                    tenant_id=USER_TENANT,
                    user_id="local-user-1",
                    roles=frozenset({"admin"}),
                ),
                started_at=0.0,
            )
            assert result.response.response == ANSWER
            assert sales_calls["n"] == 0
            assert len(answer_calls) == 1
            sent = answer_calls[0]
            assert sent["tenant_id"] == USER_TENANT
            assert sent["tenant_id"] != FOREIGN_TENANT
            assert sent["provider_api_key"] == CLIENT_KEY
            assert sent["document_ids"] == []
            assert sent["allowed_source_paths"] == []
            assert FOREIGN_TENANT not in repr(sent)
            assert list_calls == [(USER_TENANT, FOREIGN_BUCKET)]
            assert document_calls == [(USER_TENANT, FOREIGN_DOCUMENT)]
            _assert_secrets_absent(caplog.text, CLIENT_KEY)

        _run(run())
    finally:
        for name, value in saved.items():
            setattr(rag_turn_module, name, value)
