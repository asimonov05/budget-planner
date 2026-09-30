"""One-shot database migration and role provisioning for Compose."""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from .config import config
from .db import database_connect_args, database_url, engine
from .migrations import migrate
from .models import TENANT_TABLES


def _password(path: Path | None, role: str) -> str:
    if path is None:
        raise RuntimeError(f"Password file for {role} is required")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 24:
        raise RuntimeError(f"Password for {role} is too short")
    return value


def _bootstrap_legacy_owner() -> None:
    """Carry the existing sole owner into the shared DB before user_id backfill."""
    with engine.begin() as destination:
        if destination.execute(text("SELECT to_regclass('public.alembic_version')")).scalar_one() is None:
            return
        revision = destination.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        if revision != "0006":
            return
        existing = destination.execute(text("SELECT count(*) FROM users")).scalar_one()
        if existing:
            return

    source_url = make_url(database_url()).set(database="budget_auth")
    # Fresh installations have no old auth database or owner to copy.
    with engine.connect() as connection:
        has_source = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'budget_auth'")
        ).scalar_one_or_none()
        financial_rows = connection.execute(text("SELECT count(*) FROM accounts")).scalar_one()
    if not has_source:
        if financial_rows:
            raise RuntimeError("Financial data exists, but legacy owner database is missing")
        return

    source = create_engine(
        source_url,
        connect_args=database_connect_args(str(source_url)),
        pool_pre_ping=True,
    )
    try:
        with source.connect() as connection:
            users = connection.execute(
                text("SELECT id, username, password_hash, created_at, budget_database, is_admin, active FROM users")
            ).mappings().all()
            sessions = connection.execute(
                text("SELECT id, user_id, token_hash, csrf_hash, expires_at, revoked, created_at FROM sessions")
            ).mappings().all()
        if len(users) != 1 or users[0]["budget_database"] != "budget" or not users[0]["is_admin"]:
            raise RuntimeError("Legacy auth has more than one budget owner; manual ID mapping required")
        with engine.begin() as destination:
            destination.execute(
                text("INSERT INTO users (id, username, password_hash, created_at, budget_database, is_admin, active) "
                     "VALUES (:id, :username, :password_hash, :created_at, :budget_database, :is_admin, :active)"),
                [dict(users[0])],
            )
            if sessions:
                destination.execute(
                    text("INSERT INTO sessions (id, user_id, token_hash, csrf_hash, expires_at, revoked, created_at) "
                         "VALUES (:id, :user_id, :token_hash, :csrf_hash, :expires_at, :revoked, :created_at)"),
                    [dict(row) for row in sessions],
                )
            for table in ("users", "sessions"):
                destination.execute(
                    text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                         f"GREATEST((SELECT coalesce(max(id), 0) FROM {table}), 1), "
                         f"(SELECT count(*) > 0 FROM {table}))")
                )
    finally:
        source.dispose()


def _role(cursor, name: str, password: str) -> None:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    if cursor.fetchone():
        cursor.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(
            sql.Identifier(name), sql.Literal(password)
        ))
    else:
        cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(
            sql.Identifier(name), sql.Literal(password)
        ))


def _admin_connection():
    url = make_url(database_url())
    return psycopg.connect(
        host=url.host, port=url.port or 5432, dbname=url.database,
        user=url.username, password=_password(config.database_password_file, "migration"),
    )


def _ensure_roles() -> None:
    runtime_password = _password(config.runtime_password_file, "runtime")
    debug_password = _password(config.debug_database_password_file, "debug admin")
    with _admin_connection() as connection:
        with connection.cursor() as cursor:
            _role(cursor, "budget_runtime", runtime_password)
            _role(cursor, "debug_admin", debug_password)


def _provision_roles() -> None:
    url = make_url(database_url())
    with _admin_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO budget_runtime, debug_admin")
                           .format(sql.Identifier(url.database)))
            cursor.execute("GRANT USAGE ON SCHEMA public TO budget_runtime, debug_admin")
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO budget_runtime")
            cursor.execute("REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM budget_runtime")
            cursor.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO budget_runtime")
            cursor.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO debug_admin")
            for table in sorted(TENANT_TABLES):
                cursor.execute(sql.SQL("DROP POLICY IF EXISTS debug_admin_read ON {}")
                               .format(sql.Identifier(table)))
                cursor.execute(sql.SQL("CREATE POLICY debug_admin_read ON {} FOR SELECT "
                                       "TO debug_admin USING (true)")
                               .format(sql.Identifier(table)))


def main() -> None:
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Migration job requires PostgreSQL")
    _bootstrap_legacy_owner()
    _ensure_roles()
    migrate()
    _provision_roles()


if __name__ == "__main__":
    main()
