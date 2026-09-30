from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app.db import Base, database_connect_args
from app import models  # noqa: F401

config = context.config
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=(
            database_connect_args(config.get_main_option("sqlalchemy.url"))
            if config.get_main_option("sqlalchemy.url").startswith("postgresql")
            else {"autocommit": False}
        ),
    )

    if connectable.dialect.name == "sqlite":
        @event.listens_for(connectable, "connect")
        def set_sqlite_pragmas(dbapi_connection, _record):
            previous_autocommit = dbapi_connection.autocommit
            dbapi_connection.autocommit = True
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.close()
            dbapi_connection.autocommit = previous_autocommit

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connectable.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
