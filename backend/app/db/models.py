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
