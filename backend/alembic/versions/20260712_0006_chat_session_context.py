"""add chat session context fields

Revision ID: 20260712_0006
Revises: 20260711_0005
Create Date: 2026-07-12 03:12:00+05:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260712_0006"
down_revision: str | None = "20260711_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("tenant_id", sa.String(length=255), nullable=True))
    op.add_column("chat_sessions", sa.Column("owner_user_id", sa.String(length=255), nullable=True))
    op.add_column("chat_sessions", sa.Column("active_bucket_id", sa.String(length=36), nullable=True))
    op.add_column("chat_sessions", sa.Column("model_id", sa.String(length=255), nullable=True))
    op.add_column("chat_sessions", sa.Column("approach", sa.String(length=64), nullable=True))
    op.add_column(
        "chat_sessions",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_chat_sessions_tenant_id"), "chat_sessions", ["tenant_id"], unique=False)
    op.create_index(
        op.f("ix_chat_sessions_owner_user_id"),
        "chat_sessions",
        ["owner_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_sessions_owner_user_id"), table_name="chat_sessions")
    op.drop_index(op.f("ix_chat_sessions_tenant_id"), table_name="chat_sessions")
    op.drop_column("chat_sessions", "metadata_json")
    op.drop_column("chat_sessions", "approach")
    op.drop_column("chat_sessions", "model_id")
    op.drop_column("chat_sessions", "active_bucket_id")
    op.drop_column("chat_sessions", "owner_user_id")
    op.drop_column("chat_sessions", "tenant_id")
