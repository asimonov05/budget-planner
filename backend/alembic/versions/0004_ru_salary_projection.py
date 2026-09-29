"""Opt-in Russian salary projections with per-employer payout matches."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("salary_enabled", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_table(
        "salary_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("gross_minor", sa.Integer(), nullable=False),
        sa.Column("advance_share_bps", sa.Integer(), nullable=False),
        sa.Column("advance_day", sa.Integer(), nullable=False),
        sa.Column("salary_day", sa.Integer(), nullable=False),
        sa.Column("start_month", sa.String(length=7), nullable=False),
        sa.Column("end_month", sa.String(length=7), nullable=True),
        sa.Column("initial_tax_base_minor", sa.Integer(), nullable=False),
        sa.Column("initial_tax_year", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("gross_minor > 0"),
        sa.CheckConstraint("advance_share_bps > 0 AND advance_share_bps < 10000"),
        sa.CheckConstraint("advance_day BETWEEN 16 AND 31"),
        sa.CheckConstraint("salary_day BETWEEN 1 AND 15"),
        sa.CheckConstraint("initial_tax_base_minor >= 0"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "salary_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("salary_rule_id", sa.Integer(), nullable=False),
        sa.Column("earning_month", sa.String(length=7), nullable=False),
        sa.Column("component", sa.String(length=16), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.CheckConstraint("amount_minor > 0"),
        sa.ForeignKeyConstraint(["salary_rule_id"], ["salary_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id"),
    )
    op.create_index("ix_salary_matches_salary_rule_id", "salary_matches", ["salary_rule_id"])


def downgrade() -> None:
    op.drop_index("ix_salary_matches_salary_rule_id", "salary_matches")
    op.drop_table("salary_matches")
    op.drop_table("salary_rules")
    op.drop_column("app_settings", "salary_enabled")
