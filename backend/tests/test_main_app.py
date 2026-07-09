from fastapi import FastAPI

from app.main import _conversation_context_error, create_app


def test_create_app_returns_fastapi_instance() -> None:
    app = create_app()

    assert isinstance(app, FastAPI)


def test_conversation_context_error_contains_expected_defaults() -> None:
    context = _conversation_context_error(message="Что с notifications?")

    assert context["used"] is False
    assert context["mode"] == "error"
    assert context["retrieval_query"] == "Что с notifications?"
    assert context["summary_validation_error"] == "conversation_context_build_failed"
    assert context["prompt_memory"]["used"] is False
    assert "notifications" in context["current_features"]
