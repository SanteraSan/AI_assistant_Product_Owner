"""feedback rule columns

Revision ID: 20261023_0011
Revises: 20261023_0010
Create Date: 2026-10-23 17:40:00+05:00

Head at authoring time was 20261023_0010. Downgrade drops only these
constraints and columns. Stage 1 columns and indexing-job fields stay.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261023_0011"
down_revision: str | None = "20261023_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "feedback_items",
        sa.Column("generator_class", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "feedback_items",
        sa.Column("rule_class", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "feedback_items",
        sa.Column("scenario_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "feedback_items",
        sa.Column("index_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "feedback_items",
        sa.Column("corpus_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "feedback_items",
        sa.Column("rule_reason", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "feedback_items",
        sa.Column("duplicate_of", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_feedback_items_generator_class",
        "feedback_items",
        "generator_class IS NULL OR generator_class IN ('noise', 'churn_signal', 'bug', 'feature')",
    )
    op.create_check_constraint(
        "ck_feedback_items_rule_class",
        "feedback_items",
        "rule_class IS NULL OR rule_class IN ('noise', 'churn_signal', 'bug', 'feature')",
    )
    op.create_check_constraint(
        "ck_feedback_items_rule_matches_feedback",
        "feedback_items",
        "rule_class IS NULL OR feedback_class = rule_class",
    )
    op.create_check_constraint(
        "ck_feedback_items_rule_reason",
        "feedback_items",
        "rule_reason IS NULL OR rule_reason IN ('lexicon_noise', 'lexicon_churn', 'keep_generator', 'exact_duplicate')",
    )
    op.create_unique_constraint(
        "uq_feedback_items_tenant_bucket_corpus",
        "feedback_items",
        ["tenant_id", "bucket_id", "corpus_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_feedback_items_tenant_bucket_corpus",
        "feedback_items",
        type_="unique",
    )
    op.drop_constraint(
        "ck_feedback_items_rule_reason",
        "feedback_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_feedback_items_rule_matches_feedback",
        "feedback_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_feedback_items_rule_class",
        "feedback_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_feedback_items_generator_class",
        "feedback_items",
        type_="check",
    )
    op.drop_column("feedback_items", "duplicate_of")
    op.drop_column("feedback_items", "rule_reason")
    op.drop_column("feedback_items", "corpus_id")
    op.drop_column("feedback_items", "index_text")
    op.drop_column("feedback_items", "scenario_id")
    op.drop_column("feedback_items", "rule_class")
    op.drop_column("feedback_items", "generator_class")
