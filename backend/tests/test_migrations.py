from __future__ import annotations

import sqlite3
import shutil
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, Integer, Table, create_engine

from app.db import Base


def test_alembic_creates_and_reopens_file_database(tmp_path: Path, monkeypatch):
    backend_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "fresh.sqlite3"
    alembic = Config(str(backend_root / "alembic.ini"))
    alembic.set_main_option("script_location", str(backend_root / "alembic"))
    alembic.set_main_option("sqlalchemy.url", f"sqlite:///{database}")

    def unexpected_create_all(*_args, **_kwargs):
        raise AssertionError("The initial revision must not use current ORM metadata")

    monkeypatch.setattr(Base.metadata, "create_all", unexpected_create_all)
    future_table = Table(
        "future_model_table", Base.metadata, Column("id", Integer, primary_key=True)
    )
    try:
        command.upgrade(alembic, "head")
    finally:
        Base.metadata.remove(future_table)
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
    assert "future_model_table" not in tables
    assert revision == ("0002",)
    assert foreign_key_errors == []

    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    engine.dispose()


def test_existing_revision_0001_can_upgrade_without_losing_data(tmp_path: Path):
    backend_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "existing.sqlite3"
    versions = tmp_path / "alembic"
    shutil.copytree(
        backend_root / "alembic", versions, ignore=shutil.ignore_patterns("__pycache__")
    )
    alembic = Config(str(backend_root / "alembic.ini"))
    alembic.set_main_option("script_location", str(versions))
    alembic.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(alembic, "0001")

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            ("owner", "hash", "2026-01-01 00:00:00"),
        )

    (versions / "versions" / "0003_test.py").write_text(
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        "revision = '0003_test'\n"
        "down_revision = '0002'\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade():\n"
        "    op.add_column('users', sa.Column('display_name', sa.String(80)))\n"
        "def downgrade():\n"
        "    op.drop_column('users', 'display_name')\n"
    )

    command.upgrade(alembic, "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0003_test",
        )
        assert connection.execute("SELECT username, display_name FROM users").fetchone() == (
            "owner",
            None,
        )


def test_loan_migration_preserves_existing_plan_matches(tmp_path: Path):
    backend_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "linked.sqlite3"
    alembic = Config(str(backend_root / "alembic.ini"))
    alembic.set_main_option("script_location", str(backend_root / "alembic"))
    alembic.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(alembic, "0001")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO accounts "
            "(id, name, type, initial_balance_minor, initial_balance_date, archived, created_at, updated_at, version) "
            "VALUES (1, 'Счёт', 'bank', 100000, '2026-01-01', 0, '2026-01-01', '2026-01-01', 1)"
        )
        connection.execute(
            "INSERT INTO plan_items "
            "(id, kind, title, amount_minor, date, recurrence, certainty, status, funding_source, required, created_at, updated_at, version) "
            "VALUES (1, 'expense', 'Платёж', 1000, '2026-02-01', 'none', 'confirmed', 'planned', 'free', 0, '2026-01-01', '2026-01-01', 1)"
        )
        connection.execute(
            "INSERT INTO transactions "
            "(id, type, amount_minor, date, account_id, description, created_at, updated_at, version) "
            "VALUES (1, 'expense', 1000, '2026-02-01', 1, 'Платёж', '2026-02-01', '2026-02-01', 1)"
        )
        connection.execute(
            "INSERT INTO plan_matches "
            "(id, plan_item_id, occurrence_month, transaction_id, amount_minor, completed) "
            "VALUES (1, 1, '2026-02', 1, 1000, 1)"
        )
        connection.execute(
            "INSERT INTO loans (id, name, archived, created_at, updated_at, version) "
            "VALUES (1, 'Кредит', 0, '2026-01-01', '2026-01-01', 1)"
        )
        connection.execute(
            "INSERT INTO loan_schedule_items "
            "(id, loan_id, due_date, amount_minor, status, paid_minor, created_at, updated_at, version) "
            "VALUES (1, 1, '2026-02-01', 500, 'paid', 500, '2026-01-01', '2026-01-01', 1)"
        )
        connection.execute(
            "INSERT INTO transactions "
            "(id, type, amount_minor, date, account_id, description, external_source, created_at, updated_at, version) "
            "VALUES (2, 'expense', 500, '2026-02-01', 1, 'Кредит', 'loan_schedule:1', '2026-02-01', '2026-02-01', 1)"
        )

    command.upgrade(alembic, "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT plan_item_id, transaction_id FROM plan_matches"
        ).fetchall() == [(1, 1)]
        assert connection.execute("SELECT loan_id FROM transactions WHERE id = 2").fetchone() == (
            1,
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    command.downgrade(alembic, "0001")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT plan_item_id, transaction_id FROM plan_matches"
        ).fetchall() == [(1, 1)]
