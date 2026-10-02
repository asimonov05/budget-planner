"""Allow each budget owner to choose how currency totals are displayed."""

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # TD-003 legacy SQLite fixtures.
    op.add_column(
        "app_settings",
        sa.Column(
            "currency_display_mode", sa.String(length=16),
            nullable=False, server_default="separate",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column("display_rates_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_check_constraint(
        "ck_app_settings_currency_display_mode",
        "app_settings",
        "currency_display_mode IN ('separate', 'converted')",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_constraint("ck_app_settings_currency_display_mode", "app_settings", type_="check")
    op.drop_column("app_settings", "display_rates_json")
    op.drop_column("app_settings", "currency_display_mode")
