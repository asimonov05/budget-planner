"""Repair loan-link schema drift and add monthly category estimates."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    transaction_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("transactions")
    }
    if "loan_balance_applied" not in transaction_columns:
        # Some installations had already marked revision 0002 complete before
        # this nullable link column was added to that revision's source.
        op.add_column(
            "transactions", sa.Column("loan_balance_applied", sa.Boolean(), nullable=True)
        )

    category_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("categories")
    }
    if "monthly_estimate" not in category_columns:
        op.add_column(
            "categories",
            sa.Column("monthly_estimate", sa.Boolean(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    category_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("categories")
    }
    if "monthly_estimate" in category_columns:
        op.drop_column("categories", "monthly_estimate")
