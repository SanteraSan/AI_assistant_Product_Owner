from typing import Any

from pydantic import BaseModel, Field


class ChatSessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    active_bucket_id: str | None = Field(default=None, max_length=36)
    model_id: str | None = Field(default=None, max_length=255)
    approach: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatSessionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    active_bucket_id: str | None = Field(default=None, max_length=36)
    model_id: str | None = Field(default=None, max_length=255)
    approach: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] | None = None


class ChatSessionResponse(BaseModel):
    id: str
    title: str
    tenant_id: str | None = None
    owner_user_id: str | None = None
    active_bucket_id: str | None = None
    model_id: str | None = None
    approach: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    model: str | None = None
    provider: str | None = None
    latency_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ChatAttachmentCreateRequest(BaseModel):
    document_id: str = Field(..., min_length=1, max_length=36)
    file_name: str = Field(..., min_length=1, max_length=512)
    source_type: str = Field(..., min_length=1, max_length=64)
    status: str = Field(default="indexing", min_length=1, max_length=32)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    model: str | None = None
    session_id: str | None = Field(default=None, min_length=1, max_length=36)


class ChatResponse(BaseModel):
    model: str
    response: str
    latency_ms: int
    provider: str = "ollama"
    session_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None


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
    session_id: str | None = Field(default=None, min_length=1, max_length=36)
    approach: str | None = Field(default=None, max_length=64)
    active_bucket_id: str | None = Field(default=None, max_length=36)
    top_k: int | None = Field(default=None, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    tenant_id: str | None = Field(default=None, min_length=1)
    bucket_ids: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)
    max_sources_per_title: int | None = Field(default=None, ge=1, le=10)
    max_sources_per_source_type: int | None = Field(default=None, ge=1, le=10)
    max_sources_per_source_path: int | None = Field(default=None, ge=1, le=10)


class RagChatResponse(ChatResponse):
    collection: str
    sources: list[SourceChunk]
    score_threshold: float | None = None
    features: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    diversity: dict[str, int | None] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    query_hints: dict[str, Any] = Field(default_factory=dict)
    context_policy: dict[str, Any] = Field(default_factory=dict)
    conversation_context: dict[str, Any] = Field(default_factory=dict)
    prompt_tokens_estimate: int | None = None
