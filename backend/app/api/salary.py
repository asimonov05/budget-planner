"""Salary rules, net payment previews, and reconciliation with actual receipts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.salary_projection import projected_salary_payments
from ..core.ru_payroll import add_months
from ..core.tenant import budget_month_for_user, settings_for_user
from ..models import Account, BudgetMonth, Category, PlanMatch, SalaryMatch, SalaryRule, Transaction
from ..schemas import SalaryMatchCreate, SalaryRuleCreate, SalaryRuleOut, SalaryRuleUpdate
from ..security import get_db, require_csrf, require_user


router = APIRouter(tags=["salary"])


def validate_references(db: Session, body: SalaryRuleCreate, *, allow_archived: bool = False) -> None:
    settings = settings_for_user(db)
    if not settings or settings.currency != "RUB":
        raise HTTPException(status_code=422, detail="Russian salary calculation requires RUB currency")
    account = db.get(Account, body.account_id) if body.account_id else None
    if not account or (account.archived and not allow_archived):
        raise HTTPException(status_code=422, detail="Choose an active salary account")
    if account.currency != "RUB":
        raise HTTPException(status_code=422, detail="Расчёт зарплаты требует рублёвый счёт")
    if body.category_id is not None:
        category = db.get(Category, body.category_id)
        if not category or (category.archived and not allow_archived) or category.kind != "income":
            raise HTTPException(status_code=422, detail="Choose an active income category")


@router.get("/salary-rules")
def list_salary_rules(include_archived: bool = False, _=Depends(require_user), db: Session = Depends(get_db)) -> dict:
    query = select(SalaryRule).order_by(SalaryRule.id)
    if not include_archived:
        query = query.where(SalaryRule.archived.is_(False))
    items = db.scalars(query).all()
    return {"items": [SalaryRuleOut.model_validate(item) for item in items], "total": len(items)}


@router.post("/salary-rules", response_model=SalaryRuleOut, status_code=201)
def create_salary_rule(body: SalaryRuleCreate, _=Depends(require_csrf), db: Session = Depends(get_db)) -> SalaryRule:
    validate_references(db, body)
    value = SalaryRule(**body.model_dump())
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


@router.put("/salary-rules/{entity_id}", response_model=SalaryRuleOut)
def update_salary_rule(entity_id: int, body: SalaryRuleUpdate, _=Depends(require_csrf), db: Session = Depends(get_db)) -> SalaryRule:
    value = db.get(SalaryRule, entity_id)
    if not value:
        raise HTTPException(status_code=404, detail="Salary rule not found")
    if value.version != body.version:
        raise HTTPException(status_code=409, detail="Version conflict; reload and retry")
    validate_references(db, body, allow_archived=body.archived)
    data = body.model_dump(exclude={"version"})
    financial_changed = any(
        getattr(value, key) != new_value for key, new_value in data.items() if key not in ("name", "archived")
    )
    if financial_changed and db.scalar(select(func.count()).select_from(SalaryMatch).where(SalaryMatch.salary_rule_id == entity_id)):
        raise HTTPException(status_code=409, detail="Salary with matched receipts cannot change; create a new rule")
    if financial_changed and db.scalar(select(func.count()).select_from(BudgetMonth).where(BudgetMonth.status == "closed", BudgetMonth.month >= value.start_month)):
        raise HTTPException(status_code=409, detail="Reopen closed months before changing salary calculation")
    for key, new_value in data.items():
        setattr(value, key, new_value)
    value.version += 1
    db.commit()
    db.refresh(value)
    return value


@router.delete("/salary-rules/{entity_id}", status_code=204)
def delete_salary_rule(entity_id: int, version: int = Query(ge=1), _=Depends(require_csrf), db: Session = Depends(get_db)) -> Response:
    value = db.get(SalaryRule, entity_id)
    if not value:
        raise HTTPException(status_code=404, detail="Salary rule not found")
    if value.version != version:
        raise HTTPException(status_code=409, detail="Version conflict; reload and retry")
    if db.scalar(select(func.count()).select_from(SalaryMatch).where(SalaryMatch.salary_rule_id == entity_id)):
        raise HTTPException(status_code=409, detail="Salary has matched receipts; archive it")
    db.delete(value)
    db.commit()
    return Response(status_code=204)


@router.get("/salary-payments")
def list_salary_payments(
    month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    if not 2025 <= int(month[:4]) <= 2100:
        raise HTTPException(status_code=422, detail="Salary month must be between 2025 and 2100")
    settings = settings_for_user(db)
    items = [item for item in projected_salary_payments(db, month) if item["date"].strftime("%Y-%m") == month] if settings and settings.salary_enabled else []
    return {"items": items, "total": len(items)}


@router.post("/salary-rules/{entity_id}/matches", status_code=201)
def match_salary(entity_id: int, body: SalaryMatchCreate, _=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    settings = settings_for_user(db)
    if not settings or not settings.salary_enabled:
        raise HTTPException(status_code=409, detail="Enable gross salary planning first")
    rule = db.get(SalaryRule, entity_id)
    transaction = db.get(Transaction, body.transaction_id)
    if not rule or rule.archived:
        raise HTTPException(status_code=404, detail="Salary rule not found")
    if not transaction or transaction.type != "income" or transaction.goal_id is not None:
        raise HTTPException(status_code=422, detail="Choose an ordinary income transaction")
    if transaction.account_id != rule.account_id or body.amount_minor > transaction.amount_minor:
        raise HTTPException(status_code=422, detail="Salary match account or amount does not match receipt")
    if db.scalar(select(PlanMatch.id).where(PlanMatch.transaction_id == transaction.id)) or db.scalar(select(SalaryMatch.id).where(SalaryMatch.transaction_id == transaction.id)):
        raise HTTPException(status_code=409, detail="Receipt is already matched")
    through = max(transaction.date.strftime("%Y-%m"), add_months(body.earning_month, 1))
    payment = next((item for item in projected_salary_payments(db, through) if item["salary_rule_id"] == entity_id and item["earning_month"] == body.earning_month and item["component"] == body.component), None)
    if not payment or body.amount_minor > payment["remaining_minor"]:
        raise HTTPException(status_code=422, detail="No matching salary payment or amount exceeds remainder")
    if abs((transaction.date - payment["date"]).days) > 31:
        raise HTTPException(status_code=422, detail="Receipt date is too far from salary payment")
    for month in {transaction.date.strftime("%Y-%m"), payment["date"].strftime("%Y-%m")}:
        budget_month = budget_month_for_user(db, month)
        if budget_month and budget_month.status == "closed":
            raise HTTPException(status_code=409, detail="Reopen month before matching salary")
    value = SalaryMatch(salary_rule_id=entity_id, **body.model_dump())
    db.add(value)
    db.commit()
    db.refresh(value)
    return {"id": value.id, **body.model_dump()}


@router.delete("/salary-matches/{entity_id}", status_code=204)
def unmatch_salary(entity_id: int, _=Depends(require_csrf), db: Session = Depends(get_db)) -> Response:
    value = db.get(SalaryMatch, entity_id)
    if not value:
        raise HTTPException(status_code=404, detail="Salary match not found")
    transaction = db.get(Transaction, value.transaction_id)
    if transaction:
        months = {transaction.date.strftime("%Y-%m")}
        for payment in projected_salary_payments(db, add_months(value.earning_month, 1)):
            if payment["salary_rule_id"] == value.salary_rule_id and payment["earning_month"] == value.earning_month and payment["component"] == value.component:
                months.add(payment["date"].strftime("%Y-%m"))
                break
        if any((record := budget_month_for_user(db, month)) and record.status == "closed" for month in months):
            raise HTTPException(status_code=409, detail="Reopen month before removing salary match")
    db.delete(value)
    db.commit()
    return Response(status_code=204)
