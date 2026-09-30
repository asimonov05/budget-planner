from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker, with_loader_criteria

from .config import config


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    return config.database_url or f"sqlite:///{config.database_path}"


def database_connect_args(url: str, password_file: Path | None = None) -> dict:
    if url.startswith("sqlite:"):
        return {
        "check_same_thread": False,
        "timeout": 5,
        # Authenticated mutations explicitly issue BEGIN IMMEDIATE before
        # their first read.  Legacy transaction control is required here so
        # sqlite3 has not already opened an implicit deferred transaction.
        "autocommit": sqlite3.LEGACY_TRANSACTION_CONTROL,
        "isolation_level": "IMMEDIATE",
        }
    if url.startswith("postgresql"):
        args: dict = {"connect_timeout": 5, "options": "-c timezone=UTC"}
        secret = password_file or config.database_password_file
        if secret:
            args["password"] = secret.read_text(encoding="utf-8").strip()
        return args
    raise ValueError("Unsupported database URL")


if not config.database_url:
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    database_url(),
    connect_args=database_connect_args(database_url()),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def set_sqlite_pragmas(dbapi_connection: sqlite3.Connection, _record: object) -> None:
    previous_autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=FULL")
    cursor.close()
    dbapi_connection.autocommit = previous_autocommit


if engine.dialect.name == "sqlite":
    event.listen(engine, "connect", set_sqlite_pragmas)


def sqlite_version_safe() -> bool:
    version = tuple(int(part) for part in sqlite3.sqlite_version.split(".")[:3])
    return version >= (3, 51, 3)


def verify_database() -> dict[str, str | bool]:
    if engine.dialect.name == "postgresql":
        from .models import TENANT_TABLES

        with engine.connect() as connection:
            version = connection.execute(text("SHOW server_version")).scalar_one()
            role = connection.execute(text(
                "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
                "FROM pg_roles WHERE rolname = current_user"
            )).one()
            if any(role[1:]):
                raise RuntimeError("HTTP database role has elevated privileges")
            unsafe = connection.execute(text(
                "SELECT relname FROM pg_class "
                "WHERE relname = ANY(:tables) AND relkind = 'r' "
                "AND (NOT relrowsecurity OR NOT relforcerowsecurity OR relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user))"
            ), {"tables": sorted(TENANT_TABLES | {"sessions"})}).scalars().all()
            if unsafe:
                raise RuntimeError(f"Tenant RLS is not enforced on: {', '.join(unsafe)}")
            connection.execute(text("SELECT 1"))
        return {"database": "ok", "backend": "postgresql", "version": version}
    with engine.connect() as connection:
        fk = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        sync = connection.execute(text("PRAGMA synchronous")).scalar_one()
        connection.execute(text("SELECT 1"))
    safe = sqlite_version_safe()
    if config.require_safe_sqlite and not safe:
        raise RuntimeError(f"SQLite >= 3.51.3 required, got {sqlite3.sqlite_version}")
    if fk != 1 or str(journal).lower() != "wal" or int(sync) != 2:
        raise RuntimeError("Required SQLite safety pragmas were not applied")
    return {"database": "ok", "sqlite_version": sqlite3.sqlite_version, "sqlite_safe": safe}


def reserve_write_slot(db: Session) -> None:
    """Serialize one owner's financial read-check-write operations."""
    if db.bind.dialect.name == "postgresql":
        user_id = db.info.get("user_id")
        if not isinstance(user_id, int) or user_id <= 0:
            raise RuntimeError("Authenticated user is required for a financial write")
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :user_id)"),
            {"namespace": 17021986, "user_id": user_id},
        )
    else:
        db.execute(text("BEGIN IMMEDIATE"))


def get_auth_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


@event.listens_for(Session, "after_begin")
def set_tenant_scope(session: Session, _transaction, connection) -> None:
    user_id = session.info.get("user_id")
    connection.info["tenant_user_id"] = user_id
    if connection.dialect.name == "postgresql":
        for key, setting in (
            ("user_id", "app.current_user_id"),
            ("session_token_hash", "app.session_token_hash"),
            ("admin_actor_id", "app.admin_actor_id"),
        ):
            value = session.info.get(key)
            if value is not None:
                connection.execute(
                    text("SELECT set_config(:setting, :value, true)"),
                    {"setting": setting, "value": str(value)},
                )


@event.listens_for(Session, "before_flush")
def set_new_row_owner(session: Session, _context, _instances) -> None:
    from .models import TenantMixin

    user_id = session.info.get("user_id")
    if user_id is None and session.bind.dialect.name == "sqlite":
        user_id = 1
    for value in session.new:
        if isinstance(value, TenantMixin):
            if user_id is None:
                raise RuntimeError("Tenant context is required for financial inserts")
            if value.user_id is None:
                value.user_id = user_id
            elif value.user_id != user_id:
                raise PermissionError("Cannot insert data for another user")


@event.listens_for(Session, "do_orm_execute")
def scope_orm_reads(execute_state) -> None:
    from .models import TenantMixin

    user_id = execute_state.session.info.get("user_id")
    if user_id is not None and execute_state.is_select and not execute_state.is_relationship_load:
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                TenantMixin, lambda cls: cls.user_id == user_id, include_aliases=True
            )
        )
