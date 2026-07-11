from functools import lru_cache
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TaskFlow AI Assistant API"
    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "qwen2.5:0.5b"
    default_rag_model: str = "gemma3:12b"
    embedding_model: str = "nomic-embed-text"
    request_timeout_seconds: float = 120.0
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "documents"
    postgres_dsn: str = "postgresql+asyncpg://po_user:po_password@localhost:5432/po_assistant"
    database_auto_create_tables: bool = True
    raw_data_dir: str = "../data/raw"
    default_tenant_id: str = "local_demo"
    default_bucket_id: str = "taskflow_seed"
    rag_top_k: int = 5
    rag_score_threshold: float | None = 0.68
    rag_candidate_multiplier: int = 3
    rag_generation_keep_alive: str = "10m"
    rag_generation_temperature: float = 0.1
    rag_generation_top_p: float = 0.9
    excel_supplement_scroll_limit: int = 1000
    docx_supplement_scroll_limit: int = 1000
    image_vision_enabled: bool = True
    image_vision_model: str = "gemma4:12b"
    conversation_summary_strategy: str = "hybrid"
    conversation_summary_model: str = "gemma4:12b"
    conversation_summary_temperature: float = 0.0
    conversation_memory_enabled: bool = True
    conversation_memory_token_budget: int = 350
    conversation_memory_recent_messages: int = 4
    max_chat_message_chars: int = 8000
    max_rag_top_k: int = 20
    max_filter_values: int = 50
    max_filter_value_chars: int = 512
    redis_enabled: bool = True
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    rate_limit_fail_open: bool = True
    ollama_max_concurrency: int = 2
    ollama_queue_timeout_seconds: float = 5.0
    cors_allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("rag_score_threshold", mode="before")
    @classmethod
    def _empty_score_threshold(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator(
        "request_timeout_seconds",
        "rag_top_k",
        "rag_candidate_multiplier",
        "excel_supplement_scroll_limit",
        "docx_supplement_scroll_limit",
        "conversation_memory_token_budget",
        "conversation_memory_recent_messages",
        "max_chat_message_chars",
        "max_rag_top_k",
        "max_filter_values",
        "max_filter_value_chars",
        "rate_limit_requests",
        "rate_limit_window_seconds",
        "ollama_max_concurrency",
        "ollama_queue_timeout_seconds",
    )
    @classmethod
    def _positive_number(cls, value: int | float) -> int | float:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator(
        "ollama_base_url",
        "qdrant_url",
    )
    @classmethod
    def _http_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return normalized.rstrip("/")

    @field_validator("redis_url")
    @classmethod
    def _redis_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith(("redis://", "rediss://")):
            raise ValueError("must start with redis:// or rediss://")
        return normalized

    @field_validator(
        "default_model",
        "default_rag_model",
        "embedding_model",
        "qdrant_collection",
        "postgres_dsn",
        "default_tenant_id",
        "default_bucket_id",
    )
    @classmethod
    def _non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("rag_score_threshold")
    @classmethod
    def _score_threshold_range(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not 0.0 <= value <= 1.0:
            raise ValueError("must be between 0.0 and 1.0")
        return value

    @field_validator(
        "rag_generation_temperature",
        "rag_generation_top_p",
    )
    @classmethod
    def _generation_option_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("must be between 0.0 and 1.0")
        return value

    @model_validator(mode="after")
    def _validate_cross_field_limits(self) -> "Settings":
        if self.rag_top_k > self.max_rag_top_k:
            raise ValueError("rag_top_k must not exceed max_rag_top_k")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
