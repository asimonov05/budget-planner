"""Read only the public identity fields of an active, exactly named recipient."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..application.resolve_photo_user import PhotoRecipient
from ..models import User


class SqlAlchemyPhotoRecipientLookup:
    def __init__(self, db: Session) -> None:
        self.db = db

    def active_user(self, username: str) -> PhotoRecipient | None:
        row = self.db.execute(
            select(User.id, User.username).where(User.username == username, User.active.is_(True))
        ).one_or_none()
        return None if row is None else PhotoRecipient(row.id, row.username)
