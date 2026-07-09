from functools import lru_cache
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
    conversation_summary_strategy: str = "hybrid"
    conversation_summary_model: str = "gemma4:12b"
    conversation_summary_temperature: float = 0.0
    conversation_memory_enabled: bool = True
    conversation_memory_token_budget: int = 350
    conversation_memory_recent_messages: int = 4

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
