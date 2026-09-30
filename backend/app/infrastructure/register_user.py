"""SQLAlchemy adapter for atomic registration and session creation."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..application.register_user import UsernameTaken
from ..config import config
from ..models import SessionToken, User
from .credentials import hash_token


class SqlAlchemyRegistration:
    def __init__(self, db: Session) -> None:
        self.db = db

    def owner_exists(self) -> bool:
        return self.db.scalar(
            select(User.id).where(User.is_admin.is_(True), User.active.is_(True))
        ) is not None

    def username_exists(self, username: str) -> bool:
        return self.db.scalar(select(User.id).where(User.username == username)) is not None

    def create_user(self, username: str, password_hash: str) -> int:
        user = User(
            username=username,
            password_hash=password_hash,
            is_admin=False,
            active=True,
        )
        self.db.add(user)
        try:
            self.db.flush()
        except IntegrityError as exc:
            raise UsernameTaken from exc
        return user.id

    def create_session(self, user_id: int) -> tuple[str, str]:
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        self.db.info["user_id"] = user_id
        if self.db.bind.dialect.name == "postgresql":
            self.db.execute(
                text("SELECT set_config('app.current_user_id', :user_id, true)"),
                {"user_id": str(user_id)},
            )
        self.db.add(SessionToken(
            user_id=user_id,
            token_hash=hash_token(token),
            csrf_hash=hash_token(csrf),
            expires_at=datetime.now(timezone.utc) + timedelta(days=config.session_days),
        ))
        return token, csrf

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
