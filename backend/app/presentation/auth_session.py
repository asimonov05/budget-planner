"""Common cookie response for login and self-service registration."""

from __future__ import annotations

from fastapi import Response

from ..config import config


def authenticated_response(
    response: Response,
    *,
    user_id: int,
    username: str,
    is_admin: bool,
    session_token: str,
    csrf_token: str,
) -> dict:
    response.set_cookie(
        "budget_session",
        session_token,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
        max_age=config.session_days * 86400,
        path="/",
    )
    response.set_cookie(
        "csrf_token",
        csrf_token,
        httponly=False,
        secure=config.cookie_secure,
        samesite="strict",
        max_age=config.session_days * 86400,
        path="/",
    )
    return {
        "user": {
            "id": user_id,
            "username": username,
            "is_admin": is_admin,
            "debug_admin_enabled": config.debug_admin_enabled and is_admin,
        },
        "csrf_token": csrf_token,
    }
