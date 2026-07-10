from typing import Any

import httpx

from app.services.ollama_load_guard import OllamaLoadGuard


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        load_guard: OllamaLoadGuard | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._load_guard = load_guard
        self._client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def health(self) -> bool:
        try:
            response = await self._http_client.get(f"{self._base_url}/api/tags")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def generate(
        self,
        model: str,
        prompt: str,
        *,
        images: list[str] | None = None,
        keep_alive: str | int | None = None,
        options: dict[str, Any] | None = None,
        think: bool | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if images is not None:
            payload["images"] = images
        if options is not None:
            payload["options"] = options
        if think is not None:
            payload["think"] = think

        async with self._guarded_slot(model=model, operation="generate"):
            response = await self._http_client.post(
                f"{self._base_url}/api/generate",
                json=payload,
            )
        response.raise_for_status()
        return response.json()

    async def embed(self, model: str, text: str) -> list[float]:
        payload = {
            "model": model,
            "prompt": text,
        }

        async with self._guarded_slot(model=model, operation="embed"):
            response = await self._http_client.post(
                f"{self._base_url}/api/embeddings",
                json=payload,
            )
        response.raise_for_status()
        data = response.json()

        embedding = data.get("embedding")
        if not isinstance(embedding, list):
            raise ValueError("Ollama embeddings response did not include an embedding list.")
        return embedding

    @property
    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    def _guarded_slot(self, *, model: str, operation: str):
        if self._load_guard is None:
            return _NoopAsyncContext()
        return self._load_guard.slot(model=model, operation=operation)


class _NoopAsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None
