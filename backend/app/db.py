from __future__ import annotations

import sqlite3
from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import config


class Base(DeclarativeBase):
    pass


config.database_path.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    f"sqlite:///{config.database_path}",
    connect_args={
        "check_same_thread": False,
        "timeout": 5,
        # Authenticated mutations explicitly issue BEGIN IMMEDIATE before
        # their first read.  Legacy transaction control is required here so
        # sqlite3 has not already opened an implicit deferred transaction.
        "autocommit": sqlite3.LEGACY_TRANSACTION_CONTROL,
        "isolation_level": "IMMEDIATE",
    },
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@event.listens_for(engine, "connect")
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


def sqlite_version_safe() -> bool:
    version = tuple(int(part) for part in sqlite3.sqlite_version.split(".")[:3])
    return version >= (3, 51, 3)


def verify_database() -> dict[str, str | bool]:
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


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
