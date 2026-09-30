"""Protect sessions in the shared database without blocking token lookup."""

from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # TD-003 legacy SQLite fixtures.
    op.execute("ALTER TABLE sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sessions FORCE ROW LEVEL SECURITY")
    owner = "user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer"
    token = "token_hash = NULLIF(current_setting('app.session_token_hash', true), '')"
    admin = (
        "EXISTS (SELECT 1 FROM users WHERE users.id = "
        "NULLIF(current_setting('app.admin_actor_id', true), '')::integer "
        "AND users.is_admin AND users.active)"
    )
    op.execute(
        f"CREATE POLICY session_owner ON sessions TO budget_runtime "
        f"USING ({owner}) WITH CHECK ({owner})"
    )
    op.execute(
        f"CREATE POLICY session_token_lookup ON sessions FOR SELECT TO budget_runtime "
        f"USING ({token})"
    )
    op.execute(
        f"CREATE POLICY session_token_update ON sessions FOR UPDATE TO budget_runtime "
        f"USING ({token}) WITH CHECK ({token})"
    )
    op.execute(
        f"CREATE POLICY session_admin_select ON sessions FOR SELECT TO budget_runtime "
        f"USING ({admin})"
    )
    op.execute(
        f"CREATE POLICY session_admin_delete ON sessions FOR DELETE TO budget_runtime "
        f"USING ({admin})"
    )
    op.execute(
        "CREATE POLICY debug_admin_read ON sessions FOR SELECT TO debug_admin USING (true)"
    )


def downgrade() -> None:
    raise RuntimeError("Downgrading session RLS would remove the auth isolation boundary")
