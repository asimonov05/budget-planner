from __future__ import annotations

import pytest

from app.application.reset_budget import (
    InvalidResetConfirmation,
    ResetBudgetCommand,
    ResetBudgetHandler,
    WrongResetPassword,
)


class FakeUnitOfWork:
    def __init__(self, *, fail: bool = False):
        self.events: list[object] = []
        self.fail = fail

    def clear_budget(self, owner_id: int) -> dict[str, int]:
        self.events.append(('clear', owner_id))
        if self.fail:
            raise RuntimeError('database failure')
        return {'accounts': 2}

    def record_reset(self, owner_id: int, deleted: dict[str, int]) -> None:
        self.events.append(('audit', owner_id, deleted))

    def revoke_other_sessions(self, owner_id: int, current_session_id: int) -> None:
        self.events.append(('revoke', owner_id, current_session_id))

    def commit(self) -> None:
        self.events.append('commit')

    def rollback(self) -> None:
        self.events.append('rollback')


def command(**changes) -> ResetBudgetCommand:
    data = {
        'owner_id': 7, 'current_session_id': 19,
        'password_hash': 'stored', 'password': 'correct', 'confirmation': 'RESET',
    }
    data.update(changes)
    return ResetBudgetCommand(**data)


def test_reset_command_requires_password_and_confirmation_before_writes():
    unit = FakeUnitOfWork()
    handler = ResetBudgetHandler(unit, lambda stored, candidate: candidate == 'correct')
    with pytest.raises(InvalidResetConfirmation):
        handler.execute(command(confirmation='wrong'))
    with pytest.raises(WrongResetPassword):
        handler.execute(command(password='wrong'))
    assert unit.events == []


def test_reset_command_commits_clear_audit_and_session_revocation_together():
    unit = FakeUnitOfWork()
    ResetBudgetHandler(unit, lambda stored, candidate: True).execute(command())
    assert unit.events == [
        ('clear', 7),
        ('audit', 7, {'accounts': 2}),
        ('revoke', 7, 19),
        'commit',
    ]


def test_reset_command_rolls_back_on_storage_failure():
    unit = FakeUnitOfWork(fail=True)
    with pytest.raises(RuntimeError, match='database failure'):
        ResetBudgetHandler(unit, lambda stored, candidate: True).execute(command())
    assert unit.events == [('clear', 7), 'rollback']
