"""HTTP boundary and dependency provider for the reset command."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..application.reset_budget import (
    InvalidResetConfirmation,
    ResetBudgetCommand,
    ResetBudgetHandler,
    WrongResetPassword,
)
from ..infrastructure.reset_budget import SqlAlchemyResetBudget
from ..security import current_session, get_db, require_csrf, verify_password


router = APIRouter(tags=["data"])


class ResetBudgetInput(BaseModel):
    password: str
    confirmation: str


def provide_reset_budget_handler(db: Session = Depends(get_db)) -> ResetBudgetHandler:
    return ResetBudgetHandler(SqlAlchemyResetBudget(db), verify_password)


@router.post("/budget/reset")
def reset_budget(
    body: ResetBudgetInput,
    _=Depends(require_csrf),
    auth=Depends(current_session),
    handler: ResetBudgetHandler = Depends(provide_reset_budget_handler),
) -> dict[str, bool]:
    user, session = auth
    try:
        handler.execute(ResetBudgetCommand(
            owner_id=user.id,
            current_session_id=session.id,
            password_hash=user.password_hash,
            password=body.password,
            confirmation=body.confirmation,
        ))
    except InvalidResetConfirmation as exc:
        raise HTTPException(status_code=422, detail="Current password and RESET confirmation required") from exc
    except WrongResetPassword as exc:
        raise HTTPException(status_code=403, detail="Current password is incorrect") from exc
    return {"ok": True}
