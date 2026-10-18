"""Shared Photo identity boundary, including session-bound CSRF verification."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..application_access import require_application
from ..application.resolve_photo_user import PhotoRecipientNotFound, ResolvePhotoUser
from ..db import get_auth_db
from ..infrastructure.resolve_photo_user import SqlAlchemyPhotoRecipientLookup
from ..models import User
from ..security import require_csrf_unlocked


router = APIRouter(prefix="/apps/photo")


class PhotoIdentity(BaseModel):
    id: int
    username: str


class PhotoAdminIdentity(PhotoIdentity):
    is_admin: Literal[True] = True


def provide_photo_identity(
    user: User = Depends(require_csrf_unlocked),
    db: Session = Depends(get_auth_db),
) -> PhotoIdentity:
    require_application(db, "photo", user.id)
    return PhotoIdentity(id=user.id, username=user.username)


@router.get("/identity", response_model=PhotoIdentity)
@router.post("/identity", response_model=PhotoIdentity)
def photo_identity(identity: PhotoIdentity = Depends(provide_photo_identity)) -> PhotoIdentity:
    """POST also validates CSRF; it does not write or lock financial data.

    A server-side caller validates its browser origin before forwarding the
    session and CSRF header. Its upstream Origin must match the configured
    identity URL, just like any other request to the central identity API.
    """
    return identity


def provide_photo_admin_identity(
    user: User = Depends(require_csrf_unlocked),
) -> PhotoAdminIdentity:
    # Administration stays reachable even when Photo itself is disabled.
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return PhotoAdminIdentity(id=user.id, username=user.username)


@router.get("/admin/identity", response_model=PhotoAdminIdentity)
@router.post("/admin/identity", response_model=PhotoAdminIdentity)
def photo_admin_identity(
    identity: PhotoAdminIdentity = Depends(provide_photo_admin_identity),
) -> PhotoAdminIdentity:
    return identity


def provide_photo_recipient_lookup(db: Session = Depends(get_auth_db)) -> ResolvePhotoUser:
    return ResolvePhotoUser(SqlAlchemyPhotoRecipientLookup(db))


@router.get("/users/resolve", response_model=PhotoIdentity)
def resolve_photo_user(
    username: str = Query(min_length=3, max_length=80),
    _identity: PhotoIdentity = Depends(provide_photo_identity),
    handler: ResolvePhotoUser = Depends(provide_photo_recipient_lookup),
) -> PhotoIdentity:
    try:
        recipient = handler.execute(username)
    except PhotoRecipientNotFound as exc:
        raise HTTPException(status_code=404, detail="Пользователь не найден") from exc
    return PhotoIdentity(id=recipient.id, username=recipient.username)
