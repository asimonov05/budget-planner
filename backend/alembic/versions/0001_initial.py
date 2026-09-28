"""Initial financial schema."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.db import Base
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=op.get_bind())
