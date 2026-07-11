from datetime import UTC, datetime
from types import SimpleNamespace

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


def test_chat_sessions_endpoint_returns_user_sessions(monkeypatch) -> None:
    timestamp = datetime(2026, 7, 12, 3, 15, tzinfo=UTC)

    class _FakeChatHistoryService:
        async def list_sessions(self, *, tenant_id: str, user_id: str | None, limit: int = 50):
            assert tenant_id == "local_demo"
            assert user_id == "local-user-1"
            assert limit == 50
            return [
                SimpleNamespace(
                    id="session-1",
                    title="Тестовый чат",
                    tenant_id=tenant_id,
                    owner_user_id=user_id,
                    active_bucket_id="bucket-1",
                    model_id="qwen3.5:9b",
                    approach="hybrid",
                    metadata_json={},
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            ]

    monkeypatch.setattr(main_module, "chat_history_service", _FakeChatHistoryService())
    client = TestClient(main_module.app)

    response = client.get(
        "/chat/sessions",
        headers={"X-Tenant-ID": "local_demo", "X-User-ID": "local-user-1"},
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == "session-1"
    assert response.json()[0]["active_bucket_id"] == "bucket-1"


def test_chat_messages_endpoint_returns_session_messages(monkeypatch) -> None:
    timestamp = datetime(2026, 7, 12, 3, 15, tzinfo=UTC)

    class _FakeChatHistoryService:
        async def list_messages(self, *, tenant_id: str, user_id: str | None, session_id: str):
            assert tenant_id == "local_demo"
            assert user_id == "local-user-1"
            assert session_id == "session-1"
            return [
                SimpleNamespace(
                    id="message-1",
                    session_id=session_id,
                    role="assistant",
                    content="Ответ из истории",
                    model="qwen3.5:9b",
                    provider="ollama",
                    latency_ms=100,
                    metadata_json={"sources": []},
                    created_at=timestamp,
                )
            ]

    monkeypatch.setattr(main_module, "chat_history_service", _FakeChatHistoryService())
    client = TestClient(main_module.app)

    response = client.get(
        "/chat/sessions/session-1/messages",
        headers={"X-Tenant-ID": "local_demo", "X-User-ID": "local-user-1"},
    )

    assert response.status_code == 200
    assert response.json()[0]["content"] == "Ответ из истории"


def test_update_chat_session_endpoint_persists_context(monkeypatch) -> None:
    timestamp = datetime(2026, 7, 12, 3, 15, tzinfo=UTC)

    class _FakeChatHistoryService:
        async def update_session(
            self,
            *,
            tenant_id: str,
            user_id: str | None,
            session_id: str,
            title: str | None = None,
            active_bucket_id: str | None = None,
            model_id: str | None = None,
            approach: str | None = None,
            metadata: dict[str, object] | None = None,
        ):
            assert tenant_id == "local_demo"
            assert user_id == "local-user-1"
            assert session_id == "session-1"
            assert active_bucket_id == ""
            assert model_id == "qwen3.5:9b"
            assert approach == "hybrid"
            return SimpleNamespace(
                id=session_id,
                title=title or "Тестовый чат",
                tenant_id=tenant_id,
                owner_user_id=user_id,
                active_bucket_id=None,
                model_id=model_id,
                approach=approach,
                metadata_json=metadata or {},
                created_at=timestamp,
                updated_at=timestamp,
            )

    monkeypatch.setattr(main_module, "chat_history_service", _FakeChatHistoryService())
    client = TestClient(main_module.app)

    response = client.patch(
        "/chat/sessions/session-1",
        headers={"X-Tenant-ID": "local_demo", "X-User-ID": "local-user-1"},
        json={
            "active_bucket_id": "",
            "model_id": "qwen3.5:9b",
            "approach": "hybrid",
        },
    )

    assert response.status_code == 200
    assert response.json()["active_bucket_id"] is None
    assert response.json()["model_id"] == "qwen3.5:9b"


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
