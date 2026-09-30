"""Assign each login a private budget database and an administrator flag."""

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("budget_database", sa.String(length=63), server_default="budget", nullable=False),
    )
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), server_default="0", nullable=False),
    )
    op.add_column(
        "users", sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
    )
    op.execute("UPDATE users SET is_admin = true WHERE username = 'owner'")
    op.create_index("ix_users_budget_database", "users", ["budget_database"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_budget_database", table_name="users")
    op.drop_column("users", "active")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "budget_database")
