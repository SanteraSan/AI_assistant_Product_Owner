"""staged upload indexing jobs

Revision ID: 20260711_0004
Revises: 20260711_0003
Create Date: 2026-07-11 21:35:00+05:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260711_0004"
down_revision: str | None = "20260711_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staged_document_uploads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.String(length=255), nullable=True),
        sa.Column("original_file_name", sa.String(length=512), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_staged_document_uploads_owner_user_id"),
        "staged_document_uploads",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_staged_document_uploads_tenant_id"),
        "staged_document_uploads",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "document_indexing_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("bucket_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("chunks_indexed", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document_assets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_indexing_jobs_bucket_id"),
        "document_indexing_jobs",
        ["bucket_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_indexing_jobs_document_id"),
        "document_indexing_jobs",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_indexing_jobs_tenant_id"),
        "document_indexing_jobs",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_indexing_jobs_tenant_id"), table_name="document_indexing_jobs")
    op.drop_index(op.f("ix_document_indexing_jobs_document_id"), table_name="document_indexing_jobs")
    op.drop_index(op.f("ix_document_indexing_jobs_bucket_id"), table_name="document_indexing_jobs")
    op.drop_table("document_indexing_jobs")
    op.drop_index(op.f("ix_staged_document_uploads_tenant_id"), table_name="staged_document_uploads")
    op.drop_index(
        op.f("ix_staged_document_uploads_owner_user_id"),
        table_name="staged_document_uploads",
    )
    op.drop_table("staged_document_uploads")
