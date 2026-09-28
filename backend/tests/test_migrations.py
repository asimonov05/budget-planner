from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_alembic_creates_and_reopens_file_database(tmp_path: Path):
    backend_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "fresh.sqlite3"
    alembic = Config(str(backend_root / "alembic.ini"))
    alembic.set_main_option("script_location", str(backend_root / "alembic"))
    alembic.set_main_option("sqlalchemy.url", f"sqlite:///{database}")

    command.upgrade(alembic, "head")
    command.upgrade(alembic, "head")

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert {"accounts", "transactions", "goals", "alembic_version"} <= tables
    assert revision == ("0001",)
    assert foreign_key_errors == []
