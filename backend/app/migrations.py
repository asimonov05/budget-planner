from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from .db import database_url, engine


def alembic_config(url: str | None = None) -> Config:
    root = Path(__file__).resolve().parents[1]
    value = Config(str(root / "alembic.ini"))
    value.set_main_option("script_location", str(root / "alembic"))
    value.set_main_option("sqlalchemy.url", (url or database_url()).replace("%", "%%"))
    return value


def migrate() -> None:
    alembic = alembic_config()
    command.upgrade(alembic, "head")


def verify_schema_current() -> None:
    alembic = alembic_config()
    head = ScriptDirectory.from_config(alembic).get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    if current != head:
        raise RuntimeError(f"Database migration required: {current or 'base'} -> {head}")
