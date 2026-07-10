from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import (
    _conversation_context_error,
    _enforce_chat_request_limits,
    _enforce_filter_values_limit,
    _enforce_rag_request_limits,
    _limits_snapshot,
    create_app,
)
from app.models.chat import ChatRequest, RagChatRequest


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


def test_health_live_returns_ok() -> None:
    client = TestClient(main_module.app)

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_limits_snapshot_contains_request_limits() -> None:
    limits = _limits_snapshot()

    assert limits["max_chat_message_chars"] > 0
    assert limits["max_rag_top_k"] > 0
    assert limits["max_filter_values"] > 0
    assert limits["max_filter_value_chars"] > 0


def test_chat_request_limit_rejects_oversized_message() -> None:
    request = ChatRequest(message="x" * 8001)

    try:
        _enforce_chat_request_limits(request)
    except HTTPException as exc:
        assert exc.status_code == 413
    else:
        raise AssertionError("expected HTTPException")


def test_rag_request_limit_rejects_top_k_above_configured_limit(monkeypatch) -> None:
    monkeypatch.setattr(main_module.settings, "max_rag_top_k", 10)
    request = RagChatRequest(message="ok", top_k=20)

    try:
        _enforce_rag_request_limits(request)
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("expected HTTPException")


def test_filter_values_limit_rejects_too_many_values() -> None:
    try:
        _enforce_filter_values_limit(
            field_name="features",
            values=[str(index) for index in range(51)],
        )
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("expected HTTPException")
