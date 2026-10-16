"""Resolve an explicitly supplied login for sharing, without exposing a directory."""

from dataclasses import dataclass
from typing import Protocol

from .register_user import USERNAME


@dataclass(frozen=True)
class PhotoRecipient:
    id: int
    username: str


class PhotoRecipientNotFound(Exception):
    pass


class PhotoRecipientLookup(Protocol):
    def active_user(self, username: str) -> PhotoRecipient | None: ...


class ResolvePhotoUser:
    def __init__(self, lookup: PhotoRecipientLookup) -> None:
        self.lookup = lookup

    def execute(self, username: str) -> PhotoRecipient:
        username = username.strip()
        if not USERNAME.fullmatch(username):
            raise PhotoRecipientNotFound
        recipient = self.lookup.active_user(username)
        if recipient is None:
            raise PhotoRecipientNotFound
        return recipient
