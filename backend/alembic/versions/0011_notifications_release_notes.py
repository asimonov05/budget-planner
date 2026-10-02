"""In-app user notifications and owner-authored release notes."""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "release_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_version", sa.String(40), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_release_notes_status"),
        sa.UniqueConstraint("release_version", name="uq_release_notes_release_version"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("release_note_id", sa.Integer(), sa.ForeignKey("release_notes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('message', 'release')", name="ck_notifications_kind"),
        sa.UniqueConstraint("user_id", "id", name="uq_notifications_user_id_id"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_release_note_id", "notifications", ["release_note_id"])
    if op.get_bind().dialect.name != "postgresql":
        return

    admin = (
        "EXISTS (SELECT 1 FROM users WHERE users.id = "
        "NULLIF(current_setting('app.admin_actor_id', true), '')::integer "
        "AND users.is_admin AND users.active)"
    )
    owner = "user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer"
    op.execute("ALTER TABLE release_notes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE release_notes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY release_notes_published ON release_notes FOR SELECT "
        "TO budget_runtime USING (status = 'published')"
    )
    op.execute(
        f"CREATE POLICY release_notes_admin ON release_notes TO budget_runtime "
        f"USING ({admin}) WITH CHECK ({admin})"
    )
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY notifications_owner ON notifications TO budget_runtime "
        f"USING ({owner}) WITH CHECK ({owner})"
    )
    op.execute(
        f"CREATE POLICY notifications_admin ON notifications TO budget_runtime "
        f"USING ({admin}) WITH CHECK ({admin})"
    )
    op.execute(
        "CREATE POLICY debug_admin_read ON release_notes FOR SELECT TO debug_admin USING (true)"
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_release_note_id", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("release_notes")
