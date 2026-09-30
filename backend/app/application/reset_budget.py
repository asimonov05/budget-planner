"""Application command for clearing one owner's financial workspace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ResetBudgetCommand:
    owner_id: int
    current_session_id: int
    password_hash: str
    password: str
    confirmation: str


class InvalidResetConfirmation(Exception):
    pass


class WrongResetPassword(Exception):
    pass


class PasswordVerifier(Protocol):
    def __call__(self, password_hash: str, password: str) -> bool: ...


class ResetBudgetUnitOfWork(Protocol):
    def clear_budget(self, owner_id: int) -> dict[str, int]: ...
    def record_reset(self, owner_id: int, deleted: dict[str, int]) -> None: ...
    def revoke_other_sessions(self, owner_id: int, current_session_id: int) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class ResetBudgetHandler:
    def __init__(self, unit_of_work: ResetBudgetUnitOfWork, verifier: PasswordVerifier):
        self.unit_of_work = unit_of_work
        self.verifier = verifier

    def execute(self, command: ResetBudgetCommand) -> None:
        if command.confirmation != "RESET" or not command.password:
            raise InvalidResetConfirmation
        if not self.verifier(command.password_hash, command.password):
            raise WrongResetPassword
        try:
            deleted = self.unit_of_work.clear_budget(command.owner_id)
            self.unit_of_work.record_reset(command.owner_id, deleted)
            self.unit_of_work.revoke_other_sessions(
                command.owner_id, command.current_session_id
            )
            self.unit_of_work.commit()
        except Exception:
            self.unit_of_work.rollback()
            raise
