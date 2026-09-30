"""Self-service account registration command and its storage contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Protocol


USERNAME = re.compile(r"^[a-z][a-z0-9_.-]{2,79}$")


class InvalidRegistration(Exception):
    pass


class UsernameTaken(Exception):
    pass


class OwnerSetupRequired(Exception):
    pass


@dataclass(frozen=True)
class RegisterUserCommand:
    username: str
    password: str


@dataclass(frozen=True)
class RegisteredUser:
    id: int
    username: str
    session_token: str
    csrf_token: str


class RegistrationUnitOfWork(Protocol):
    def owner_exists(self) -> bool: ...
    def username_exists(self, username: str) -> bool: ...
    def create_user(self, username: str, password_hash: str) -> int: ...
    def create_session(self, user_id: int) -> tuple[str, str]: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class RegisterUserHandler:
    def __init__(
        self, unit_of_work: RegistrationUnitOfWork, hash_password: Callable[[str], str]
    ) -> None:
        self.unit_of_work = unit_of_work
        self.hash_password = hash_password

    def execute(self, command: RegisterUserCommand) -> RegisteredUser:
        if not USERNAME.fullmatch(command.username) or not 12 <= len(command.password) <= 512:
            raise InvalidRegistration
        try:
            if not self.unit_of_work.owner_exists():
                raise OwnerSetupRequired
            if self.unit_of_work.username_exists(command.username):
                raise UsernameTaken
            user_id = self.unit_of_work.create_user(
                command.username, self.hash_password(command.password)
            )
            token, csrf = self.unit_of_work.create_session(user_id)
            self.unit_of_work.commit()
            return RegisteredUser(user_id, command.username, token, csrf)
        except Exception:
            self.unit_of_work.rollback()
            raise
