"""Manual USD prices per 1M tokens. Missing model → None, never 0."""

from __future__ import annotations

# provider -> model -> {input, output} USD / 1M tokens
MODEL_PRICES_USD_PER_MILLION: dict[str, dict[str, dict[str, float]]] = {
    "gemini": {
        "gemini-3.6-flash": {"input": 0.15, "output": 0.60},
        "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    },
    "openrouter": {
        "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
    },
    "ollama": {},
}


def estimate_cost_usd(
    *,
    provider: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    prices = MODEL_PRICES_USD_PER_MILLION.get(provider, {}).get(model)
    if prices is None:
        return None
    prompt = prompt_tokens or 0
    completion = completion_tokens or 0
    return (prompt * prices["input"] + completion * prices["output"]) / 1_000_000
