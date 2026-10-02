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
    DisplayRateInput,
    TagCreate,
    TagOut,
    TagUpdate,
)
from ..security import get_db, require_csrf, require_user
from ..core.tenant import budget_month_for_user, settings_for_user, tenant_id
from ..application.currency import SUPPORTED_CURRENCIES, convert_minor, parse_display_rates, positive_rate


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


@router.get("/currencies/display-rates")
def list_display_rates(_=Depends(require_user), db: Session = Depends(get_db)) -> dict:
    settings = settings_for_user(db)
    base_currency = settings.currency if settings else "RUB"
    saved = json.loads(settings.display_rates_json if settings else "{}")
    used = set(db.scalars(select(Account.currency).distinct()).all())
    used.update(db.scalars(select(PlanItem.currency).distinct()).all())
    currencies = (used | set(saved)) - {base_currency}
    return {
        "base_currency": base_currency,
        "version": settings.version if settings else None,
        "items": [
            {
                "from_currency": currency,
                "to_currency": base_currency,
                "rate": saved.get(currency, {}).get("rate"),
                "updated_on": saved.get(currency, {}).get("updated_on"),
                "required": currency in used,
            }
            for currency in sorted(currencies)
        ],
    }


@router.put("/currencies/display-rates/{from_currency}")
def save_display_rate(
    from_currency: str,
    body: DisplayRateInput,
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    settings = settings_for_user(db)
    if not settings:
        missing("Settings")
    ensure_version(settings, body.version)
    if from_currency not in SUPPORTED_CURRENCIES or from_currency == settings.currency:
        raise HTTPException(status_code=422, detail="Выберите другую поддерживаемую валюту")
    try:
        rate = positive_rate(body.rate.replace(",", "."))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    saved = json.loads(settings.display_rates_json)
    saved[from_currency] = {
        "rate": format(rate, "f"),
        "updated_on": datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat(),
    }
    settings.display_rates_json = json.dumps(saved, ensure_ascii=False, sort_keys=True)
    settings.version += 1
    db.commit()
    return {"from_currency": from_currency, "to_currency": settings.currency, **saved[from_currency], "version": settings.version}


@router.delete("/currencies/display-rates/{from_currency}", status_code=204)
def delete_display_rate(
    from_currency: str,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    settings = settings_for_user(db)
    if not settings:
        missing("Settings")
    ensure_version(settings, version)
    saved = json.loads(settings.display_rates_json)
    if from_currency not in saved:
        missing("Display rate")
    del saved[from_currency]
    settings.display_rates_json = json.dumps(saved, ensure_ascii=False, sort_keys=True)
    settings.version += 1
    db.commit()
    return Response(status_code=204)


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
        if data["currency"] not in SUPPORTED_CURRENCIES:
            raise HTTPException(status_code=422, detail="Unsupported currency")
        if has_financial_data and data["currency"] != value.currency:
            raise HTTPException(
                status_code=409, detail="Currency cannot be renamed after financial data exists"
            )
        if data["currency"] != value.currency:
            value.display_rates_json = "{}"
    if "currency_display_mode" in data and data["currency_display_mode"] is None:
        raise HTTPException(status_code=422, detail="Currency display mode is required")
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
            transfer.to_amount_minor
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
    base_currency = settings.currency if settings else "RUB"
    for account in db.scalars(statement).all():
        item = AccountOut.model_validate(account).model_dump()
        item["current_balance_minor"] = account_balance(db, account, as_of)
        items.append(item)
    return {
        "items": items,
        "total": len(items),
        "base_currency": base_currency,
        "currency_display_mode": settings.currency_display_mode if settings else "separate",
    }


@router.get("/accounts/converted-total")
def converted_account_total(_=Depends(require_user), db: Session = Depends(get_db)) -> dict:
    settings = settings_for_user(db)
    base_currency = settings.currency if settings else "RUB"
    try:
        zone = ZoneInfo(settings.timezone if settings else "Europe/Moscow")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("Europe/Moscow")
    as_of = datetime.now(zone).date()
    totals: dict[str, int] = {}
    for account in db.scalars(select(Account)).all():
        totals[account.currency] = totals.get(account.currency, 0) + account_balance(db, account, as_of)
    rates = parse_display_rates(settings.display_rates_json if settings else "{}", base_currency)
    missing_rates = sorted(set(totals) - set(rates))
    if missing_rates:
        raise HTTPException(
            status_code=409,
            detail=f"Задайте курсы в настройках: {', '.join(missing_rates)}",
        )
    total_minor = sum(
        convert_minor(amount, currency, base_currency, rates[currency])
        for currency, amount in totals.items()
    )
    return {
        "currency": base_currency, "total_minor": total_minor,
        "as_of": as_of.isoformat(),
        "rate_source": "manual",
        "indicative": True,
        "totals_minor": totals,
        "rates": {currency: format(rates[currency], "f") for currency in totals},
    }


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(
    body: AccountCreate, _=Depends(require_csrf), db: Session = Depends(get_db)
) -> Account:
    settings = settings_for_user(db)
    base_currency = settings.currency if settings else "RUB"
    currency = body.currency or base_currency
    if currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=422, detail="Unsupported currency")
    value = Account(
        name=body.name,
        type=body.type,
        currency=currency,
        initial_balance_minor=body.initial_balance_minor,
        initial_balance_date=body.initial_balance_date,
    )
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
