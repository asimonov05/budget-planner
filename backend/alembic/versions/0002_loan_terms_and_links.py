"""Loan interest terms and links to planned and actual payments."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("loans", sa.Column("annual_rate_bps", sa.Integer(), nullable=True))
    op.add_column(
        "loans",
        sa.Column("interest_method", sa.String(16), nullable=False, server_default="simple"),
    )
    op.add_column(
        "loans",
        sa.Column("schedule_mode", sa.String(16), nullable=False, server_default="manual"),
    )
    op.add_column("loans", sa.Column("first_payment_date", sa.Date(), nullable=True))
    op.add_column("loans", sa.Column("annuity_payment_minor", sa.Integer(), nullable=True))

    # SQLite can append a nullable REFERENCES column in place. Rebuilding these
    # tables would cascade-delete existing plan matches and goal movements.
    op.execute("ALTER TABLE plan_items ADD COLUMN loan_id INTEGER REFERENCES loans(id)")
    op.create_index("ix_plan_items_loan_id", "plan_items", ["loan_id"])

    op.execute("ALTER TABLE transactions ADD COLUMN loan_id INTEGER REFERENCES loans(id)")
    op.add_column(
        "transactions", sa.Column("principal_component_minor", sa.Integer(), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("interest_component_minor", sa.Integer(), nullable=True)
    )
    op.add_column("transactions", sa.Column("prepayment_strategy", sa.String(24), nullable=True))
    op.add_column("transactions", sa.Column("loan_balance_applied", sa.Boolean(), nullable=True))
    op.create_index("ix_transactions_loan_id", "transactions", ["loan_id"])
    op.execute(
        "UPDATE transactions SET loan_id = ("
        "SELECT loan_id FROM loan_schedule_items "
        "WHERE 'loan_schedule:' || loan_schedule_items.id = transactions.external_source"
        ") WHERE external_source LIKE 'loan_schedule:%'"
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_loan_id", "transactions")
    op.drop_column("transactions", "loan_balance_applied")
    op.drop_column("transactions", "prepayment_strategy")
    op.drop_column("transactions", "interest_component_minor")
    op.drop_column("transactions", "principal_component_minor")
    op.drop_column("transactions", "loan_id")
    op.drop_index("ix_plan_items_loan_id", "plan_items")
    op.drop_column("plan_items", "loan_id")
    op.drop_column("loans", "annuity_payment_minor")
    op.drop_column("loans", "first_payment_date")
    op.drop_column("loans", "schedule_mode")
    op.drop_column("loans", "interest_method")
    op.drop_column("loans", "annual_rate_bps")
