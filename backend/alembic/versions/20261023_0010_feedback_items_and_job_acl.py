"""feedback items and indexing job owner

Revision ID: 20261023_0010
Revises: 20260915_0009
Create Date: 2026-10-23 15:45:00+05:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261023_0010"
down_revision: str | None = "20260915_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("bucket_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("feedback_class", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "index_in_rag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "feedback_class IN ('noise', 'churn_signal', 'bug', 'feature')",
            name="ck_feedback_items_feedback_class",
        ),
        sa.CheckConstraint(
            "index_in_rag = false OR feedback_class IN ('bug', 'feature')",
            name="ck_feedback_items_index_in_rag_class",
        ),
        sa.ForeignKeyConstraint(
            ["bucket_id"],
            ["knowledge_buckets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document_assets.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_feedback_items_tenant_id", "feedback_items", ["tenant_id"])
    op.create_index("ix_feedback_items_bucket_id", "feedback_items", ["bucket_id"])
    op.create_index("ix_feedback_items_document_id", "feedback_items", ["document_id"])

    op.add_column(
        "document_indexing_jobs",
        sa.Column("failed_stage", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "document_indexing_jobs",
        sa.Column("owner_user_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "document_indexing_jobs",
        sa.Column(
            "owner_roles_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("document_indexing_jobs", "owner_roles_json")
    op.drop_column("document_indexing_jobs", "owner_user_id")
    op.drop_column("document_indexing_jobs", "failed_stage")
    op.drop_index("ix_feedback_items_document_id", table_name="feedback_items")
    op.drop_index("ix_feedback_items_bucket_id", table_name="feedback_items")
    op.drop_index("ix_feedback_items_tenant_id", table_name="feedback_items")
    op.drop_table("feedback_items")
