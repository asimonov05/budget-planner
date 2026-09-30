"""Store monetary minor units as PostgreSQL bigint.

SQLite INTEGER already stores signed 64-bit values, so its schema is unchanged.
"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


MONEY_COLUMNS = {
    "accounts": ("initial_balance_minor",),
    "goals": ("target_amount_minor", "initial_reserved_minor"),
    "transactions": (
        "amount_minor", "principal_component_minor", "interest_component_minor",
    ),
    "transfers": ("amount_minor",),
    "plan_items": ("amount_minor",),
    "plan_overrides": ("amount_minor",),
    "plan_matches": ("amount_minor",),
    "salary_rules": ("gross_minor", "initial_tax_base_minor"),
    "salary_matches": ("amount_minor",),
    "budget_limits": ("amount_minor",),
    "budget_limit_overrides": ("amount_minor",),
    "goal_reserve_movements": ("amount_minor",),
    "loans": ("principal_minor", "annuity_payment_minor"),
    "loan_schedule_items": ("amount_minor", "principal_minor", "interest_minor", "paid_minor"),
}


def change_money_type(target_type: sa.types.TypeEngine, old_type: sa.types.TypeEngine) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name, columns in MONEY_COLUMNS.items():
        for column_name in columns:
            op.alter_column(
                table_name,
                column_name,
                type_=target_type,
                existing_type=old_type,
            )


def upgrade() -> None:
    change_money_type(sa.BigInteger(), sa.Integer())


def downgrade() -> None:
    change_money_type(sa.Integer(), sa.BigInteger())
