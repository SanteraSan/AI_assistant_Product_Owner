import pytest

from app.core.config import Settings
from app.core.errors import ErrorType, ProviderError
from app.services.llm.catalog import DEFAULT_LOCAL_MODELS, ModelCatalog
from app.services.llm.types import normalize_approach


def test_normalize_approach_maps_openapi_alias() -> None:
    assert normalize_approach("openapi") == "external"
    assert normalize_approach("OpenAPI") == "external"
    assert normalize_approach(None) == "hybrid"
    assert normalize_approach("") == "hybrid"
    assert normalize_approach("local_only") == "local_only"


def test_local_only_rejects_gemini_id() -> None:
    catalog = ModelCatalog(gemini_configured=True)
    with pytest.raises(ProviderError) as exc:
        catalog.resolve_provider(model="gemini-2.5-flash", approach="local_only")
    assert exc.value.error_type == ErrorType.MODEL_UNAVAILABLE
    assert exc.value.status_code == 404


def test_external_requires_configured_key() -> None:
    catalog = ModelCatalog(gemini_configured=False)
    with pytest.raises(ProviderError) as exc:
        catalog.resolve_provider(model="gemini-2.5-flash", approach="external")
    assert exc.value.error_type == ErrorType.MODEL_UNAVAILABLE
    assert exc.value.status_code == 503


def test_external_unknown_model_is_unavailable() -> None:
    catalog = ModelCatalog(gemini_configured=True)
    with pytest.raises(ProviderError) as exc:
        catalog.resolve_provider(model="qwen3.5:9b", approach="external")
    assert exc.value.error_type == ErrorType.MODEL_UNAVAILABLE
    assert exc.value.status_code == 404


def test_external_resolves_current_flash_id() -> None:
    catalog = ModelCatalog(gemini_configured=True)
    assert catalog.resolve_provider(model="gemini-3.6-flash", approach="external") == "gemini"


def test_hybrid_keeps_local_model_on_ollama() -> None:
    catalog = ModelCatalog(gemini_configured=True)
    assert catalog.resolve_provider(model="qwen3.5:9b", approach="hybrid") == "ollama"


def test_health_catalog_hides_unconfigured_external_models() -> None:
    catalog = ModelCatalog(gemini_configured=False, openrouter_configured=False)
    providers = {entry.provider for entry in catalog.list_entries()}
    assert providers == {"ollama"}


def test_default_local_models_end_with_qwen38() -> None:
    assert DEFAULT_LOCAL_MODELS[-1] == "qwen3.8:latest"


def test_qwen38_resolves_to_ollama_without_a_custom_list() -> None:
    catalog = ModelCatalog()
    assert catalog.resolve_provider(model="qwen3.8:latest", approach="local_only") == "ollama"
    assert catalog.resolve_provider(model="qwen3.8:latest", approach="hybrid") == "ollama"


def test_external_qwen38_is_unavailable_even_with_client_key() -> None:
    catalog = ModelCatalog(gemini_configured=True)
    with pytest.raises(ProviderError) as exc:
        catalog.resolve_provider(
            model="qwen3.8:latest",
            approach="external",
            client_key_supplied=True,
        )
    assert exc.value.error_type == ErrorType.MODEL_UNAVAILABLE
    assert exc.value.status_code == 404


def test_settings_keep_catalog_model_defaults() -> None:
    settings = Settings()
    assert settings.default_model == "qwen2.5:0.5b"
    assert settings.default_rag_model == "gemma3:12b"
    assert settings.agent_default_model == ""
