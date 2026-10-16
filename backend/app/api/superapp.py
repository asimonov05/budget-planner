"""Shared application catalogue and owner-only availability administration."""

from __future__ import annotations

import json

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session

from ..application_access import APPLICATIONS, application_state
from ..db import get_auth_db
from ..models import AppAvailability, AuditLog, User, UserAppAccess
from ..presentation.photo_identity import router as photo_identity_router
from ..security import current_session, require_csrf_unlocked
from .users import require_admin


router = APIRouter(prefix="/superapp", tags=["superapp"])
router.include_router(photo_identity_router)


class AvailabilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    version: int = Field(ge=0)


class UserAvailabilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None
    version: int = Field(ge=0)


def optional_user(
    request: Request,
    budget_session: str | None = Cookie(None),
    db: Session = Depends(get_auth_db),
) -> User | None:
    if not budget_session:
        return None
    try:
        return current_session(request, budget_session, db)[0]
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return None


def public_state(db: Session, app_id: str, user_id: int | None = None) -> dict:
    state = application_state(db, app_id, user_id)
    return {key: state[key] for key in ("id", "name", "enabled", "available")}


def admin_state(db: Session, app_id: str) -> dict:
    state = application_state(db, app_id)
    return {key: state[key] for key in ("id", "name", "enabled", "available", "version")}


def user_state(db: Session, app_id: str, user_id: int) -> dict:
    state = application_state(db, app_id, user_id)
    state["version"] = state.pop("override_version")
    return state


def ensure_version(value, expected: int) -> None:
    if (value.version if value else 0) != expected:
        raise HTTPException(status_code=409, detail="Version conflict; reload and retry")


def audit_change(db: Session, admin: User, app_id: str, before: dict, after: dict,
                 user_id: int | None = None) -> None:
    db.add(AuditLog(
        user_id=admin.id,
        entity_type="application_access",
        entity_id=f"{user_id}:{app_id}" if user_id is not None else app_id,
        action="set_user_access" if user_id is not None else "set_global_access",
        before_json=json.dumps(before, ensure_ascii=False),
        after_json=json.dumps(after, ensure_ascii=False),
    ))


@router.get("/apps")
def list_applications(user: User | None = Depends(optional_user),
                      db: Session = Depends(get_auth_db)) -> dict:
    return {"apps": [public_state(db, app_id, user.id if user else None)
                     for app_id in APPLICATIONS]}


@router.get("/admin/apps")
def list_admin_applications(_=Depends(require_admin),
                            db: Session = Depends(get_auth_db)) -> dict:
    return {"apps": [admin_state(db, app_id) for app_id in APPLICATIONS]}


@router.patch("/admin/apps/{app_id}")
def update_application(app_id: str, body: AvailabilityUpdate,
                       admin: User = Depends(require_admin),
                       _csrf=Depends(require_csrf_unlocked),
                       db: Session = Depends(get_auth_db)) -> dict:
    before = admin_state(db, app_id)
    value = db.get(AppAvailability, app_id)
    ensure_version(value, body.version)
    if value is None:
        value = AppAvailability(id=app_id, enabled=body.enabled, version=1)
        db.add(value)
    else:
        value.enabled = body.enabled
        value.version += 1
    after = {**before, "enabled": body.enabled, "available": body.enabled,
             "version": value.version}
    audit_change(db, admin, app_id, before, after)
    db.commit()
    return after


@router.get("/admin/users/{user_id}/apps")
def list_user_applications(user_id: int, _=Depends(require_admin),
                           db: Session = Depends(get_auth_db)) -> dict:
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user_id,
            "apps": [user_state(db, app_id, user_id) for app_id in APPLICATIONS]}


@router.patch("/admin/users/{user_id}/apps/{app_id}")
def update_user_application(user_id: int, app_id: str, body: UserAvailabilityUpdate,
                            admin: User = Depends(require_admin),
                            _csrf=Depends(require_csrf_unlocked),
                            db: Session = Depends(get_auth_db)) -> dict:
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    before = user_state(db, app_id, user_id)
    value = db.get(UserAppAccess, (user_id, app_id))
    ensure_version(value, body.version)
    if value is None:
        value = UserAppAccess(user_id=user_id, app_id=app_id, enabled=body.enabled, version=1)
        db.add(value)
    else:
        value.enabled = body.enabled
        value.version += 1
    after = {**before, "override": body.enabled,
             "available": before["enabled"] if body.enabled is None else body.enabled,
             "version": value.version}
    audit_change(db, admin, app_id, before, after, user_id)
    db.commit()
    return after
