"""Server-side superapp availability, with explicit per-user exceptions."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import AppAvailability, UserAppAccess


APPLICATIONS = {"budget": "Бюджет", "photo": "Фотографии"}


def application_state(db: Session, app_id: str, user_id: int | None = None) -> dict:
    if app_id not in APPLICATIONS:
        raise HTTPException(status_code=404, detail="Application not found")
    global_access = db.get(AppAvailability, app_id)
    enabled = global_access.enabled if global_access else True
    override = db.get(UserAppAccess, (user_id, app_id)) if user_id is not None else None
    return {
        "id": app_id,
        "name": APPLICATIONS[app_id],
        "enabled": enabled,
        "available": override.enabled if override and override.enabled is not None else enabled,
        "version": global_access.version if global_access else 0,
        "override": override.enabled if override else None,
        "override_version": override.version if override else 0,
    }


def require_application(db: Session, app_id: str, user_id: int) -> None:
    # Administrators follow the same availability rules as everyone else;
    # the superapp administration and central authentication stay independent.
    if not application_state(db, app_id, user_id)["available"]:
        raise HTTPException(status_code=403, detail="Приложение закрыто для вашего аккаунта")
