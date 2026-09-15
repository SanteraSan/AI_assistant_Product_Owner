from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import (
    _bucket_file_inventory_response,
    _conversation_context_error,
    _document_ids,
    _effective_bucket_ids,
    _enforce_chat_request_limits,
    _enforce_filter_values_limit,
    _enforce_rag_request_limits,
    _limits_snapshot,
    _looks_like_bucket_file_inventory_question,
    _looks_like_targeted_image_reanalysis,
    _targeted_image_point_id,
    create_app,
)
from app.models.chat import ChatRequest, RagChatRequest, RagChatResponse, SourceChunk
from app.services.llm.types import GenerationResult
from tests.auth_helpers import auth_headers


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
        headers={**auth_headers(), "X-Request-ID": "limit-test"},
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
        headers={**auth_headers(), "X-Request-ID": "validation-test"},
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
        headers=auth_headers(),
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
        headers=auth_headers(),
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
        headers=auth_headers(),
        json={
            "active_bucket_id": "",
            "model_id": "qwen3.5:9b",
            "approach": "hybrid",
        },
    )

    assert response.status_code == 200
    assert response.json()["active_bucket_id"] is None
    assert response.json()["model_id"] == "qwen3.5:9b"


def test_create_chat_attachment_message_endpoint(monkeypatch) -> None:
    timestamp = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)

    class _FakeChatHistoryService:
        async def save_attachment_message(
            self,
            *,
            tenant_id: str,
            user_id: str | None,
            session_id: str | None,
            document_id: str,
            file_name: str,
            source_type: str,
            status: str,
            active_bucket_id: str | None = None,
            model_id: str | None = None,
            approach: str | None = None,
        ):
            assert tenant_id == "local_demo"
            assert user_id == "local-user-1"
            assert session_id == "session-1"
            assert document_id == "doc-1"
            assert file_name == "diagram.png"
            assert source_type == "image"
            assert status == "indexing"
            return SimpleNamespace(
                id="attachment-message-1",
                session_id=session_id,
                role="user",
                content="Прикреплён файл: diagram.png",
                model=None,
                provider=None,
                latency_ms=None,
                metadata_json={
                    "attachments": [
                        {
                            "id": document_id,
                            "file_name": file_name,
                            "source_type": source_type,
                            "status": status,
                        }
                    ]
                },
                created_at=timestamp,
            )

    monkeypatch.setattr(main_module, "chat_history_service", _FakeChatHistoryService())
    client = TestClient(main_module.app)

    response = client.post(
        "/chat/sessions/session-1/attachments",
        headers=auth_headers(),
        json={
            "document_id": "doc-1",
            "file_name": "diagram.png",
            "source_type": "image",
            "status": "indexing",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == "Прикреплён файл: diagram.png"
    assert body["metadata"]["attachments"][0]["id"] == "doc-1"


def test_create_chat_attachment_message_endpoint_returns_404(monkeypatch) -> None:
    class _FakeChatHistoryService:
        async def save_attachment_message(self, **_kwargs):
            return None

    monkeypatch.setattr(main_module, "chat_history_service", _FakeChatHistoryService())
    client = TestClient(main_module.app)

    response = client.post(
        "/chat/sessions/session-1/attachments",
        headers=auth_headers(),
        json={
            "document_id": "doc-1",
            "file_name": "diagram.png",
            "source_type": "image",
            "status": "indexing",
        },
    )

    assert response.status_code == 404


def test_delete_chat_session_endpoint(monkeypatch) -> None:
    class _FakeChatHistoryService:
        async def delete_session(self, *, tenant_id: str, user_id: str | None, session_id: str):
            assert tenant_id == "local_demo"
            assert user_id == "local-user-1"
            assert session_id == "session-1"
            return True

    monkeypatch.setattr(main_module, "chat_history_service", _FakeChatHistoryService())
    client = TestClient(main_module.app)

    response = client.delete(
        "/chat/sessions/session-1",
        headers=auth_headers(),
    )

    assert response.status_code == 204



def test_bucket_file_inventory_helpers_use_selected_bucket_context() -> None:
    request = RagChatRequest(
        message="Какие файлы есть в бакете?",
        active_bucket_id="bucket-1",
        bucket_ids=["bucket-1"],
    )
    documents = [
        SimpleNamespace(id="doc-1", file_name="diagramms.xlsx", status="indexed"),
        SimpleNamespace(id="doc-2", file_name="draft.txt", status="index_failed"),
    ]

    assert _effective_bucket_ids(request) == ["bucket-1"]
    assert _looks_like_bucket_file_inventory_question(request.message)
    assert _document_ids(documents) == ["doc-1"]

    response = _bucket_file_inventory_response(
        message=request.message,
        model="qwen3.5:9b",
        bucket_ids=["bucket-1"],
        documents=documents,
        latency_ms=1,
    )

    assert "diagramms.xlsx" in response.response
    assert response.sources[0].source_type == "bucket_metadata"


def test_targeted_image_reanalysis_intent_and_point_id_are_stable() -> None:
    assert _looks_like_targeted_image_reanalysis("Повторно проанализируй картинку: какого цвета ствол?")
    assert _looks_like_targeted_image_reanalysis("Какого цвета ствол у дерева?")
    assert not _looks_like_targeted_image_reanalysis("Суммируй историю чата")

    first = _targeted_image_point_id(
        document_id="doc-1",
        bucket_id="__personal__",
        question="Какого цвета ствол у дерева?",
        vision_model="gemma4:12b",
    )
    second = _targeted_image_point_id(
        document_id="doc-1",
        bucket_id="__personal__",
        question="  какого   цвета ствол у дерева? ",
        vision_model="gemma4:12b",
    )

    assert first == second


def test_rag_chat_passes_targeted_image_source_to_rag(monkeypatch) -> None:
    captured: dict[str, object] = {}
    targeted_source = SourceChunk(
        id="targeted-source-1",
        score=None,
        title="images.jpeg - targeted image analysis",
        source_type="image_targeted_digest",
        source_path="/tmp/images.jpeg",
        content="Focused question: Какого цвета ствол?\nTargeted vision digest:\nСтвол коричневый.",
        metadata={"document_metadata": {"document_asset_id": "doc-1"}},
    )

    async def _fake_build_context(*, session_id: str | None, message: str):
        return {
            "retrieval_query": message,
            "prompt_memory": {"used": False},
        }

    async def _fake_build_targeted_image_sources(**kwargs):
        captured["targeted_kwargs"] = kwargs
        return [targeted_source]

    class _FakeRagService:
        async def answer(self, **kwargs):
            captured["rag_kwargs"] = kwargs
            return RagChatResponse(
                model="qwen3.5:9b",
                response="Ствол дерева коричневый.",
                latency_ms=1,
                collection="documents",
                sources=kwargs["additional_sources"],
                retrieval={
                    "additional_source_count": len(kwargs["additional_sources"]),
                },
            )

    async def _fake_save_exchange(**_kwargs):
        return None

    class _FakeRagLogService:
        async def log_response(self, **_kwargs):
            return None

    monkeypatch.setattr(main_module, "_qdrant_collection_exists", lambda: True)
    monkeypatch.setattr(main_module, "_build_conversation_context", _fake_build_context)
    monkeypatch.setattr(main_module, "_build_targeted_image_sources", _fake_build_targeted_image_sources)
    monkeypatch.setattr(main_module, "rag_service", _FakeRagService())
    monkeypatch.setattr(main_module, "_try_save_chat_exchange", _fake_save_exchange)
    monkeypatch.setattr(main_module, "rag_log_service", _FakeRagLogService())

    async def _fake_resolve_rag_document_ids(**kwargs):
        return list(kwargs.get("requested_document_ids") or [])

    monkeypatch.setattr(main_module, "resolve_rag_document_ids", _fake_resolve_rag_document_ids)

    async def _fake_accessible_documents_for_rag(**_kwargs):
        return [
            SimpleNamespace(
                id="doc-1",
                file_name="images.jpeg",
                title="images.jpeg",
                status="indexed",
                source_path="/tmp/images.jpeg",
            )
        ]

    monkeypatch.setattr(
        main_module,
        "_accessible_documents_for_rag",
        _fake_accessible_documents_for_rag,
    )
    client = TestClient(main_module.app)

    response = client.post(
        "/rag/chat",
        headers=auth_headers(),
        json={
            "message": "Повторно проанализируй картинку: какого цвета ствол?",
            "document_ids": ["doc-1"],
        },
    )

    assert response.status_code == 200
    assert response.json()["sources"][0]["source_type"] == "image_targeted_digest"
    assert captured["targeted_kwargs"]["document_ids"] == ["doc-1"]
    assert captured["rag_kwargs"]["additional_sources"] == [targeted_source]


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


def test_health_snapshot_exposes_external_key_flags() -> None:
    snapshot = main_module.model_gateway.health_snapshot()

    assert "gemini_key_configured" in snapshot
    assert "openrouter_key_configured" in snapshot
    assert isinstance(snapshot["models"], list)


def test_chat_sends_approach_to_gateway_without_cloud_fallback(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeGateway:
        async def generate(self, **kwargs):
            captured.update(kwargs)
            return GenerationResult(
                response="local-ok",
                model=str(kwargs["model"]),
                provider="ollama",
            )

    async def _no_seen(**_kwargs):
        return False

    async def _no_save(**_kwargs):
        return None

    monkeypatch.setattr(main_module, "model_gateway", _FakeGateway())
    monkeypatch.setattr(main_module, "_session_seen_non_synthetic_flag", _no_seen)
    monkeypatch.setattr(main_module, "_try_save_chat_exchange", _no_save)
    client = TestClient(main_module.app)

    response = client.post(
        "/chat",
        headers=auth_headers(),
        json={"message": "hello", "approach": "hybrid", "model": "qwen3.5:9b"},
    )

    assert response.status_code == 200
    assert response.json()["response"] == "local-ok"
    assert captured["endpoint"] == "chat"
    assert captured["allow_external_fallback"] is False
    assert captured["approach"] == "hybrid"


def test_chat_external_blocked_by_session_flag(monkeypatch) -> None:
    called = {"n": 0}

    class _FakeGateway:
        async def generate(self, **_kwargs):
            called["n"] += 1
            raise AssertionError("gateway must not be called")

    async def _seen(**_kwargs):
        return True

    monkeypatch.setattr(main_module, "model_gateway", _FakeGateway())
    monkeypatch.setattr(main_module, "_session_seen_non_synthetic_flag", _seen)
    client = TestClient(main_module.app)

    response = client.post(
        "/chat",
        headers=auth_headers(),
        json={"message": "hello", "approach": "external", "model": "gemini-2.5-flash"},
    )

    assert response.status_code == 403
    assert response.json()["error_type"] == "external_scope_not_synthetic"
    assert response.json()["reason"] == "session_memory"
    assert called["n"] == 0


def test_agent_external_returns_explicit_error() -> None:
    client = TestClient(main_module.app)

    response = client.post(
        "/agent/chat",
        headers=auth_headers(),
        json={"message": "hello", "approach": "openapi"},
    )

    assert response.status_code == 400
    assert response.json()["error_type"] == "external_agent_not_supported"

