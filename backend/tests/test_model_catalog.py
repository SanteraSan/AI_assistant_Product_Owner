import pytest

from app.core.errors import ErrorType, ProviderError
from app.services.llm.catalog import ModelCatalog
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
