from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import delete, select

from .api.io import create_backup
from .config import config
from .db import SessionLocal, engine
from .models import SessionToken, User
from .migrations import alembic_config, migrate
from .security import hash_password


def password_twice() -> str:
    first = getpass.getpass("Пароль: ")
    second = getpass.getpass("Повторите пароль: ")
    if first != second:
        raise SystemExit("Пароли не совпадают")
    if len(first) < 12:
        raise SystemExit("Пароль должен содержать не менее 12 символов")
    return first


def init_admin(username: str) -> None:
    with SessionLocal() as db:
        if db.scalar(select(User)):
            raise SystemExit("Владелец уже создан")
        db.add(User(username=username, password_hash=hash_password(password_twice())))
        db.commit()
    print(f"Владелец {username} создан")


def reset_password(username: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            raise SystemExit("Владелец не найден")
        user.password_hash = hash_password(password_twice())
        db.execute(delete(SessionToken))
        db.commit()
    print("Пароль изменён; все сессии отозваны")


def restore(path: Path) -> None:
    if not path.is_file():
        raise SystemExit("Файл резервной копии не найден")
    source_uri = f"{path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as check:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("Резервная копия повреждена")
        if check.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise SystemExit("Нарушены внешние ключи")
        try:
            revision = check.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.DatabaseError as exc:
            raise SystemExit("Неизвестная схема резервной копии") from exc
        known_revisions = {
            item.revision
            for item in ScriptDirectory.from_config(alembic_config()).iterate_revisions(
                "head", "base"
            )
        }
        if not revision or revision[0] not in known_revisions:
            raise SystemExit("Несовместимая версия схемы резервной копии")
    current = create_backup() if config.database_path.exists() else None
    engine.dispose()
    fd, temporary_name = tempfile.mkstemp(
        prefix=".restore-", suffix=".sqlite3", dir=config.database_path.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with (
            closing(sqlite3.connect(source_uri, uri=True)) as source,
            closing(sqlite3.connect(temporary)) as destination,
        ):
            source.backup(destination)
            # Invalidate sessions before publication, so a crash after the
            # atomic replace cannot expose sessions from the restored image.
            destination.execute("DELETE FROM sessions")
            destination.commit()
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SystemExit("Временная восстановленная база повреждена")
            if destination.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise SystemExit("Нарушены внешние ключи после отзыва сессий")
        with temporary.open("rb") as restored_file:
            os.fsync(restored_file.fileno())
        # A replaced SQLite main file must never be opened alongside WAL/SHM
        # sidecars belonging to the previous database image.
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{config.database_path}{suffix}").unlink(missing_ok=True)
        os.replace(temporary, config.database_path)
        directory_fd = os.open(config.database_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"База восстановлена; предыдущая копия: {current or 'не создавалась'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-admin")
    init.add_argument("--username", default="owner")
    reset = sub.add_parser("reset-password")
    reset.add_argument("--username", default="owner")
    sub.add_parser("backup")
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command != "restore":
        migrate(backup_before_upgrade=True)
    if args.command == "init-admin":
        init_admin(args.username)
    elif args.command == "reset-password":
        reset_password(args.username)
    elif args.command == "backup":
        print(create_backup())
    elif args.command == "restore":
        restore(args.path)


if __name__ == "__main__":
    main()
