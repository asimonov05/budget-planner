"""Persist in-app messages for the selected users in the caller's transaction."""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from .models import Notification


def deliver_notifications(
    db: Session,
    user_ids: Iterable[int],
    *,
    kind: str,
    title: str,
    body: str,
    release_note_id: int | None = None,
) -> int:
    recipients = list(user_ids)
    db.add_all(
        Notification(
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            release_note_id=release_note_id,
        )
        for user_id in recipients
    )
    return len(recipients)
