"""Owner-only account management in the shared database."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from ..db import get_auth_db
from ..models import SessionToken, User
from ..schemas import PrivateUserCreate, PrivateUserOut, PrivateUserPassword, PrivateUserStatus
from ..security import hash_password, require_csrf_unlocked, require_user


router = APIRouter(prefix="/users", tags=["users"])


def require_admin(
    user: User = Depends(require_user), db: Session = Depends(get_auth_db)
) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Owner access required")
    db.info["admin_actor_id"] = user.id
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.admin_actor_id', :actor_id, true)"),
            {"actor_id": str(user.id)},
        )
    return user


@router.get("")
def list_users(_=Depends(require_admin), db: Session = Depends(get_auth_db)) -> dict:
    users = db.scalars(select(User).order_by(User.id)).all()
    return {"items": [PrivateUserOut.model_validate(user) for user in users], "total": len(users)}


@router.post("", response_model=PrivateUserOut, status_code=201)
def create_user(
    body: PrivateUserCreate,
    _admin=Depends(require_admin),
    _csrf=Depends(require_csrf_unlocked),
    db: Session = Depends(get_auth_db),
) -> User:
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        is_admin=False,
        active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=PrivateUserOut)
def set_user_status(
    user_id: int,
    body: PrivateUserStatus,
    admin: User = Depends(require_admin),
    _csrf=Depends(require_csrf_unlocked),
    db: Session = Depends(get_auth_db),
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and not body.active:
        raise HTTPException(status_code=409, detail="Owner cannot disable their own account")
    user.active = body.active
    if not body.active:
        db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    body: PrivateUserPassword,
    _admin=Depends(require_admin),
    _csrf=Depends(require_csrf_unlocked),
    db: Session = Depends(get_auth_db),
) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(body.password)
    db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
    db.commit()
    return {"ok": True}
