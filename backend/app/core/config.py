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
    rag_top_k: int = 5
    rag_score_threshold: float | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
