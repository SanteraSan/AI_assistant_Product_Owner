import asyncio

import pytest

from app.services import ollama_client as ollama_module
from app.services.ollama_client import OllamaClient


class _FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeAsyncClient:
    instances: list["_FakeAsyncClient"] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.is_closed = False
        self.posts: list[str] = []
        _FakeAsyncClient.instances.append(self)

    async def get(self, url: str) -> _FakeResponse:
        return _FakeResponse()

    async def post(self, url: str, json: dict[str, object]) -> _FakeResponse:
        self.posts.append(url)
        if url.endswith("/api/embeddings"):
            return _FakeResponse({"embedding": [1.0, 2.0, 3.0]})
        return _FakeResponse({"response": "ok"})

    async def aclose(self) -> None:
        self.is_closed = True


def test_ollama_client_reuses_http_client_and_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.instances = []
    monkeypatch.setattr(ollama_module.httpx, "AsyncClient", _FakeAsyncClient)

    client = OllamaClient(base_url="http://ollama.test", timeout_seconds=1)

    async def run_client_calls() -> None:
        await client.generate("model", "prompt")
        await client.embed("model", "text")
        await client.aclose()

    asyncio.run(run_client_calls())

    assert len(_FakeAsyncClient.instances) == 1
    assert len(_FakeAsyncClient.instances[0].posts) == 2
    assert _FakeAsyncClient.instances[0].is_closed is True
