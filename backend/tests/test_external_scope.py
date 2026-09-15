from app.core.errors import ErrorType, ProviderError
from app.models.chat import SourceChunk
from app.services.external_scope import (
    decide_external_scope,
    sources_include_non_synthetic,
)


def _chunk(*, synthetic: object | None) -> SourceChunk:
    metadata: dict[str, object] = {}
    if synthetic is not None:
        metadata["synthetic"] = synthetic
    return SourceChunk(
        id="c1",
        content="deal",
        metadata=metadata,
    )


def test_missing_synthetic_flag_is_non_synthetic() -> None:
    assert sources_include_non_synthetic([_chunk(synthetic=None)]) is True
    assert sources_include_non_synthetic([_chunk(synthetic="true")]) is True
    assert sources_include_non_synthetic([_chunk(synthetic=True)]) is False


def test_external_non_synthetic_is_denied_before_provider() -> None:
    called = {"n": 0}

    def fake_generate() -> None:
        called["n"] += 1

    try:
        decide_external_scope(
            approach="external",
            endpoint="rag",
            session_seen_non_synthetic_flag=False,
            retrieved_non_synthetic=True,
        )
    except ProviderError as exc:
        assert exc.error_type == ErrorType.EXTERNAL_SCOPE_NOT_SYNTHETIC
        assert exc.status_code == 403
        assert exc.extra["reason"] == "retrieved_non_synthetic"
    else:
        raise AssertionError("expected ProviderError")
    assert called["n"] == 0


def test_session_flag_blocks_external_with_session_memory_reason() -> None:
    try:
        decide_external_scope(
            approach="external",
            endpoint="rag",
            session_seen_non_synthetic_flag=True,
            retrieved_non_synthetic=False,
        )
    except ProviderError as exc:
        assert exc.error_type == ErrorType.EXTERNAL_SCOPE_NOT_SYNTHETIC
        assert exc.extra["reason"] == "session_memory"
    else:
        raise AssertionError("expected ProviderError")


def test_hybrid_rag_on_taskflow_disables_cloud_fallback() -> None:
    decision = decide_external_scope(
        approach="hybrid",
        endpoint="rag",
        session_seen_non_synthetic_flag=False,
        retrieved_non_synthetic=True,
    )
    assert decision.allow_external_fallback is False
    assert decision.allow_external_generation is False
    assert decision.persist_session_seen_non_synthetic is True


def test_hybrid_chat_never_allows_cloud_fallback() -> None:
    decision = decide_external_scope(
        approach="hybrid",
        endpoint="chat",
        session_seen_non_synthetic_flag=False,
        retrieved_non_synthetic=False,
    )
    assert decision.allow_external_fallback is False
    assert decision.allow_external_generation is False


def test_user_message_is_not_an_input_to_guard() -> None:
    decision = decide_external_scope(
        approach="external",
        endpoint="chat",
        session_seen_non_synthetic_flag=False,
        retrieved_non_synthetic=False,
    )
    assert decision.allow_external_generation is True
