from typing import Any

import httpx


class OllamaClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
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
        if options is not None:
            payload["options"] = options
        if think is not None:
            payload["think"] = think

        response = await self._http_client.post(f"{self._base_url}/api/generate", json=payload)
        response.raise_for_status()
        return response.json()

    async def embed(self, model: str, text: str) -> list[float]:
        payload = {
            "model": model,
            "prompt": text,
        }

        response = await self._http_client.post(f"{self._base_url}/api/embeddings", json=payload)
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
