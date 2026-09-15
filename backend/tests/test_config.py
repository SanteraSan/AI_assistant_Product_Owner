import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_accepts_empty_score_threshold_as_disabled() -> None:
    settings = Settings(rag_score_threshold="")

    assert settings.rag_score_threshold is None


def test_settings_rejects_invalid_urls() -> None:
    with pytest.raises(ValidationError):
        Settings(ollama_base_url="localhost:11434")


def test_settings_rejects_invalid_gemini_url() -> None:
    with pytest.raises(ValidationError):
        Settings(gemini_base_url="generativelanguage.googleapis.com")


def test_settings_rejects_invalid_redis_url() -> None:
    with pytest.raises(ValidationError):
        Settings(redis_url="localhost:6379")


def test_settings_rejects_rag_top_k_above_configured_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(rag_top_k=21, max_rag_top_k=20)
