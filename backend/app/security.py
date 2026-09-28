from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import config
from .db import get_db
from .models import SessionToken, User


password_hasher = PasswordHasher(
    time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16
)
login_attempts: dict[str, deque[float]] = defaultdict(deque)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def enforce_login_rate(key: str) -> None:
    now = time.monotonic()
    attempts = login_attempts[key]
    while attempts and now - attempts[0] > 60:
        attempts.popleft()
    if len(attempts) >= 10:
        raise HTTPException(status_code=429, detail="Too many login attempts")
    attempts.append(now)


def clear_login_rate(key: str) -> None:
    login_attempts.pop(key, None)


def create_session(db: Session, user: User) -> tuple[str, str]:
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    db.add(
        SessionToken(
            user_id=user.id,
            token_hash=hash_token(token),
            csrf_hash=hash_token(csrf),
            expires_at=datetime.now(timezone.utc) + timedelta(days=config.session_days),
        )
    )
    db.commit()
    return token, csrf


def current_session(
    request: Request,
    budget_session: str | None = Cookie(None),
    db: Session = Depends(get_db),
) -> tuple[User, SessionToken]:
    if not budget_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    session = db.scalar(
        select(SessionToken).where(SessionToken.token_hash == hash_token(budget_session))
    )
    now = datetime.now(timezone.utc)
    if not session or session.revoked or session.expires_at.replace(tzinfo=timezone.utc) <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    request.state.auth_session = session
    return user, session


def require_user(auth: tuple[User, SessionToken] = Depends(current_session)) -> User:
    return auth[0]


def require_csrf(
    request: Request,
    x_csrf_token: str | None = Header(None),
    auth: tuple[User, SessionToken] = Depends(current_session),
    db: Session = Depends(get_db),
) -> User:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not x_csrf_token or not secrets.compare_digest(
            hash_token(x_csrf_token), auth[1].csrf_hash
        ):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
        origin = request.headers.get("origin")
        if origin:
            allowed = {str(request.base_url).rstrip("/")}
            if origin.rstrip("/") not in allowed:
                raise HTTPException(status_code=403, detail="Origin not allowed")
        # Take the SQLite writer reservation only after authentication and CSRF
        # validation, but before the endpoint performs its first financial read.
        # This turns write races into deterministic version conflicts rather
        # than SQLITE_BUSY_SNAPSHOT and protects read-check-write invariants.
        db.execute(text("BEGIN IMMEDIATE"))
    return auth[0]


def require_csrf_unlocked(
    request: Request,
    x_csrf_token: str | None = Header(None),
    auth: tuple[User, SessionToken] = Depends(current_session),
) -> User:
    """CSRF validation for commands that intentionally do long read-only work first."""
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not x_csrf_token or not secrets.compare_digest(
            hash_token(x_csrf_token), auth[1].csrf_hash
        ):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(status_code=403, detail="Origin not allowed")
    return auth[0]
