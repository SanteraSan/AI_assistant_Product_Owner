from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class OllamaOverloadedError(RuntimeError):
    def __init__(self, *, model: str, operation: str, timeout_seconds: float) -> None:
        self.model = model
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Ollama {operation} queue timed out for model {model} "
            f"after {timeout_seconds} seconds."
        )


class OllamaLoadGuard:
    def __init__(self, *, max_concurrency: int, timeout_seconds: float) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout_seconds = timeout_seconds

    @asynccontextmanager
    async def slot(self, *, model: str, operation: str) -> AsyncIterator[None]:
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise OllamaOverloadedError(
                model=model,
                operation=operation,
                timeout_seconds=self._timeout_seconds,
            ) from exc

        try:
            yield
        finally:
            self._semaphore.release()
