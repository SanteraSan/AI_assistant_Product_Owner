from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TaskFlow AI BFF"
    keycloak_issuer: str = "http://localhost:8080/realms/taskflow"
    keycloak_client_id: str = "taskflow-bff"
    keycloak_client_secret: str = "taskflow-bff-dev-secret"
    bff_public_base_url: str = "http://localhost:8001"
    bff_callback_path: str = "/auth/callback"
    frontend_base_url: str = "http://localhost:5173"
    backend_base_url: str = "http://localhost:8000"
    redis_url: str = "redis://localhost:6379/1"
    session_cookie_name: str = "taskflow_session"
    session_ttl_seconds: int = 28800
    service_jwt_secret: str = "taskflow-bff-service-jwt-dev-secret"
    service_jwt_issuer: str = "taskflow-bff"
    service_jwt_audience: str = "taskflow-backend"
    service_jwt_ttl_seconds: int = 60
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    request_timeout_seconds: float = 30.0

    @field_validator("cookie_samesite")
    @classmethod
    def _normalize_samesite(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("cookie_samesite must be lax, strict, or none")
        return normalized

    @property
    def callback_url(self) -> str:
        return f"{self.bff_public_base_url.rstrip('/')}{self.bff_callback_path}"

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.keycloak_issuer.rstrip('/')}/protocol/openid-connect/auth"

    @property
    def token_endpoint(self) -> str:
        return f"{self.keycloak_issuer.rstrip('/')}/protocol/openid-connect/token"

    @property
    def end_session_endpoint(self) -> str:
        return f"{self.keycloak_issuer.rstrip('/')}/protocol/openid-connect/logout"

    @property
    def userinfo_endpoint(self) -> str:
        return f"{self.keycloak_issuer.rstrip('/')}/protocol/openid-connect/userinfo"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
