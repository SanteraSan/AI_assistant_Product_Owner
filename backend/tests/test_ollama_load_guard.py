import asyncio

import pytest

from app.services.ollama_load_guard import OllamaLoadGuard, OllamaOverloadedError


def test_ollama_load_guard_times_out_when_concurrency_is_full() -> None:
    guard = OllamaLoadGuard(max_concurrency=1, timeout_seconds=0.01)

    async def run() -> None:
        async with guard.slot(model="qwen", operation="generate"):
            with pytest.raises(OllamaOverloadedError):
                async with guard.slot(model="qwen", operation="generate"):
                    pass

    asyncio.run(run())
