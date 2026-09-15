from app.core.model_pricing import estimate_cost_usd


def test_estimate_cost_usd_uses_manual_table() -> None:
    cost = estimate_cost_usd(
        provider="gemini",
        model="gemini-2.5-flash",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    )
    assert cost == 0.75


def test_estimate_cost_usd_unknown_model_is_none_not_zero() -> None:
    assert (
        estimate_cost_usd(
            provider="gemini",
            model="unknown-model",
            prompt_tokens=10,
            completion_tokens=10,
        )
        is None
    )
    assert (
        estimate_cost_usd(
            provider="ollama",
            model="qwen3.5:9b",
            prompt_tokens=10,
            completion_tokens=10,
        )
        is None
    )
