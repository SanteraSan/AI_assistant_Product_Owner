"""add demo_deals for sales composer cards

Revision ID: 20260915_0009
Revises: 20260714_0008
Create Date: 2026-09-15 21:30:00+05:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260915_0009"
down_revision: str | None = "20260714_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_deals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("bucket_id", sa.String(length=36), nullable=False),
        sa.Column("deal_code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="proposed"),
        sa.Column("close_date", sa.Date(), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "aliases_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "bucket_id",
            "deal_code",
            name="uq_demo_deals_tenant_bucket_code",
        ),
    )
    op.create_index("ix_demo_deals_tenant_id", "demo_deals", ["tenant_id"])
    op.create_index("ix_demo_deals_bucket_id", "demo_deals", ["bucket_id"])
    op.create_index("ix_demo_deals_deal_code", "demo_deals", ["deal_code"])


def downgrade() -> None:
    op.drop_index("ix_demo_deals_deal_code", table_name="demo_deals")
    op.drop_index("ix_demo_deals_bucket_id", table_name="demo_deals")
    op.drop_index("ix_demo_deals_tenant_id", table_name="demo_deals")
    op.drop_table("demo_deals")
