from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    model: str | None = None


class ChatResponse(BaseModel):
    model: str
    response: str
    latency_ms: int
    provider: str = "ollama"


class SourceChunk(BaseModel):
    id: str
    score: float | None = None
    title: str | None = None
    source_type: str | None = None
    source_path: str | None = None
    feature: list[str] = Field(default_factory=list)
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    model: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    features: list[str] = Field(default_factory=list)


class RagChatResponse(ChatResponse):
    collection: str
    sources: list[SourceChunk]
    score_threshold: float | None = None
    features: list[str] = Field(default_factory=list)
    prompt_tokens_estimate: int | None = None
