from __future__ import annotations

import argparse
import getpass

from sqlalchemy import delete, select, text

from .db import SessionLocal
from .migrations import verify_schema_current
from .models import SessionToken, User
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
        if db.scalar(select(User.id).where(User.is_admin.is_(True))):
            raise SystemExit("Владелец уже создан")
        db.add(User(username=username, password_hash=hash_password(password_twice()), is_admin=True))
        db.commit()
    print(f"Владелец {username} создан")


def reset_password(username: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            raise SystemExit("Пользователь не найден")
        user.password_hash = hash_password(password_twice())
        db.info["user_id"] = user.id
        if db.bind.dialect.name == "postgresql":
            db.execute(
                text("SELECT set_config('app.current_user_id', :user_id, true)"),
                {"user_id": str(user.id)},
            )
        db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
        db.commit()
    print("Пароль изменён; сессии пользователя отозваны")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-admin")
    init.add_argument("--username", default="owner")
    reset = sub.add_parser("reset-password")
    reset.add_argument("--username", default="owner")
    args = parser.parse_args()
    verify_schema_current()
    if args.command == "init-admin":
        init_admin(args.username)
    elif args.command == "reset-password":
        reset_password(args.username)


if __name__ == "__main__":
    main()
