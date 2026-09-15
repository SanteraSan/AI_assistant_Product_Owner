from enum import StrEnum


class ErrorType(StrEnum):
    HTTP_ERROR = "http_error"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"
    OLLAMA_OVERLOADED = "ollama_overloaded"
    EXTERNAL_PROVIDER_RATE_LIMITED = "external_provider_rate_limited"
    EXTERNAL_PROVIDER_UNAVAILABLE = "external_provider_unavailable"
    EXTERNAL_PROVIDER_ERROR = "external_provider_error"
    MODEL_UNAVAILABLE = "model_unavailable"
    PROVIDER_INVALID_RESPONSE = "provider_invalid_response"
    EXTERNAL_SCOPE_NOT_SYNTHETIC = "external_scope_not_synthetic"
    EXTERNAL_AGENT_NOT_SUPPORTED = "external_agent_not_supported"


class ProviderError(Exception):
    def __init__(
        self,
        error_type: ErrorType,
        detail: str,
        *,
        status_code: int,
        extra: dict[str, object] | None = None,
    ) -> None:
        super().__init__(detail)
        self.error_type = error_type
        self.detail = detail
        self.status_code = status_code
        self.extra = extra or {}
