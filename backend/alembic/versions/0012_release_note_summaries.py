"""Keep release notifications short while retaining full release notes."""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _preview(body: str) -> str:
    paragraphs = [part.replace("\n", " ").strip() for part in body.split("\n\n") if part.strip()]
    if not paragraphs:
        return ""
    first_paragraph = next(
        (part for part in paragraphs if not part.startswith("#")), paragraphs[0]
    )
    return first_paragraph[:299] + "…" if len(first_paragraph) > 300 else first_paragraph


def upgrade() -> None:
    op.add_column(
        "release_notes",
        sa.Column("summary", sa.String(300), nullable=False, server_default=""),
    )
    connection = op.get_bind()
    notes = connection.execute(sa.text("SELECT id, body FROM release_notes")).all()
    for note_id, body in notes:
        connection.execute(
            sa.text("UPDATE release_notes SET summary = :summary WHERE id = :note_id"),
            {"summary": _preview(body), "note_id": note_id},
        )
    op.execute(
        "UPDATE notifications SET body = ("
        "SELECT summary FROM release_notes WHERE release_notes.id = notifications.release_note_id"
        ") WHERE kind = 'release' AND release_note_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("release_notes", "summary")
