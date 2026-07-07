from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _new_uuid() -> str:
    return str(uuid4())


class RagRequestLog(Base):
    __tablename__ = "rag_request_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    message: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(64), default="ollama")
    latency_ms: Mapped[int] = mapped_column(Integer)
    collection: Mapped[str] = mapped_column(String(255))
    score_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    features: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    diversity: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    retrieval: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    query_hints: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    context_policy: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    prompt_tokens_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    sources: Mapped[list["RagSourceLog"]] = relationship(
        back_populates="request_log",
        cascade="all, delete-orphan",
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
        unique=True,
    )
    summary: Mapped[str] = mapped_column(Text)
    message_count_at_update: Mapped[int] = mapped_column(Integer, default=0)
    features: Mapped[list[str]] = mapped_column(JSONB, default=list)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255))
    checklist_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    models: Mapped[list[str]] = mapped_column(JSONB, default=list)
    scenario_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="running")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    results: Mapped[list["EvaluationResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        index=True,
    )
    scenario_id: Mapped[str] = mapped_column(String(64))
    scenario_name: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    sources: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    retrieval: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    query_hints: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    context_policy: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    quality_flags: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    run: Mapped[EvaluationRun] = relationship(back_populates="results")


class RagSourceLog(Base):
    __tablename__ = "rag_source_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    request_log_id: Mapped[str] = mapped_column(
        ForeignKey("rag_request_logs.id", ondelete="CASCADE"),
        index=True,
    )
    source_index: Mapped[int] = mapped_column(Integer)
    qdrant_point_id: Mapped[str] = mapped_column(String(255))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature: Mapped[list[str]] = mapped_column(JSONB, default=list)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    content_excerpt: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    request_log: Mapped[RagRequestLog] = relationship(back_populates="sources")
