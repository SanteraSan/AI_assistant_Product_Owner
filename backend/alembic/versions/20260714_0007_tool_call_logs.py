"""add tool_call_logs audit table

Revision ID: 20260714_0007
Revises: 20260712_0006
Create Date: 2026-07-14 20:30:00+05:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260714_0007"
down_revision: str | None = "20260712_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_call_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column(
            "arguments_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_preview", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_tool_call_logs_request_id", "tool_call_logs", ["request_id"])
    op.create_index("ix_tool_call_logs_tenant_id", "tool_call_logs", ["tenant_id"])
    op.create_index("ix_tool_call_logs_user_id", "tool_call_logs", ["user_id"])
    op.create_index("ix_tool_call_logs_tool_name", "tool_call_logs", ["tool_name"])


def downgrade() -> None:
    op.drop_index("ix_tool_call_logs_tool_name", table_name="tool_call_logs")
    op.drop_index("ix_tool_call_logs_user_id", table_name="tool_call_logs")
    op.drop_index("ix_tool_call_logs_tenant_id", table_name="tool_call_logs")
    op.drop_index("ix_tool_call_logs_request_id", table_name="tool_call_logs")
    op.drop_table("tool_call_logs")
