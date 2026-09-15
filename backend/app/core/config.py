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
    # Signed BFF→backend identity (must match bff service JWT settings).
    service_jwt_secret: str = "taskflow-bff-service-jwt-dev-secret"
    service_jwt_issuer: str = "taskflow-bff"
    service_jwt_audience: str = "taskflow-backend"
    # E3.2 Text-to-SQL / readonly SQL tools
    sql_tool_enabled: bool = True
    sql_tool_row_limit: int = 200
    sql_tool_timeout_seconds: float = 10.0
    # Preferred Ollama tag for LoRA adapter (create via Modelfile); falls back if missing.
    text_to_sql_model: str = "qwen2_5_coder_7b_v5_projection_steps400"
    text_to_sql_fallback_model: str = "qwen2.5-coder:7b"
    # Comma-separated override; empty → DEFAULT_SQL_TOOL_ALLOWED_TABLES
    sql_tool_allowed_tables: str = ""
    agent_max_steps: int = 4
    agent_default_model: str = ""
    # E6 lab: LangGraph adapter beside handwritten AgentOrchestrator (default off).
    agent_langgraph_enabled: bool = False
    # E4: readonly DSN for synthetic external demo DB (n8n sync source).
    external_postgres_dsn: str = (
        "postgresql+asyncpg://external_user:external_password@localhost:5433/external_demo"
    )
    integrations_default_bucket_name: str = "n8n Integrations"
    # E5: durable indexing via Kafka/Redpanda. When false → FastAPI BackgroundTasks.
    kafka_enabled: bool = False
    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_indexing_topic: str = "taskflow.indexing.requested"
    kafka_document_events_topic: str = "taskflow.document.events"
    kafka_consumer_group: str = "taskflow-indexing-workers"
    # Local Qdrant server may lag client package; silence noisy mismatch warning.
    qdrant_check_compatibility: bool = False
    # E7: MinIO / S3-compatible object storage for uploads (default = local FS).
    object_storage_enabled: bool = False
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_access_key: str = "minioadmin"
    object_storage_secret_key: str = "minioadmin"
    object_storage_bucket: str = "taskflow-uploads"
    object_storage_region: str = "us-east-1"
    # E7: indexing worker health HTTP (compose deploy profile).
    indexing_worker_health_host: str = "0.0.0.0"
    indexing_worker_health_port: int = 8002
    # E7: in-process Prometheus-style metrics (/metrics, /metrics/summary).
    metrics_enabled: bool = True
    # E2.1: OpenAI-compatible external generation (Gemini AI Studio + OpenRouter).
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_default_model: str = "gemini-3.6-flash"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = "openai/gpt-4o-mini"
    openrouter_http_referer: str = "http://localhost:5173"
    openrouter_app_title: str = "TaskFlow AI"
    external_request_timeout_seconds: float = 60.0

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
        "sql_tool_row_limit",
        "sql_tool_timeout_seconds",
        "agent_max_steps",
        "external_request_timeout_seconds",
    )
    @classmethod
    def _positive_number(cls, value: int | float) -> int | float:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator(
        "ollama_base_url",
        "qdrant_url",
        "gemini_base_url",
        "openrouter_base_url",
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
        "text_to_sql_model",
        "text_to_sql_fallback_model",
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
