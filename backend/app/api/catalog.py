from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Account,
    AppSettings,
    AuditLog,
    BudgetLimit,
    Category,
    Loan,
    PlanItem,
    SalaryRule,
    PlanItemTag,
    Tag,
    Transaction,
    TransactionTag,
    Transfer,
)
from ..schemas import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    SettingsOut,
    SettingsUpdate,
    TagCreate,
    TagOut,
    TagUpdate,
)
from ..security import get_db, require_csrf, require_user
from ..core.tenant import budget_month_for_user, settings_for_user, tenant_id


router = APIRouter(tags=["catalog"])


def conflict() -> None:
    raise HTTPException(status_code=409, detail="Version conflict; reload the entity and retry")


def missing(name: str) -> None:
    raise HTTPException(status_code=404, detail=f"{name} not found")


def ensure_version(value, version: int) -> None:
    if value.version != version:
        conflict()


def ensure_open(db: Session, value) -> None:
    month = budget_month_for_user(db, value.strftime("%Y-%m"))
    if month and month.status == "closed":
        raise HTTPException(
            status_code=409,
            detail="Month is closed; reopen it before deleting financial data",
        )


def audit_delete(db: Session, entity_type: str, value) -> None:
    before = {column.name: getattr(value, column.name) for column in value.__table__.columns}
    db.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=str(value.id),
            action="delete",
            before_json=json.dumps(before, default=str, ensure_ascii=False),
            after_json=None,
        )
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings(_=Depends(require_user), db: Session = Depends(get_db)) -> AppSettings:
    value = settings_for_user(db)
    if not value:
        value = AppSettings(user_id=tenant_id(db))
        db.add(value)
        db.commit()
        db.refresh(value)
    return value


@router.patch("/settings", response_model=SettingsOut)
def update_settings(
    body: SettingsUpdate, _=Depends(require_csrf), db: Session = Depends(get_db)
) -> AppSettings:
    value = settings_for_user(db)
    if not value:
        missing("Settings")
    if value.version != body.version:
        conflict()
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    has_financial_data = (db.scalar(select(func.count()).select_from(Transaction)) or 0) + (
        db.scalar(select(func.count()).select_from(Account)) or 0
    )
    if "currency" in data:
        if has_financial_data and data["currency"] != value.currency:
            raise HTTPException(
                status_code=409, detail="Currency cannot be renamed after financial data exists"
            )
    if (
        "accounting_start_date" in data
        and has_financial_data
        and data["accounting_start_date"] != value.accounting_start_date
    ):
        raise HTTPException(
            status_code=409,
            detail="Accounting start date cannot change after accounts or transactions exist",
        )
    if "timezone" in data:
        try:
            ZoneInfo(data["timezone"])
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Unknown IANA timezone") from exc
    if data.get("salary_enabled") and data.get("currency", value.currency) != "RUB":
        raise HTTPException(status_code=422, detail="Russian salary calculation requires RUB currency")
    for key, val in data.items():
        setattr(value, key, val)
    value.version += 1
    db.commit()
    db.refresh(value)
    return value


def account_balance(db: Session, account: Account, as_of: date) -> int:
    if account.initial_balance_date > as_of:
        return 0
    total = account.initial_balance_minor
    for tx in db.scalars(
        select(Transaction).where(Transaction.account_id == account.id, Transaction.date <= as_of)
    ).all():
        total += (
            tx.amount_minor if tx.type in ("income", "refund", "adjustment") else -tx.amount_minor
        )
    for transfer in db.scalars(
        select(Transfer).where(
            (Transfer.from_account_id == account.id) | (Transfer.to_account_id == account.id),
            Transfer.date <= as_of,
        )
    ).all():
        total += (
            transfer.amount_minor
            if transfer.to_account_id == account.id
            else -transfer.amount_minor
        )
    return total


@router.get("/accounts")
def list_accounts(
    include_archived: bool = False, _=Depends(require_user), db: Session = Depends(get_db)
) -> dict:
    settings = settings_for_user(db)
    try:
        zone = ZoneInfo(settings.timezone if settings else "Europe/Moscow")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("Europe/Moscow")
    as_of = datetime.now(zone).date()
    statement = select(Account).order_by(Account.id)
    if not include_archived:
        statement = statement.where(Account.archived.is_(False))
    items = []
    for account in db.scalars(statement).all():
        item = AccountOut.model_validate(account).model_dump()
        item["current_balance_minor"] = account_balance(db, account, as_of)
        items.append(item)
    return {"items": items, "total": len(items)}


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(
    body: AccountCreate, _=Depends(require_csrf), db: Session = Depends(get_db)
) -> Account:
    value = Account(**body.model_dump())
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


@router.patch("/accounts/{entity_id}", response_model=AccountOut)
def update_account(
    entity_id: int, body: AccountUpdate, _=Depends(require_csrf), db: Session = Depends(get_db)
) -> Account:
    value = db.get(Account, entity_id)
    if not value:
        missing("Account")
    if value.version != body.version:
        conflict()
    for key, val in body.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(value, key, val)
    value.version += 1
    db.commit()
    db.refresh(value)
    return value


@router.delete("/accounts/{entity_id}", status_code=204)
def delete_account(
    entity_id: int,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    value = db.get(Account, entity_id)
    if not value:
        missing("Account")
    ensure_version(value, version)
    has_references = any(
        (
            db.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.account_id == entity_id)
            ),
            db.scalar(
                select(func.count())
                .select_from(Transfer)
                .where(
                    (Transfer.from_account_id == entity_id) | (Transfer.to_account_id == entity_id)
                )
            ),
            db.scalar(
                select(func.count()).select_from(PlanItem).where(PlanItem.account_id == entity_id)
            ),
            db.scalar(select(func.count()).select_from(Loan).where(Loan.account_id == entity_id)),
            db.scalar(select(func.count()).select_from(SalaryRule).where(SalaryRule.account_id == entity_id)),
        )
    )
    if has_references:
        raise HTTPException(
            status_code=409,
            detail="Account has financial history or dependencies; archive it instead",
        )
    ensure_open(db, value.initial_balance_date)
    audit_delete(db, "account", value)
    db.delete(value)
    db.commit()
    return Response(status_code=204)


@router.get("/categories")
def list_categories(
    include_archived: bool = False,
    kind: str | None = None,
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(Category).order_by(Category.sort_order, Category.id)
    if not include_archived:
        statement = statement.where(Category.archived.is_(False))
    if kind:
        statement = statement.where(Category.kind == kind)
    items = db.scalars(statement).all()
    return {"items": [CategoryOut.model_validate(x) for x in items], "total": len(items)}


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(
    body: CategoryCreate, _=Depends(require_csrf), db: Session = Depends(get_db)
) -> Category:
    value = Category(**body.model_dump())
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


@router.patch("/categories/{entity_id}", response_model=CategoryOut)
def update_category(
    entity_id: int, body: CategoryUpdate, _=Depends(require_csrf), db: Session = Depends(get_db)
) -> Category:
    value = db.get(Category, entity_id)
    if not value:
        missing("Category")
    if value.version != body.version:
        conflict()
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if "monthly_estimate" in data and (
        data["monthly_estimate"] is None or (data["monthly_estimate"] and value.kind != "expense")
    ):
        raise HTTPException(
            status_code=422,
            detail="Ежемесячная оценка доступна только для категорий расходов",
        )
    for key, val in data.items():
        setattr(value, key, val)
    value.version += 1
    db.commit()
    db.refresh(value)
    return value


@router.delete("/categories/{entity_id}", status_code=204)
def delete_category(
    entity_id: int,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    value = db.get(Category, entity_id)
    if not value:
        missing("Category")
    ensure_version(value, version)
    has_references = any(
        (
            db.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.category_id == entity_id)
            ),
            db.scalar(
                select(func.count()).select_from(PlanItem).where(PlanItem.category_id == entity_id)
            ),
            db.scalar(
                select(func.count())
                .select_from(BudgetLimit)
                .where(BudgetLimit.category_id == entity_id)
            ),
            db.scalar(select(func.count()).select_from(SalaryRule).where(SalaryRule.category_id == entity_id)),
        )
    )
    if has_references:
        raise HTTPException(
            status_code=409,
            detail="Category has financial history or dependencies; archive it instead",
        )
    audit_delete(db, "category", value)
    db.delete(value)
    db.commit()
    return Response(status_code=204)


@router.get("/tags")
def list_tags(
    include_archived: bool = False, _=Depends(require_user), db: Session = Depends(get_db)
) -> dict:
    statement = select(Tag).order_by(Tag.name)
    if not include_archived:
        statement = statement.where(Tag.archived.is_(False))
    items = db.scalars(statement).all()
    return {"items": [TagOut.model_validate(x) for x in items], "total": len(items)}


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(body: TagCreate, _=Depends(require_csrf), db: Session = Depends(get_db)) -> Tag:
    value = Tag(**body.model_dump())
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


@router.patch("/tags/{entity_id}", response_model=TagOut)
def update_tag(
    entity_id: int, body: TagUpdate, _=Depends(require_csrf), db: Session = Depends(get_db)
) -> Tag:
    value = db.get(Tag, entity_id)
    if not value:
        missing("Tag")
    if value.version != body.version:
        conflict()
    for key, val in body.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(value, key, val)
    value.version += 1
    db.commit()
    db.refresh(value)
    return value


@router.delete("/tags/{entity_id}", status_code=204)
def delete_tag(
    entity_id: int,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    value = db.get(Tag, entity_id)
    if not value:
        missing("Tag")
    ensure_version(value, version)
    has_references = any(
        (
            db.scalar(
                select(func.count())
                .select_from(TransactionTag)
                .where(TransactionTag.tag_id == entity_id)
            ),
            db.scalar(
                select(func.count()).select_from(PlanItemTag).where(PlanItemTag.tag_id == entity_id)
            ),
        )
    )
    if has_references:
        raise HTTPException(
            status_code=409,
            detail="Tag is used by transactions or plan items; archive it instead",
        )
    audit_delete(db, "tag", value)
    db.delete(value)
    db.commit()
    return Response(status_code=204)
