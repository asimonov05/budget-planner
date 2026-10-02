"""Store account denominations and exact FX amounts without mixing ledgers."""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # TD-003 legacy SQLite fixtures.

    op.add_column(
        "accounts",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="RUB"),
    )
    op.execute(
        "UPDATE accounts AS a SET currency = COALESCE("
        "(SELECT s.currency FROM app_settings AS s WHERE s.user_id = a.user_id), 'RUB')"
    )

    op.add_column("transactions", sa.Column("merchant_currency", sa.String(length=3), nullable=True))
    op.add_column("transactions", sa.Column("merchant_amount_minor", sa.BigInteger(), nullable=True))
    op.add_column("transactions", sa.Column("merchant_exchange_rate", sa.Numeric(24, 12), nullable=True))
    op.create_check_constraint(
        "ck_transactions_merchant_rate_positive",
        "transactions",
        "merchant_exchange_rate IS NULL OR merchant_exchange_rate > 0",
    )

    op.add_column(
        "transfers",
        sa.Column("to_amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "transfers",
        sa.Column("exchange_rate", sa.Numeric(24, 12), nullable=False, server_default="1"),
    )
    op.execute("UPDATE transfers SET to_amount_minor = amount_minor")
    op.alter_column("transfers", "to_amount_minor", server_default=None)
    op.create_check_constraint("ck_transfers_to_amount_positive", "transfers", "to_amount_minor > 0")
    op.create_check_constraint("ck_transfers_rate_positive", "transfers", "exchange_rate > 0")

    op.add_column(
        "plan_items",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="RUB"),
    )
    op.execute(
        "UPDATE plan_items AS p SET currency = COALESCE("
        "(SELECT s.currency FROM app_settings AS s WHERE s.user_id = p.user_id), 'RUB')"
    )


def downgrade() -> None:
    raise RuntimeError("Downgrading currencies would discard exchange amounts and rates")
