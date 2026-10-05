"""Owner-authored messages, release notes, and each user's inbox."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import get_auth_db
from ..models import Notification, ReleaseNote, User
from ..notification_service import deliver_notifications
from ..security import get_db, require_csrf_unlocked, require_user
from .users import require_admin


router = APIRouter(tags=["notifications"])


class WrittenContent(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=20_000)

    @field_validator("title", "body")
    @classmethod
    def nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Text cannot be empty")
        return stripped


class MessageCreate(WrittenContent):
    recipient_user_id: int | None = Field(default=None, ge=1)


class ReleaseNoteDraft(WrittenContent):
    release_version: str = Field(pattern=r"^[0-9A-Za-z][0-9A-Za-z._-]{0,39}$")
    summary: str | None = Field(default=None, min_length=1, max_length=300)

    @field_validator("summary")
    @classmethod
    def nonempty_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Text cannot be empty")
        return stripped


def preview_from_body(body: str) -> str:
    """Provide a short preview for older clients that omit the summary."""
    paragraphs = [part.replace("\n", " ").strip() for part in body.split("\n\n") if part.strip()]
    first_paragraph = next(
        (part for part in paragraphs if not part.startswith("#")), paragraphs[0]
    )
    return first_paragraph[:299] + "…" if len(first_paragraph) > 300 else first_paragraph


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: Literal["message", "release"]
    title: str
    body: str
    release_note_id: int | None
    created_at: datetime
    read_at: datetime | None


class ReleaseNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    release_version: str
    title: str
    summary: str
    body: str
    status: Literal["draft", "published"]
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


@router.get("/notifications")
def list_notifications(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    scoped = select(Notification).where(Notification.user_id == user.id)
    items = db.scalars(
        scoped.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit).offset(offset)
    ).all()
    total = db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id)) or 0
    unread = db.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    )) or 0
    return {"items": [NotificationOut.model_validate(item) for item in items], "total": total, "unread": unread}


@router.get("/notifications/unread-count")
def unread_count(user: User = Depends(require_user), db: Session = Depends(get_db)) -> dict:
    count = db.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    )) or 0
    return {"count": count}


@router.get("/notifications/release-preview", response_model=NotificationOut | None)
def latest_unread_release(
    user: User = Depends(require_user), db: Session = Depends(get_db)
) -> Notification | None:
    return db.scalar(
        select(Notification).where(
            Notification.user_id == user.id,
            Notification.kind == "release",
            Notification.read_at.is_(None),
        ).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(1)
    )


@router.post("/notifications/read-all")
def mark_all_read(
    user: User = Depends(require_csrf_unlocked), db: Session = Depends(get_db)
) -> dict[str, int]:
    changed = db.execute(
        update(Notification).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        ).values(read_at=datetime.now(timezone.utc))
    ).rowcount
    db.commit()
    return {"updated": changed or 0}


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    user: User = Depends(require_csrf_unlocked),
    db: Session = Depends(get_db),
) -> Notification:
    item = db.scalar(select(Notification).where(
        Notification.id == notification_id, Notification.user_id == user.id
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if item.read_at is None:
        item.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(item)
    return item


@router.post("/notifications/send", status_code=201)
def send_message(
    body: MessageCreate,
    _admin: User = Depends(require_admin),
    _csrf: User = Depends(require_csrf_unlocked),
    db: Session = Depends(get_auth_db),
) -> dict:
    if body.recipient_user_id is None:
        recipients = db.scalars(select(User.id).where(User.active.is_(True))).all()
    else:
        recipient = db.scalar(select(User.id).where(
            User.id == body.recipient_user_id, User.active.is_(True)
        ))
        if recipient is None:
            raise HTTPException(status_code=404, detail="Active recipient not found")
        recipients = [recipient]
    delivered = deliver_notifications(
        db, recipients, kind="message", title=body.title, body=body.body
    )
    db.commit()
    return {"delivered": delivered}


@router.get("/release-notes", response_model=list[ReleaseNoteOut])
def list_release_notes(
    _user: User = Depends(require_user), db: Session = Depends(get_auth_db)
) -> list[ReleaseNote]:
    return db.scalars(select(ReleaseNote).where(
        ReleaseNote.status == "published"
    ).order_by(ReleaseNote.published_at.desc(), ReleaseNote.id.desc())).all()


@router.get("/release-notes/manage", response_model=list[ReleaseNoteOut])
def manage_release_notes(
    _admin: User = Depends(require_admin), db: Session = Depends(get_auth_db)
) -> list[ReleaseNote]:
    return db.scalars(select(ReleaseNote).order_by(ReleaseNote.id.desc())).all()


@router.get("/release-notes/{note_id}", response_model=ReleaseNoteOut)
def get_release_note(
    note_id: int,
    _user: User = Depends(require_user),
    db: Session = Depends(get_auth_db),
) -> ReleaseNote:
    note = db.scalar(select(ReleaseNote).where(
        ReleaseNote.id == note_id, ReleaseNote.status == "published"
    ))
    if note is None:
        raise HTTPException(status_code=404, detail="Release note not found")
    return note


@router.post("/release-notes", response_model=ReleaseNoteOut, status_code=201)
def create_release_note(
    body: ReleaseNoteDraft,
    _admin: User = Depends(require_admin),
    _csrf: User = Depends(require_csrf_unlocked),
    db: Session = Depends(get_auth_db),
) -> ReleaseNote:
    values = body.model_dump()
    values["summary"] = values["summary"] or preview_from_body(values["body"])
    note = ReleaseNote(**values)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.patch("/release-notes/{note_id}", response_model=ReleaseNoteOut)
def edit_release_note(
    note_id: int,
    body: ReleaseNoteDraft,
    _admin: User = Depends(require_admin),
    _csrf: User = Depends(require_csrf_unlocked),
    db: Session = Depends(get_auth_db),
) -> ReleaseNote:
    note = db.get(ReleaseNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Release note not found")
    if note.status != "draft":
        raise HTTPException(status_code=409, detail="Published release notes cannot be edited")
    values = body.model_dump()
    values["summary"] = values["summary"] or preview_from_body(values["body"])
    for key, value in values.items():
        setattr(note, key, value)
    note.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(note)
    return note


@router.post("/release-notes/{note_id}/publish")
def publish_release_note(
    note_id: int,
    _admin: User = Depends(require_admin),
    _csrf: User = Depends(require_csrf_unlocked),
    db: Session = Depends(get_auth_db),
) -> dict:
    now = datetime.now(timezone.utc)
    claimed = db.execute(
        update(ReleaseNote).where(
            ReleaseNote.id == note_id, ReleaseNote.status == "draft"
        ).values(status="published", published_at=now, updated_at=now)
        .returning(ReleaseNote.id)
    ).scalar_one_or_none()
    if claimed is None:
        if db.get(ReleaseNote, note_id) is None:
            raise HTTPException(status_code=404, detail="Release note not found")
        raise HTTPException(status_code=409, detail="Release note is already published")
    note = db.get(ReleaseNote, note_id)
    recipients = db.scalars(select(User.id).where(User.active.is_(True))).all()
    delivered = deliver_notifications(
        db, recipients, kind="release", title=note.title, body=note.summary,
        release_note_id=note.id,
    )
    db.commit()
    return {"release_note": ReleaseNoteOut.model_validate(note), "delivered": delivered}
