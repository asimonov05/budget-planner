from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from .config import config
from .db import engine


def alembic_config() -> Config:
    root = Path(__file__).resolve().parents[1]
    value = Config(str(root / "alembic.ini"))
    value.set_main_option("script_location", str(root / "alembic"))
    value.set_main_option("sqlalchemy.url", f"sqlite:///{config.database_path}")
    return value


def migrate(backup_before_upgrade: bool = True) -> None:
    alembic = alembic_config()
    head = ScriptDirectory.from_config(alembic).get_current_head()
    current = None
    if config.database_path.exists() and config.database_path.stat().st_size:
        try:
            with engine.connect() as connection:
                current = MigrationContext.configure(connection).get_current_revision()
        except Exception:
            current = None
        if backup_before_upgrade and current != head:
            from .api.io import create_backup

            create_backup()
    command.upgrade(alembic, "head")
