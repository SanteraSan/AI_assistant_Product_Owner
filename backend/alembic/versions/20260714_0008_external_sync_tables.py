"""add external_* synced analytics tables for E4

Revision ID: 20260714_0008
Revises: 20260714_0007
Create Date: 2026-07-14 23:30:00+05:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260714_0008"
down_revision: str | None = "20260714_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_customers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("segment", sa.String(length=64), nullable=False, server_default="enterprise"),
        sa.Column("arr_usd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_external_customers_tenant_id", "external_customers", ["tenant_id"])
    op.create_index("ix_external_customers_external_id", "external_customers", ["external_id"])

    op.create_table(
        "external_support_tickets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("customer_external_id", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column(
            "product_area",
            sa.String(length=64),
            nullable=False,
            server_default="notifications",
        ),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_external_support_tickets_tenant_id",
        "external_support_tickets",
        ["tenant_id"],
    )
    op.create_index(
        "ix_external_support_tickets_external_id",
        "external_support_tickets",
        ["external_id"],
    )
    op.create_index(
        "ix_external_support_tickets_customer_external_id",
        "external_support_tickets",
        ["customer_external_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_support_tickets_customer_external_id",
        table_name="external_support_tickets",
    )
    op.drop_index(
        "ix_external_support_tickets_external_id",
        table_name="external_support_tickets",
    )
    op.drop_index(
        "ix_external_support_tickets_tenant_id",
        table_name="external_support_tickets",
    )
    op.drop_table("external_support_tickets")
    op.drop_index("ix_external_customers_external_id", table_name="external_customers")
    op.drop_index("ix_external_customers_tenant_id", table_name="external_customers")
    op.drop_table("external_customers")
