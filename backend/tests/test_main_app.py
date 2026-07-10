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


def test_request_id_header_is_returned() -> None:
    client = TestClient(main_module.app)

    response = client.get("/health/live", headers={"X-Request-ID": "test-request-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"


def test_oversized_chat_request_returns_traceable_error() -> None:
    client = TestClient(main_module.app)

    response = client.post(
        "/chat",
        headers={"X-Request-ID": "limit-test"},
        json={"message": "x" * 8001},
    )

    assert response.status_code == 413
    assert response.headers["X-Request-ID"] == "limit-test"
    assert response.json()["error_type"] == "http_error"
    assert response.json()["request_id"] == "limit-test"


def test_validation_error_returns_traceable_error() -> None:
    client = TestClient(main_module.app)

    response = client.post(
        "/rag/chat",
        headers={"X-Request-ID": "validation-test"},
        json={"message": "ok", "top_k": 0},
    )

    assert response.status_code == 422
    assert response.headers["X-Request-ID"] == "validation-test"
    assert response.json()["error_type"] == "validation_error"
    assert response.json()["request_id"] == "validation-test"


def test_limits_snapshot_contains_request_limits() -> None:
    limits = _limits_snapshot()

    assert limits["max_chat_message_chars"] > 0
    assert limits["max_rag_top_k"] > 0
    assert limits["max_filter_values"] > 0
    assert limits["max_filter_value_chars"] > 0
    assert limits["rate_limit_requests"] > 0
    assert limits["ollama_max_concurrency"] > 0


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
