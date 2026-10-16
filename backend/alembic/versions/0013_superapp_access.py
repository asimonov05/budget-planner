"""Shared application availability and versioned per-user exceptions."""

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_availability",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("id IN ('budget', 'photo')", name="ck_application_availability_id"),
        sa.CheckConstraint("version > 0", name="ck_application_availability_version"),
    )
    op.create_table(
        "user_app_access",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("app_id", sa.String(32), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("app_id IN ('budget', 'photo')", name="ck_user_app_access_app_id"),
        sa.CheckConstraint("version > 0", name="ck_user_app_access_version"),
    )
    availability = sa.table("application_availability", sa.column("id", sa.String()),
                            sa.column("enabled", sa.Boolean()), sa.column("version", sa.Integer()))
    op.bulk_insert(availability, [{"id": app_id, "enabled": True, "version": 1}
                                  for app_id in ("budget", "photo")])
    if op.get_bind().dialect.name != "postgresql":
        return
    admin = (
        "EXISTS (SELECT 1 FROM users WHERE users.id = "
        "NULLIF(current_setting('app.admin_actor_id', true), '')::integer "
        "AND users.is_admin AND users.active)"
    )
    owner = "user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer"
    for table in ("application_availability", "user_app_access"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY application_admin ON {table} TO budget_runtime "
                   f"USING ({admin}) WITH CHECK ({admin})")
        op.execute(f"CREATE POLICY debug_admin_read ON {table} FOR SELECT "
                   "TO debug_admin USING (true)")
    op.execute("CREATE POLICY application_public ON application_availability FOR SELECT "
               "TO budget_runtime USING (true)")
    op.execute(f"CREATE POLICY application_owner ON user_app_access FOR SELECT "
               f"TO budget_runtime USING ({owner})")


def downgrade() -> None:
    op.drop_table("user_app_access")
    op.drop_table("application_availability")
