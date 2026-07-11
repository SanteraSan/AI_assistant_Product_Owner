"""document library acl

Revision ID: 20260711_0003
Revises: 20260711_0002
Create Date: 2026-07-11 20:25:00+05:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260711_0003"
down_revision: str | None = "20260711_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("allowed_roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_assets_owner_user_id"),
        "document_assets",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_assets_tenant_id"),
        "document_assets",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "bucket_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("bucket_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("added_by_user_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["bucket_id"],
            ["knowledge_buckets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document_assets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bucket_id",
            "document_id",
            name="uq_bucket_documents_bucket_document",
        ),
    )
    op.create_index(
        op.f("ix_bucket_documents_bucket_id"),
        "bucket_documents",
        ["bucket_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bucket_documents_document_id"),
        "bucket_documents",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bucket_documents_tenant_id"),
        "bucket_documents",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "document_acl_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("permission", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
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
        sa.UniqueConstraint(
            "document_id",
            "subject_type",
            "subject_id",
            "permission",
            name="uq_document_acl_entry",
        ),
    )
    op.create_index(
        op.f("ix_document_acl_entries_document_id"),
        "document_acl_entries",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_acl_entries_tenant_id"),
        "document_acl_entries",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_acl_entries_tenant_id"), table_name="document_acl_entries")
    op.drop_index(op.f("ix_document_acl_entries_document_id"), table_name="document_acl_entries")
    op.drop_table("document_acl_entries")
    op.drop_index(op.f("ix_bucket_documents_tenant_id"), table_name="bucket_documents")
    op.drop_index(op.f("ix_bucket_documents_document_id"), table_name="bucket_documents")
    op.drop_index(op.f("ix_bucket_documents_bucket_id"), table_name="bucket_documents")
    op.drop_table("bucket_documents")
    op.drop_index(op.f("ix_document_assets_tenant_id"), table_name="document_assets")
    op.drop_index(op.f("ix_document_assets_owner_user_id"), table_name="document_assets")
    op.drop_table("document_assets")
