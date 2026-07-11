"""bucket document indexing status

Revision ID: 20260711_0005
Revises: 20260711_0004
Create Date: 2026-07-11 22:50:00+05:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260711_0005"
down_revision: str | None = "20260711_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bucket_documents",
        sa.Column("indexing_status", sa.String(length=32), nullable=False, server_default="indexed"),
    )
    op.add_column(
        "bucket_documents",
        sa.Column("indexing_error", sa.Text(), nullable=True),
    )
    op.alter_column("bucket_documents", "indexing_status", server_default=None)


def downgrade() -> None:
    op.drop_column("bucket_documents", "indexing_error")
    op.drop_column("bucket_documents", "indexing_status")
