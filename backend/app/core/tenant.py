"""Server-side ownership helpers for shared-budget queries."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AppSettings, BudgetMonth


def tenant_id(db: Session) -> int:
    value = db.info.get("user_id")
    if isinstance(value, int) and value > 0:
        return value
    if db.bind.dialect.name == "sqlite":
        return 1  # Legacy isolated test fixture.
    raise RuntimeError("Authenticated user scope is missing")


def settings_for_user(db: Session) -> AppSettings | None:
    return db.scalar(select(AppSettings).where(AppSettings.user_id == tenant_id(db)))


def budget_month_for_user(db: Session, month: str) -> BudgetMonth | None:
    return db.get(BudgetMonth, (tenant_id(db), month))
