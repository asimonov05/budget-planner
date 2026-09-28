from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import config
from ..db import get_db
from ..models import SessionToken, User
from ..schemas import LoginInput
from ..security import (
    clear_login_rate,
    create_session,
    current_session,
    enforce_login_rate,
    require_csrf,
    verify_password,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(
    body: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict:
    rate_key = request.client.host if request.client else "unknown"
    enforce_login_rate(rate_key)
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not verify_password(user.password_hash, body.password):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid username or password")
    clear_login_rate(rate_key)
    token, csrf = create_session(db, user)
    response.set_cookie(
        "budget_session",
        token,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
        max_age=config.session_days * 86400,
        path="/",
    )
    response.set_cookie(
        "csrf_token",
        csrf,
        httponly=False,
        secure=config.cookie_secure,
        samesite="strict",
        max_age=config.session_days * 86400,
        path="/",
    )
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "debug_admin_enabled": config.debug_admin_enabled,
        },
        "csrf_token": csrf,
    }


@router.get("/me")
def me(auth: tuple[User, SessionToken] = Depends(current_session)) -> dict:
    return {
        "id": auth[0].id,
        "username": auth[0].username,
        "debug_admin_enabled": config.debug_admin_enabled,
    }


@router.post("/logout")
def logout(
    response: Response,
    _=Depends(require_csrf),
    auth: tuple[User, SessionToken] = Depends(current_session),
    db: Session = Depends(get_db),
) -> dict:
    auth[1].revoked = True
    db.commit()
    response.delete_cookie("budget_session", path="/")
    response.delete_cookie("csrf_token", path="/")
    return {"ok": True}
