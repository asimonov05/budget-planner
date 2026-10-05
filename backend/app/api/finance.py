from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.calculations import (
    calculate_forecast,
    effective_plan_amount,
    goal_remaining_need,
    goal_reserved,
    occurrence_date,
    occurs_in_month,
    projected_plan_occurrences,
    split_evenly,
)
from ..core.loans import annuity_payment, interest_for_period, monthly_dates, project_loan
from ..models import (
    Account,
    AuditLog,
    BudgetLimit,
    BudgetLimitOverride,
    BudgetMonth,
    Category,
    Goal,
    GoalReserveMovement,
    IdempotencyRecord,
    Loan,
    LoanScheduleItem,
    PlanItem,
    PlanMatch,
    SalaryMatch,
    PlanOverride,
    Tag,
    Transaction,
    Transfer,
)
from ..schemas import (
    BudgetLimitCreate,
    BudgetLimitOut,
    GoalCreate,
    GoalMovementCreate,
    GoalMovementOut,
    GoalOut,
    GoalUpdate,
    LoanCreate,
    LoanOut,
    LoanPaymentCreate,
    LoanScheduleCreate,
    LoanScheduleOut,
    LoanScheduleUpdate,
    LoanTransactionLink,
    LoanUpdate,
    MatchInput,
    OverrideInput,
    PlanItemCreate,
    PlanItemOut,
    PlanItemUpdate,
    TransactionCreate,
    TransactionOut,
    TransactionUpdate,
    TransferCreate,
    TransferOut,
    TransferUpdate,
)
from ..security import get_db, require_csrf, require_user
from ..core.tenant import budget_month_for_user, settings_for_user
from ..application.currency import SUPPORTED_CURRENCIES, convert_minor, parse_display_rates, positive_rate
from ..application.forecast_conversion import combine_forecasts


router = APIRouter(tags=["finance"])


def missing(name: str) -> None:
    raise HTTPException(status_code=404, detail=f"{name} not found")


def ensure_version(value, version: int) -> None:
    if value.version != version:
        raise HTTPException(status_code=409, detail="Version conflict; reload and retry")


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


def ensure_open(db: Session, value: date) -> None:
    month = budget_month_for_user(db, value.strftime("%Y-%m"))
    if month and month.status == "closed":
        raise HTTPException(
            status_code=409, detail="Month is closed; reopen it before changing financial data"
        )


def month_date(value: str) -> date:
    try:
        year, month = map(int, value.split("-"))
        parsed = date(year, month, 1)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Month must use YYYY-MM format") from exc
    if value != parsed.strftime("%Y-%m"):
        raise HTTPException(status_code=422, detail="Month must use YYYY-MM format")
    return parsed


def cash_balance_through(db: Session, through: date) -> int:
    settings = settings_for_user(db)
    base_currency = settings.currency if settings else "RUB"
    base_account_ids = {
        account.id for account in db.scalars(select(Account)).all()
        if account.currency == base_currency
    }
    cash = sum(
        account.initial_balance_minor
        for account in db.scalars(
            select(Account).where(
                Account.initial_balance_date <= through,
                Account.currency == base_currency,
            )
        ).all()
    )
    for transaction in db.scalars(
        select(Transaction).where(
            Transaction.date <= through,
            Transaction.account_id.in_(base_account_ids),
        )
    ).all():
        cash += (
            transaction.amount_minor
            if transaction.type in ("income", "refund", "adjustment")
            else -transaction.amount_minor
        )
    for transfer in db.scalars(select(Transfer).where(Transfer.date <= through)).all():
        if transfer.from_account_id in base_account_ids:
            cash -= transfer.amount_minor
        if transfer.to_account_id in base_account_ids:
            cash += transfer.to_amount_minor
    return cash


def total_reserved_through(db: Session, through: date) -> int:
    return sum(goal_reserved(db, goal, through) for goal in db.scalars(select(Goal)).all())


def ensure_transaction_account_date(account: Account, value: date) -> None:
    if value < account.initial_balance_date:
        raise HTTPException(
            status_code=422,
            detail="Transaction date cannot be before the account opening balance date",
        )


def rate_for_entry(source: str, target: str, _on_date: date, provided: str | None):
    """Cross-currency movements require a rate chosen by the user."""
    try:
        if source == target:
            rate = positive_rate(provided or "1")
            if rate != 1:
                raise ValueError("Same-currency rate must be 1")
            return rate
        if not provided:
            raise ValueError("Укажите курс вручную")
        return positive_rate(provided)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def merchant_details(
    account_currency: str,
    account_amount_minor: int,
    transaction_type: str,
    merchant_currency: str | None,
    merchant_amount_minor: int | None,
    merchant_exchange_rate: str | None,
) -> tuple[str | None, int | None, Decimal | None]:
    if merchant_currency is None and merchant_amount_minor is None and not merchant_exchange_rate:
        return None, None, None
    if transaction_type not in ("expense", "refund"):
        raise HTTPException(status_code=422, detail="Валюта покупки доступна для расхода или возврата")
    if not merchant_currency or merchant_amount_minor is None:
        raise HTTPException(status_code=422, detail="Укажите валюту и сумму покупки")
    try:
        if merchant_currency == account_currency:
            rate = positive_rate(merchant_exchange_rate or "1")
            if rate != 1 or merchant_amount_minor != account_amount_minor:
                raise ValueError("Для одной валюты сумма покупки должна совпадать со списанием")
        else:
            if not merchant_exchange_rate:
                raise ValueError("Укажите курс вручную")
            rate = positive_rate(merchant_exchange_rate)
            converted = convert_minor(
                merchant_amount_minor, merchant_currency, account_currency, rate
            )
            if abs(converted - account_amount_minor) > 1:
                raise ValueError("Курс не соответствует сумме фактического списания")
        return merchant_currency, merchant_amount_minor, rate
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def ensure_category_kind(db: Session, category_id: int | None, kind: str) -> None:
    if category_id is None:
        return
    category = db.get(Category, category_id)
    if not category:
        missing("Category")
    if category.kind != kind:
        raise HTTPException(status_code=422, detail=f"Category must be of kind '{kind}'")


def tags_by_ids(db: Session, ids: list[int]) -> list[Tag]:
    if not ids:
        return []
    values = db.scalars(select(Tag).where(Tag.id.in_(set(ids)))).all()
    if len(values) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Unknown tag_id")
    return list(values)


def idempotent_existing(db: Session, key: str | None, body: dict) -> dict | None:
    if not key:
        return None
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key == key))
    if record:
        if record.request_hash != digest:
            raise HTTPException(
                status_code=409, detail="Idempotency key was used with different content"
            )
        return json.loads(record.response_json)
    return None


def store_idempotent(db: Session, key: str | None, body: dict, response: dict) -> None:
    if not key:
        return
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    db.add(
        IdempotencyRecord(
            key=key,
            request_hash=digest,
            response_json=json.dumps(response, default=str),
            status_code=201,
        )
    )


@router.get("/transactions")
def list_transactions(
    from_date: date | None = None,
    to_date: date | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    goal_id: int | None = None,
    loan_id: int | None = None,
    tag_ids: list[int] = Query(default=[]),
    tag_mode: str = "or",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc())
    for condition in (
        Transaction.date >= from_date if from_date else None,
        Transaction.date <= to_date if to_date else None,
        Transaction.account_id == account_id if account_id else None,
        Transaction.category_id == category_id if category_id else None,
        Transaction.goal_id == goal_id if goal_id else None,
        Transaction.loan_id == loan_id if loan_id else None,
    ):
        if condition is not None:
            statement = statement.where(condition)
    if tag_ids:
        if tag_mode == "and":
            for tag_id in set(tag_ids):
                statement = statement.where(Transaction.tags.any(Tag.id == tag_id))
        else:
            statement = statement.where(Transaction.tags.any(Tag.id.in_(set(tag_ids))))
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    page = db.scalars(statement.limit(limit).offset(offset)).unique().all()
    page_ids = [transaction.id for transaction in page]
    matches = {
        match.transaction_id: match
        for match in (
            db.scalars(select(PlanMatch).where(PlanMatch.transaction_id.in_(page_ids))).all()
            if page_ids
            else []
        )
    }
    salary_matches = {
        match.transaction_id: match
        for match in (db.scalars(select(SalaryMatch).where(SalaryMatch.transaction_id.in_(page_ids))).all() if page_ids else [])
    }
    account_currencies = {
        account.id: account.currency for account in db.scalars(select(Account)).all()
    }
    items = []
    for transaction in page:
        item = TransactionOut.model_validate(transaction).model_dump(mode="json")
        item["account_currency"] = account_currencies.get(transaction.account_id)
        match = matches.get(transaction.id)
        if match:
            item.update(
                matched_plan_item_id=match.plan_item_id,
                matched_occurrence_month=match.occurrence_month,
                matched_amount_minor=match.amount_minor,
                match_completed=match.completed,
            )
        salary_match = salary_matches.get(transaction.id)
        if salary_match:
            item.update(
                matched_salary_rule_id=salary_match.salary_rule_id,
                matched_salary_earning_month=salary_match.earning_month,
                matched_salary_component=salary_match.component,
            )
        items.append(item)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/transactions/suggestions")
def suggest_transactions(
    query: str = Query(min_length=2, max_length=80),
    transaction_type: str = Query(alias="type", pattern=r"^(income|expense|refund)$"),
    account_id: int | None = Query(None, ge=1),
    limit: int = Query(5, ge=1, le=8),
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    needle = query.strip().casefold()
    if len(needle) < 2:
        raise HTTPException(status_code=422, detail="Введите хотя бы два символа")
    literal = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    candidates = db.scalars(
        select(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .where(
            Transaction.type == transaction_type,
            Transaction.description.ilike(f"%{literal}%", escape="\\"),
            Transaction.loan_id.is_(None),
            Transaction.goal_id.is_(None),
            Account.archived.is_(False),
        )
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(100)
    ).all()
    candidates.sort(key=lambda item: (
        item.description.strip().casefold() != needle,
        not item.description.strip().casefold().startswith(needle),
        account_id is not None and item.account_id != account_id,
        len(item.description.strip()) - len(needle),
        -item.date.toordinal(),
        -item.id,
    ))
    seen: set[tuple[str, int, int | None, str | None]] = set()
    items = []
    for item in candidates:
        signature = (
            item.description.strip().casefold(), item.account_id,
            item.category_id, item.merchant_currency,
        )
        if signature in seen:
            continue
        seen.add(signature)
        account = db.get(Account, item.account_id)
        category = db.get(Category, item.category_id) if item.category_id else None
        items.append({
            "id": item.id, "description": item.description,
            "date": item.date.isoformat(), "account_id": item.account_id,
            "category_id": item.category_id, "amount_minor": item.amount_minor,
            "account_name": account.name if account else None,
            "account_currency": account.currency if account else None,
            "category_name": category.name if category else None,
            "merchant_currency": item.merchant_currency,
            "merchant_amount_minor": item.merchant_amount_minor,
            "tag_ids": [tag.id for tag in item.tags if not tag.archived],
        })
        if len(items) >= limit:
            break
    return {"items": items}


@router.post("/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(
    body: TransactionCreate,
    idempotency_key: str | None = Header(None),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    body_data = body.model_dump()
    prior = idempotent_existing(db, idempotency_key, body_data)
    if prior:
        return prior
    ensure_open(db, body.date)
    account = db.get(Account, body.account_id)
    if not account:
        missing("Account")
    ensure_transaction_account_date(account, body.date)
    settings = settings_for_user(db)
    base_currency = settings.currency if settings else "RUB"
    merchant_currency, merchant_amount, merchant_rate = merchant_details(
        account.currency, body.amount_minor, body.type,
        body.merchant_currency, body.merchant_amount_minor, body.merchant_exchange_rate,
    )
    for key in ("merchant_currency", "merchant_amount_minor", "merchant_exchange_rate"):
        body_data.pop(key)
    body_data.update(
        merchant_currency=merchant_currency,
        merchant_amount_minor=merchant_amount,
        merchant_exchange_rate=merchant_rate,
    )
    if body.goal_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Goal expenses and refunds must use the atomic goal allocation endpoint",
        )
    if body.prepayment_strategy and body.loan_id is None:
        raise HTTPException(status_code=422, detail="Выберите кредит для досрочного платежа")
    if body.type == "adjustment" and body.category_id is not None:
        raise HTTPException(status_code=422, detail="Balance adjustment cannot have a category")
    if body.type != "adjustment":
        ensure_category_kind(
            db,
            body.category_id,
            "income" if body.type == "income" else "expense",
        )
    loan = None
    if body.loan_id is not None:
        if account.currency != base_currency:
            raise HTTPException(status_code=422, detail="Кредитный платёж должен списываться со счёта в основной валюте")
        if body.type != "expense":
            raise HTTPException(status_code=422, detail="С кредитом можно связать только расход")
        loan = db.get(Loan, body.loan_id)
        if not loan:
            missing("Loan")
        if loan.archived or loan.schedule_mode != "auto":
            raise HTTPException(
                status_code=409,
                detail="Для этого кредита проведите платёж через ручной график или восстановите кредит",
            )
        if (
            loan.principal_minor is None
            or loan.principal_as_of is None
            or loan.annual_rate_bps is None
        ):
            raise HTTPException(status_code=422, detail="У кредита не заполнены условия расчёта")
        if body.date < loan.principal_as_of:
            raise HTTPException(status_code=422, detail="Платёж раньше даты текущего остатка долга")
        future_dates = monthly_dates(loan.first_payment_date, loan.end_date, loan.principal_as_of)
        if not body.prepayment_strategy and future_dates and body.date < future_dates[0]:
            raise HTTPException(
                status_code=422,
                detail="Обычный платёж раньше даты графика; для дополнительного платежа выберите вариант досрочного погашения",
            )
        accrued_interest = interest_for_period(
            loan.principal_minor,
            loan.annual_rate_bps,
            loan.principal_as_of,
            body.date,
            loan.interest_method,
        )
        principal_part = body.amount_minor - accrued_interest
        if principal_part <= 0 or principal_part > loan.principal_minor:
            raise HTTPException(
                status_code=409,
                detail="Платёж должен покрыть начисленные проценты и не превышать остаток долга",
            )
        new_principal = loan.principal_minor - principal_part
        if new_principal and loan.end_date and body.date >= loan.end_date:
            raise HTTPException(
                status_code=409, detail="После срока кредита должен быть погашен весь долг"
            )
        body_data["principal_component_minor"] = principal_part
        body_data["interest_component_minor"] = accrued_interest
        body_data["loan_balance_applied"] = True
        loan.principal_minor = new_principal
        loan.principal_as_of = body.date
        if body.prepayment_strategy == "reduce_payment" and new_principal:
            dates = monthly_dates(loan.first_payment_date, loan.end_date, body.date)
            loan.annuity_payment_minor = annuity_payment(
                new_principal, loan.annual_rate_bps, loan.interest_method, body.date, dates
            )
        if not new_principal:
            loan.annuity_payment_minor = 0
        loan.version += 1
    tag_ids = body_data.pop("tag_ids")
    value = Transaction(**body_data, tags=tags_by_ids(db, tag_ids))
    db.add(value)
    db.flush()
    output = TransactionOut.model_validate(value).model_dump(mode="json")
    store_idempotent(db, idempotency_key, body.model_dump(), output)
    db.commit()
    db.refresh(value)
    return value


@router.patch("/transactions/{entity_id}", response_model=TransactionOut)
def update_transaction(
    entity_id: int, body: TransactionUpdate, _=Depends(require_csrf), db: Session = Depends(get_db)
):
    value = db.get(Transaction, entity_id)
    if not value:
        missing("Transaction")
    ensure_open(db, value.date)
    if value.version != body.version:
        raise HTTPException(status_code=409, detail="Version conflict; reload and retry")
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if "amount_minor" in data and data["amount_minor"] is None:
        raise HTTPException(status_code=422, detail="Transaction amount cannot be null")
    if "date" in data and data["date"] is None:
        raise HTTPException(status_code=422, detail="Transaction date cannot be null")
    account = db.get(Account, value.account_id)
    if not account:
        missing("Account")
    amount = data.get("amount_minor", value.amount_minor)
    merchant_fields = {"merchant_currency", "merchant_amount_minor", "merchant_exchange_rate"}
    changed_merchant = bool(merchant_fields & data.keys())
    merchant_currency = data.pop("merchant_currency", value.merchant_currency)
    merchant_amount = data.pop("merchant_amount_minor", value.merchant_amount_minor)
    merchant_rate_input = data.pop("merchant_exchange_rate", None)
    if changed_merchant or ("amount_minor" in data and value.merchant_currency):
        merchant_currency, merchant_amount, merchant_rate = merchant_details(
            account.currency, amount, value.type,
            merchant_currency, merchant_amount, merchant_rate_input,
        )
        data.update(
            merchant_currency=merchant_currency,
            merchant_amount_minor=merchant_amount,
            merchant_exchange_rate=merchant_rate,
        )
    linked_goal_movement = db.scalar(
        select(GoalReserveMovement).where(GoalReserveMovement.transaction_id == value.id)
    )
    if linked_goal_movement and ({"amount_minor", "date"} & data.keys()):
        raise HTTPException(
            status_code=409,
            detail="A goal-linked transaction cannot be changed independently of its reserve movement",
        )
    if (
        value.external_source
        and value.external_source.startswith("loan_schedule:")
        and ({"amount_minor", "date"} & data.keys())
    ):
        raise HTTPException(
            status_code=409,
            detail="A loan payment cannot be changed independently of its schedule item",
        )
    if value.loan_id is not None and any(
        data[field] != getattr(value, field) for field in ("amount_minor", "date") if field in data
    ):
        raise HTTPException(
            status_code=409,
            detail="Связанный с кредитом платёж нельзя изменить без пересчёта долга",
        )
    if "date" in data and data["date"] != value.date and db.scalar(select(SalaryMatch.id).where(SalaryMatch.transaction_id == value.id)):
        raise HTTPException(status_code=409, detail="Unmatch salary before changing receipt date")
    if "amount_minor" in data and value.type != "adjustment":
        matched_amount = db.scalar(
            select(func.coalesce(func.sum(PlanMatch.amount_minor), 0)).where(
                PlanMatch.transaction_id == value.id
            )
        )
        matched_amount += db.scalar(select(func.coalesce(func.sum(SalaryMatch.amount_minor), 0)).where(SalaryMatch.transaction_id == value.id)) or 0
        if data["amount_minor"] < matched_amount:
            raise HTTPException(
                status_code=409,
                detail="Transaction amount cannot be lower than its matched plan amount",
            )
    resulting_category_id = data.get("category_id", value.category_id)
    if value.type == "adjustment":
        if data.get("amount_minor") == 0:
            raise HTTPException(status_code=422, detail="Balance adjustment cannot be zero")
        if resulting_category_id is not None:
            raise HTTPException(status_code=422, detail="Balance adjustment cannot have a category")
        resulting_comment = data.get("comment", value.comment)
        if not (resulting_comment or "").strip():
            raise HTTPException(status_code=422, detail="Balance adjustment requires a comment")
    else:
        ensure_category_kind(
            db,
            resulting_category_id,
            "income" if value.type == "income" else "expense",
        )
    if "date" in data:
        ensure_open(db, data["date"])
        account = db.get(Account, value.account_id)
        if account:
            ensure_transaction_account_date(account, data["date"])
    tag_ids = data.pop("tag_ids", None)
    for key, val in data.items():
        setattr(value, key, val)
    if tag_ids is not None:
        value.tags = tags_by_ids(db, tag_ids)
    value.version += 1
    db.commit()
    db.refresh(value)
    return value


@router.delete("/transactions/{entity_id}", status_code=204)
def delete_transaction(
    entity_id: int,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    value = db.get(Transaction, entity_id)
    if not value:
        missing("Transaction")
    ensure_version(value, version)
    ensure_open(db, value.date)
    if db.scalar(
        select(func.count()).select_from(PlanMatch).where(PlanMatch.transaction_id == entity_id)
    ):
        raise HTTPException(
            status_code=409,
            detail="Transaction is matched to a plan item; remove the match before deleting it",
        )
    if db.scalar(select(func.count()).select_from(SalaryMatch).where(SalaryMatch.transaction_id == entity_id)):
        raise HTTPException(status_code=409, detail="Transaction is matched to a salary payment; remove the match first")
    if db.scalar(
        select(func.count())
        .select_from(GoalReserveMovement)
        .where(GoalReserveMovement.transaction_id == entity_id)
    ):
        raise HTTPException(
            status_code=409,
            detail="Goal-linked transaction cannot be deleted independently of its reserve movement",
        )
    if value.external_source and value.external_source.startswith("loan_schedule:"):
        raise HTTPException(
            status_code=409,
            detail="Loan payment cannot be deleted independently of its schedule item",
        )
    if value.loan_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Связанный с кредитом платёж нельзя удалить без пересчёта долга",
        )
    audit_delete(db, "transaction", value)
    db.delete(value)
    db.commit()
    return Response(status_code=204)


@router.post("/transfers", response_model=TransferOut, status_code=201)
def create_transfer(
    body: TransferCreate,
    idempotency_key: str | None = Header(None),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    prior = idempotent_existing(db, idempotency_key, body.model_dump())
    if prior:
        return prior
    ensure_open(db, body.date)
    source = db.get(Account, body.from_account_id)
    target = db.get(Account, body.to_account_id)
    if not source or not target:
        missing("Account")
    ensure_transaction_account_date(source, body.date)
    ensure_transaction_account_date(target, body.date)
    rate = rate_for_entry(source.currency, target.currency, body.date, body.exchange_rate)
    try:
        credited = convert_minor(body.amount_minor, source.currency, target.currency, rate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if credited <= 0:
        raise HTTPException(status_code=422, detail="Сумма зачисления после конвертации должна быть положительной")
    value = Transfer(
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        amount_minor=body.amount_minor,
        to_amount_minor=credited,
        exchange_rate=rate,
        date=body.date,
        comment=body.comment,
    )
    db.add(value)
    db.flush()
    output = TransferOut.model_validate(value).model_dump(mode="json")
    store_idempotent(db, idempotency_key, body.model_dump(), output)
    db.commit()
    db.refresh(value)
    return value


@router.get("/transfers")
def list_transfers(_=Depends(require_user), db: Session = Depends(get_db)) -> dict:
    items = db.scalars(select(Transfer).order_by(Transfer.date.desc())).all()
    return {"items": [TransferOut.model_validate(x) for x in items], "total": len(items)}


@router.patch("/transfers/{entity_id}", response_model=TransferOut)
def update_transfer(
    entity_id: int,
    body: TransferUpdate,
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Transfer:
    value = db.get(Transfer, entity_id)
    if not value:
        missing("Transfer")
    ensure_version(value, body.version)
    ensure_open(db, value.date)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    for required_field in ("from_account_id", "to_account_id", "amount_minor", "date"):
        if required_field in data and data[required_field] is None:
            raise HTTPException(status_code=422, detail=f"{required_field} cannot be null")
    source_id = data.get("from_account_id", value.from_account_id)
    target_id = data.get("to_account_id", value.to_account_id)
    transfer_date = data.get("date", value.date)
    if source_id == target_id:
        raise HTTPException(status_code=422, detail="Transfer accounts must differ")
    source = db.get(Account, source_id)
    target = db.get(Account, target_id)
    if not source or not target:
        missing("Account")
    ensure_open(db, transfer_date)
    ensure_transaction_account_date(source, transfer_date)
    ensure_transaction_account_date(target, transfer_date)
    rate = rate_for_entry(
        source.currency,
        target.currency,
        transfer_date,
        data.get("exchange_rate") or (
            str(value.exchange_rate)
            if source_id == value.from_account_id and target_id == value.to_account_id
            else None
        ),
    )
    amount = data.get("amount_minor", value.amount_minor)
    try:
        credited = convert_minor(amount, source.currency, target.currency, rate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if credited <= 0:
        raise HTTPException(status_code=422, detail="Сумма зачисления после конвертации должна быть положительной")
    for key, val in data.items():
        if key == "exchange_rate":
            continue
        setattr(value, key, val)
    value.exchange_rate = rate
    value.to_amount_minor = credited
    value.version += 1
    db.commit()
    db.refresh(value)
    return value


@router.delete("/transfers/{entity_id}", status_code=204)
def delete_transfer(
    entity_id: int,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    value = db.get(Transfer, entity_id)
    if not value:
        missing("Transfer")
    ensure_version(value, version)
    ensure_open(db, value.date)
    audit_delete(db, "transfer", value)
    db.delete(value)
    db.commit()
    return Response(status_code=204)


@router.get("/plan-items")
def list_plan_items(
    kind: str | None = None,
    month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(PlanItem).order_by(PlanItem.id)
    if kind:
        statement = statement.where(PlanItem.kind == kind)
    items = db.scalars(statement).unique().all()
    if not month:
        return {"items": [PlanItemOut.model_validate(x) for x in items], "total": len(items)}

    overrides = {
        (override.plan_item_id, override.month): override
        for override in db.scalars(select(PlanOverride)).all()
    }
    projected = []
    for item in items:
        for nominal_month, amount, projected_date in projected_plan_occurrences(
            item, month, overrides
        ):
            value = PlanItemOut.model_validate(item).model_dump(mode="json")
            value["amount_minor"] = amount
            value["date"] = projected_date.isoformat() if projected_date else None
            value["occurrence_month"] = nominal_month
            base_date = occurrence_date(item, nominal_month)
            value["base_amount_minor"] = item.amount_minor
            value["base_date"] = base_date.isoformat() if base_date else None
            value["has_override"] = (item.id, nominal_month) in overrides
            projected.append(value)
    return {"items": projected, "total": len(projected)}


@router.post("/plan-items", response_model=PlanItemOut, status_code=201)
def create_plan_item(body: PlanItemCreate, _=Depends(require_csrf), db: Session = Depends(get_db)):
    data = body.model_dump()
    tag_ids = data.pop("tag_ids")
    account = db.get(Account, body.account_id) if body.account_id else None
    if body.account_id and not account:
        missing("Account")
    settings = settings_for_user(db)
    base_currency = settings.currency if settings else "RUB"
    currency = body.currency or (account.currency if account else base_currency)
    if currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=422, detail="Unsupported currency")
    if account and account.currency != currency:
        raise HTTPException(status_code=422, detail="Валюта плана должна совпадать с валютой счёта")
    if (body.goal_id or body.loan_id or body.funding_source == "goal") and currency != base_currency:
        raise HTTPException(status_code=422, detail="Цели и кредиты пока учитываются в основной валюте")
    data["currency"] = currency
    ensure_category_kind(db, body.category_id, body.kind)
    if body.goal_id and not db.get(Goal, body.goal_id):
        missing("Goal")
    if body.loan_id:
        loan = db.get(Loan, body.loan_id)
        if not loan:
            missing("Loan")
        if loan.archived:
            raise HTTPException(
                status_code=409, detail="Архивный кредит нельзя выбрать для платежа"
            )
    first_occurrence = (
        body.start_date or body.date or (month_date(body.month) if body.month else None)
    )
    if first_occurrence:
        ensure_open(db, first_occurrence)
    value = PlanItem(**data, tags=tags_by_ids(db, tag_ids))
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


@router.patch("/plan-items/{entity_id}", response_model=PlanItemOut)
def update_plan_item(
    entity_id: int, body: PlanItemUpdate, _=Depends(require_csrf), db: Session = Depends(get_db)
):
    value = db.get(PlanItem, entity_id)
    if not value:
        missing("Plan item")
    if value.version != body.version:
        raise HTTPException(status_code=409, detail="Version conflict; reload and retry")
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    tag_ids = data.pop("tag_ids", None)
    protected_fields = {
        "amount_minor",
        "end_date",
        "certainty",
        "account_id",
        "category_id",
        "loan_id",
    }
    protected_changes = {
        field
        for field in protected_fields.intersection(data)
        if data[field] != getattr(value, field)
    }
    if protected_changes:
        if db.scalar(
            select(func.count()).select_from(PlanMatch).where(PlanMatch.plan_item_id == entity_id)
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Plan item has matched transactions; only its title, comment, tags or "
                    "status can be changed"
                ),
            )
        overrides = {
            (override.plan_item_id, override.month): override
            for override in db.scalars(
                select(PlanOverride).where(PlanOverride.plan_item_id == entity_id)
            ).all()
        }
        closed_months = db.scalars(
            select(BudgetMonth.month).where(BudgetMonth.status == "closed")
        ).all()
        if any(projected_plan_occurrences(value, month, overrides) for month in closed_months):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Plan item has an occurrence in a closed month; only its title, comment, "
                    "tags or status can be changed"
                ),
            )
    if data.get("account_id"):
        account = db.get(Account, data["account_id"])
        if not account:
            missing("Account")
        if account.currency != value.currency:
            raise HTTPException(status_code=422, detail="Валюта нового счёта должна совпадать с валютой плана")
    if data.get("loan_id") is not None:
        loan = db.get(Loan, data["loan_id"])
        if not loan:
            missing("Loan")
        if loan.archived and data["loan_id"] != value.loan_id:
            raise HTTPException(
                status_code=409, detail="Архивный кредит нельзя выбрать для платежа"
            )
        if value.kind != "expense" or value.funding_source == "goal":
            raise HTTPException(
                status_code=422, detail="С кредитом можно связать только обычный расход"
            )
    ensure_category_kind(db, data.get("category_id", value.category_id), value.kind)
    for key, val in data.items():
        setattr(value, key, val)
    if tag_ids is not None:
        value.tags = tags_by_ids(db, tag_ids)
    value.version += 1
    db.commit()
    db.refresh(value)
    return value


@router.delete("/plan-items/{entity_id}", status_code=204)
def delete_plan_item(
    entity_id: int,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    value = db.get(PlanItem, entity_id)
    if not value:
        missing("Plan item")
    ensure_version(value, version)
    if value.status != "planned":
        raise HTTPException(
            status_code=409,
            detail="Only a planned item without history can be deleted; keep cancelled or fulfilled items for history",
        )
    if db.scalar(
        select(func.count()).select_from(PlanMatch).where(PlanMatch.plan_item_id == entity_id)
    ):
        raise HTTPException(
            status_code=409,
            detail="Plan item has matched transactions; cancel it instead",
        )
    overrides = {
        (override.plan_item_id, override.month): override
        for override in db.scalars(
            select(PlanOverride).where(PlanOverride.plan_item_id == entity_id)
        ).all()
    }
    closed_months = db.scalars(
        select(BudgetMonth.month).where(BudgetMonth.status == "closed")
    ).all()
    if any(projected_plan_occurrences(value, month, overrides) for month in closed_months):
        raise HTTPException(
            status_code=409,
            detail="Plan item has an occurrence in a closed month; cancel it instead or reopen the month",
        )
    audit_delete(db, "plan_item", value)
    db.delete(value)
    db.commit()
    return Response(status_code=204)


@router.put("/plan-items/{entity_id}/overrides/{month}")
def set_override(
    entity_id: int,
    month: str,
    body: OverrideInput,
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    ensure_open(db, month_date(month))
    if body.moved_date:
        ensure_open(db, body.moved_date)
    item = db.get(PlanItem, entity_id)
    if not item:
        missing("Plan item")
    if body.version is not None:
        ensure_version(item, body.version)
    if not occurs_in_month(item, month):
        raise HTTPException(
            status_code=422, detail="У этой записи нет повторения в выбранном месяце"
        )
    if db.scalar(
        select(func.count())
        .select_from(PlanMatch)
        .where(PlanMatch.plan_item_id == entity_id, PlanMatch.occurrence_month == month)
    ):
        raise HTTPException(status_code=409, detail="Сверенное повторение нельзя изменить")
    existing = db.scalar(
        select(PlanOverride).where(
            PlanOverride.plan_item_id == entity_id, PlanOverride.month == month
        )
    )
    # null + no cancellation/date explicitly means inherit and removes the exception; zero remains an explicit value.
    if body.amount_minor is None and not body.cancelled and body.moved_date is None:
        if existing:
            db.delete(existing)
            item.version += 1
        db.commit()
        return {
            "plan_item_id": entity_id,
            "month": month,
            "inherited": True,
            "version": item.version,
        }
    value = existing or PlanOverride(plan_item_id=entity_id, month=month)
    value.amount_minor, value.cancelled, value.moved_date = (
        body.amount_minor,
        body.cancelled,
        body.moved_date,
    )
    db.add(value)
    item.version += 1
    db.commit()
    db.refresh(value)
    return {
        "id": value.id,
        "plan_item_id": entity_id,
        "month": month,
        "amount_minor": value.amount_minor,
        "cancelled": value.cancelled,
        "moved_date": value.moved_date,
        "version": item.version,
    }


@router.post("/plan-items/{entity_id}/matches", status_code=201)
def match_plan(
    entity_id: int,
    body: MatchInput,
    idempotency_key: str | None = Header(None),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    request = {"entity_id": entity_id, **body.model_dump()}
    prior = idempotent_existing(db, idempotency_key, request)
    if prior:
        return prior
    if not db.get(PlanItem, entity_id):
        missing("Plan item")
    plan = db.get(PlanItem, entity_id)
    transaction = db.get(Transaction, body.transaction_id)
    if not transaction:
        missing("Transaction")
    expected_transaction_type = "income" if plan.kind == "income" else "expense"
    if transaction.type != expected_transaction_type:
        raise HTTPException(status_code=422, detail="Transaction type does not match plan item")
    account = db.get(Account, transaction.account_id)
    if not account or account.currency != plan.currency:
        raise HTTPException(status_code=422, detail="Валюта операции не совпадает с валютой плана")
    if transaction.external_source and transaction.external_source.startswith("loan_schedule:"):
        raise HTTPException(
            status_code=422,
            detail="Loan schedule payments cannot also be matched to a separate plan item",
        )
    if body.amount_minor > transaction.amount_minor:
        raise HTTPException(status_code=422, detail="Matched amount exceeds transaction amount")
    if db.scalar(select(SalaryMatch.id).where(SalaryMatch.transaction_id == transaction.id)):
        raise HTTPException(status_code=409, detail="Transaction is already matched to salary")
    overrides = {
        (override.plan_item_id, override.month): override
        for override in db.scalars(
            select(PlanOverride).where(
                PlanOverride.plan_item_id == entity_id,
                PlanOverride.month == body.occurrence_month,
            )
        ).all()
    }
    if effective_plan_amount(plan, body.occurrence_month, overrides) is None:
        raise HTTPException(
            status_code=422, detail="Plan item has no active occurrence in that month"
        )
    ensure_open(db, month_date(body.occurrence_month))
    if plan.funding_source == "goal":
        if transaction.goal_id != plan.goal_id:
            raise HTTPException(status_code=422, detail="Transaction goal does not match plan item")
    elif transaction.goal_id is not None:
        raise HTTPException(
            status_code=422, detail="Goal transaction cannot match a free-money plan"
        )
    value = PlanMatch(plan_item_id=entity_id, **body.model_dump())
    db.add(value)
    db.flush()
    output = {"id": value.id, **request}
    store_idempotent(db, idempotency_key, request, output)
    db.commit()
    return output


@router.get("/budget-limits")
def list_limits(_=Depends(require_user), db: Session = Depends(get_db)) -> dict:
    items = db.scalars(select(BudgetLimit).order_by(BudgetLimit.id)).all()
    return {"items": [BudgetLimitOut.model_validate(x) for x in items], "total": len(items)}


@router.post("/budget-limits", response_model=BudgetLimitOut, status_code=201)
def create_limit(body: BudgetLimitCreate, _=Depends(require_csrf), db: Session = Depends(get_db)):
    ensure_category_kind(db, body.category_id, "expense")
    ensure_open(db, month_date(body.start_month))
    value = BudgetLimit(**body.model_dump())
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


@router.post("/budget-limits/batch")
def batch_limits(body: dict, _=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    changes = body.get("changes")
    if not isinstance(changes, list) or not changes:
        raise HTTPException(status_code=422, detail="changes must be a non-empty list")
    validated = []
    for change in changes:
        try:
            category_id, month, amount = (
                int(change["category_id"]),
                str(change["month"]),
                int(change["amount_minor"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="Each change requires category_id, month, amount_minor"
            ) from exc
        if len(month) != 7 or amount < 0:
            raise HTTPException(status_code=422, detail="Invalid month or amount_minor")
        ensure_open(db, month_date(month))
        ensure_category_kind(db, category_id, "expense")
        validated.append((category_id, month, amount))
    results = []
    for category_id, month, amount in validated:
        limits = db.scalars(
            select(BudgetLimit).where(
                BudgetLimit.category_id == category_id,
                BudgetLimit.start_month <= month,
                (BudgetLimit.end_month.is_(None)) | (BudgetLimit.end_month >= month),
            )
        ).all()
        if limits:
            limit = max(limits, key=lambda x: x.start_month)
            override = db.scalar(
                select(BudgetLimitOverride).where(
                    BudgetLimitOverride.budget_limit_id == limit.id,
                    BudgetLimitOverride.month == month,
                )
            )
            if not override:
                override = BudgetLimitOverride(
                    budget_limit_id=limit.id, month=month, amount_minor=amount
                )
            else:
                override.amount_minor = amount
            db.add(override)
            results.append(
                {
                    "category_id": category_id,
                    "month": month,
                    "amount_minor": amount,
                    "mode": "override",
                }
            )
        else:
            db.add(
                BudgetLimit(
                    category_id=category_id, amount_minor=amount, start_month=month, end_month=month
                )
            )
            results.append(
                {
                    "category_id": category_id,
                    "month": month,
                    "amount_minor": amount,
                    "mode": "one_month",
                }
            )
    db.commit()
    return {"changes": results}


def goal_output(db: Session, goal: Goal) -> dict:
    value = GoalOut.model_validate(goal).model_dump()
    value["reserved_minor"] = goal_reserved(db, goal)
    remaining = goal_remaining_need(db, goal)
    value["remaining_need_minor"] = remaining
    settings = settings_for_user(db)
    try:
        user_timezone = ZoneInfo(settings.timezone if settings else "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        user_timezone = timezone.utc
    today = datetime.now(user_timezone).date()
    contribution_count = 0
    if goal.target_date and goal.target_date >= today:
        contribution_count = (
            (goal.target_date.year - today.year) * 12 + goal.target_date.month - today.month + 1
        )
    schedule = split_evenly(remaining, contribution_count)
    value["recommended_contribution_minor"] = schedule[0] if schedule else None
    value["recommendation_status"] = (
        "insufficient_by_deadline" if remaining and not schedule else "on_track"
    )
    return value


@router.get("/goals")
def list_goals(
    include_archived: bool = False, _=Depends(require_user), db: Session = Depends(get_db)
) -> dict:
    statement = select(Goal).order_by(Goal.priority.asc(), Goal.id)
    if not include_archived:
        statement = statement.where(Goal.archived.is_(False))
    items = db.scalars(statement).all()
    return {"items": [goal_output(db, x) for x in items], "total": len(items)}


@router.post("/goals", status_code=201)
def create_goal(body: GoalCreate, _=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    settings = settings_for_user(db)
    accounting_start = settings.accounting_start_date if settings else date.today()
    opening_cash = sum(
        account.initial_balance_minor
        for account in db.scalars(
            select(Account).where(
                Account.initial_balance_date <= accounting_start,
                Account.currency == (settings.currency if settings else "RUB"),
            )
        ).all()
    )
    opening_reserved = sum(goal.initial_reserved_minor for goal in db.scalars(select(Goal)).all())
    available_opening_cash = max(0, opening_cash - opening_reserved)
    if body.initial_reserved_minor > available_opening_cash:
        raise HTTPException(
            status_code=409,
            detail="Начальный резерв цели превышает свободные деньги на дату начала учёта",
        )
    value = Goal(**body.model_dump())
    db.add(value)
    db.commit()
    db.refresh(value)
    return goal_output(db, value)


@router.patch("/goals/{entity_id}")
def update_goal(
    entity_id: int, body: GoalUpdate, _=Depends(require_csrf), db: Session = Depends(get_db)
) -> dict:
    value = db.get(Goal, entity_id)
    if not value:
        missing("Goal")
    if value.version != body.version:
        raise HTTPException(status_code=409, detail="Version conflict; reload and retry")
    data = body.model_dump(
        exclude_unset=True,
        exclude={"version", "reserve_disposition", "reserve_date"},
    )
    finishing = data.get("archived") is True or data.get("status") in ("completed", "archived")
    reserve = goal_reserved(db, value)
    if finishing and reserve:
        if body.reserve_disposition is None:
            raise HTTPException(
                status_code=422,
                detail="Choose whether to keep or release the remaining goal reserve",
            )
        if body.reserve_disposition == "keep" and body.reserve_date is not None:
            raise HTTPException(status_code=422, detail="reserve_date is only used for release")
        if body.reserve_disposition == "release":
            if body.reserve_date is None:
                raise HTTPException(status_code=422, detail="reserve_date is required for release")
            ensure_open(db, body.reserve_date)
            db.add(
                GoalReserveMovement(
                    goal_id=value.id,
                    kind="release",
                    amount_minor=reserve,
                    date=body.reserve_date,
                    comment="Released when goal was completed or archived",
                )
            )
    elif body.reserve_disposition is not None or body.reserve_date is not None:
        raise HTTPException(
            status_code=422,
            detail="Reserve disposition is only valid when completing or archiving a goal",
        )
    for key, val in data.items():
        setattr(value, key, val)
    value.version += 1
    db.commit()
    db.refresh(value)
    return goal_output(db, value)


@router.delete("/goals/{entity_id}", status_code=204)
def delete_goal(
    entity_id: int,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    value = db.get(Goal, entity_id)
    if not value:
        missing("Goal")
    ensure_version(value, version)
    has_references = value.initial_reserved_minor > 0 or any(
        (
            db.scalar(
                select(func.count())
                .select_from(GoalReserveMovement)
                .where(GoalReserveMovement.goal_id == entity_id)
            ),
            db.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.goal_id == entity_id)
            ),
            db.scalar(
                select(func.count()).select_from(PlanItem).where(PlanItem.goal_id == entity_id)
            ),
        )
    )
    if has_references:
        raise HTTPException(
            status_code=409,
            detail="Goal has reserve or financial history; archive it instead",
        )
    audit_delete(db, "goal", value)
    db.delete(value)
    db.commit()
    return Response(status_code=204)


@router.get("/goals/{entity_id}/recommendation")
def goal_recommendation(
    entity_id: int,
    contributions: int = Query(ge=0, le=120),
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    goal = db.get(Goal, entity_id)
    if not goal:
        missing("Goal")
    need = goal_remaining_need(db, goal)
    return {
        "goal_id": entity_id,
        "remaining_need_minor": need,
        "contributions": split_evenly(need, contributions),
        "status": "insufficient_by_deadline" if need and not contributions else "on_track",
    }


@router.get("/goals/{entity_id}/allocations")
def list_goal_movements(
    entity_id: int, _=Depends(require_user), db: Session = Depends(get_db)
) -> dict:
    items = db.scalars(
        select(GoalReserveMovement)
        .where(GoalReserveMovement.goal_id == entity_id)
        .order_by(GoalReserveMovement.date)
    ).all()
    return {"items": [GoalMovementOut.model_validate(x) for x in items], "total": len(items)}


@router.post("/goals/{entity_id}/allocations", status_code=201)
def move_goal_reserve(
    entity_id: int,
    body: GoalMovementCreate,
    idempotency_key: str | None = Header(None),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    request = {"goal_id": entity_id, **body.model_dump()}
    prior = idempotent_existing(db, idempotency_key, request)
    if prior:
        return prior
    goal = db.get(Goal, entity_id)
    if not goal:
        missing("Goal")
    ensure_open(db, body.date)
    reserve = goal_reserved(db, goal, body.date)
    if body.kind == "allocation":
        free_cash = cash_balance_through(db, body.date) - total_reserved_through(db, body.date)
        if body.amount_minor > free_cash:
            raise HTTPException(
                status_code=409, detail="Goal allocation exceeds money outside goals"
            )
    if body.kind in ("release", "expense") and body.amount_minor > reserve:
        if body.kind != "expense" or not body.allow_allocate_shortfall:
            raise HTTPException(status_code=409, detail="Goal reserve is insufficient")
        shortfall = body.amount_minor - reserve
        free_cash = cash_balance_through(db, body.date) - total_reserved_through(db, body.date)
        if shortfall > free_cash:
            raise HTTPException(
                status_code=409, detail="Goal allocation exceeds money outside goals"
            )
        db.add(
            GoalReserveMovement(
                goal_id=entity_id,
                kind="allocation",
                amount_minor=shortfall,
                date=body.date,
                comment="Automatic allocation confirmed with goal expense",
            )
        )
    if body.kind == "refund":
        net_spent = sum(
            movement.amount_minor if movement.kind == "expense" else -movement.amount_minor
            for movement in db.scalars(
                select(GoalReserveMovement).where(
                    GoalReserveMovement.goal_id == entity_id,
                    GoalReserveMovement.date <= body.date,
                    GoalReserveMovement.kind.in_(("expense", "refund")),
                )
            ).all()
        )
        if body.amount_minor > net_spent:
            raise HTTPException(status_code=409, detail="Goal refund exceeds prior goal expenses")
    transaction_id = None
    if body.kind in ("expense", "refund"):
        if not body.account_id:
            raise HTTPException(
                status_code=422, detail="account_id is required for goal expense/refund"
            )
        account = db.get(Account, body.account_id)
        if not account:
            missing("Account")
        settings = settings_for_user(db)
        if account.currency != (settings.currency if settings else "RUB"):
            raise HTTPException(status_code=422, detail="Операции с резервом цели требуют счёт в основной валюте")
        ensure_transaction_account_date(account, body.date)
        ensure_category_kind(db, body.category_id, "expense")
        tx = Transaction(
            type=body.kind,
            amount_minor=body.amount_minor,
            date=body.date,
            account_id=body.account_id,
            category_id=body.category_id,
            goal_id=entity_id,
            description=body.description,
            comment=body.comment,
        )
        db.add(tx)
        db.flush()
        transaction_id = tx.id
    value = GoalReserveMovement(
        goal_id=entity_id,
        kind=body.kind,
        amount_minor=body.amount_minor,
        date=body.date,
        transaction_id=transaction_id,
        comment=body.comment,
    )
    db.add(value)
    db.flush()
    output = GoalMovementOut.model_validate(value).model_dump(mode="json")
    store_idempotent(db, idempotency_key, request, output)
    db.commit()
    return output


@router.get("/loans")
def list_loans(
    include_archived: bool = False, _=Depends(require_user), db: Session = Depends(get_db)
) -> dict:
    statement = select(Loan).order_by(Loan.id)
    if not include_archived:
        statement = statement.where(Loan.archived.is_(False))
    loans = db.scalars(statement).all()
    items = []
    for loan in loans:
        value = LoanOut.model_validate(loan).model_dump(mode="json")
        schedule = db.scalars(
            select(LoanScheduleItem).where(LoanScheduleItem.loan_id == loan.id)
        ).all()
        value["schedule_remaining_minor"] = sum(
            max(0, item.amount_minor - item.paid_minor)
            for item in schedule
            if item.status not in ("paid", "cancelled")
        )
        payments = db.scalars(
            select(Transaction).where(Transaction.loan_id == loan.id, Transaction.type == "expense")
        ).all()
        value["paid_total_minor"] = sum(payment.amount_minor for payment in payments)
        value["paid_principal_minor"] = sum(
            payment.principal_component_minor or 0 for payment in payments
        )
        value["paid_interest_minor"] = sum(
            payment.interest_component_minor or 0 for payment in payments
        )
        value["paid_unclassified_minor"] = (
            value["paid_total_minor"] - value["paid_principal_minor"] - value["paid_interest_minor"]
        )
        if loan.schedule_mode == "auto" and loan.principal_minor:
            projection = projected_loan(loan)
            value["schedule_remaining_minor"] = projection.total_minor
            value["projected_interest_minor"] = projection.interest_minor
            value["projected_payoff_date"] = (
                projection.payoff_date.isoformat() if projection.payoff_date else None
            )
        items.append(value)
    return {"items": items, "total": len(items)}


def projected_loan(loan: Loan, **early: object):
    if (
        loan.schedule_mode != "auto"
        or loan.principal_minor is None
        or loan.principal_as_of is None
        or loan.annual_rate_bps is None
        or loan.first_payment_date is None
        or loan.end_date is None
    ):
        raise HTTPException(
            status_code=422, detail="Для расчёта заполните долг, ставку и даты кредита"
        )
    try:
        dates = monthly_dates(loan.first_payment_date, loan.end_date, loan.principal_as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if loan.principal_minor and not dates:
        raise HTTPException(status_code=422, detail="После даты остатка долга нет будущих платежей")
    try:
        return project_loan(
            loan.principal_minor,
            loan.annual_rate_bps,
            loan.interest_method,
            loan.principal_as_of,
            dates,
            regular_payment_minor=loan.annuity_payment_minor,
            **early,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def configure_loan_schedule(loan: Loan) -> None:
    if loan.schedule_mode != "auto":
        loan.annuity_payment_minor = None
        return
    if (
        loan.principal_minor is None
        or loan.principal_as_of is None
        or loan.annual_rate_bps is None
        or loan.first_payment_date is None
        or loan.end_date is None
    ):
        raise HTTPException(
            status_code=422,
            detail="Для аннуитетного графика укажите остаток долга, дату, ставку, первый платёж и срок",
        )
    try:
        dates = monthly_dates(loan.first_payment_date, loan.end_date, loan.principal_as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if loan.principal_minor and not dates:
        raise HTTPException(status_code=422, detail="Первый платёж должен быть после даты долга")
    try:
        loan.annuity_payment_minor = annuity_payment(
            loan.principal_minor,
            loan.annual_rate_bps,
            loan.interest_method,
            loan.principal_as_of,
            dates,
        )
        project_loan(
            loan.principal_minor,
            loan.annual_rate_bps,
            loan.interest_method,
            loan.principal_as_of,
            dates,
            regular_payment_minor=loan.annuity_payment_minor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/loans", response_model=LoanOut, status_code=201)
def create_loan(body: LoanCreate, _=Depends(require_csrf), db: Session = Depends(get_db)):
    if body.account_id:
        account = db.get(Account, body.account_id)
        if not account:
            missing("Account")
        settings = settings_for_user(db)
        if account.currency != (settings.currency if settings else "RUB"):
            raise HTTPException(status_code=422, detail="Кредитный счёт должен быть в основной валюте")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(status_code=422, detail="end_date cannot precede start_date")
    value = Loan(**body.model_dump())
    configure_loan_schedule(value)
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


@router.patch("/loans/{entity_id}", response_model=LoanOut)
def update_loan(
    entity_id: int,
    body: LoanUpdate,
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Loan:
    value = db.get(Loan, entity_id)
    if not value:
        missing("Loan")
    ensure_version(value, body.version)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    changed = {key for key, val in data.items() if val != getattr(value, key)}
    if "name" in data and data["name"] is None:
        raise HTTPException(status_code=422, detail="name cannot be null")
    if data.get("archived") is True:
        if value.schedule_mode == "auto" and (value.principal_minor or 0) > 0:
            raise HTTPException(status_code=409, detail="Сначала погасите остаток кредита")
        remaining_schedule = db.scalar(
            select(func.count())
            .select_from(LoanScheduleItem)
            .where(
                LoanScheduleItem.loan_id == entity_id,
                LoanScheduleItem.status.not_in(("paid", "cancelled")),
                LoanScheduleItem.paid_minor < LoanScheduleItem.amount_minor,
            )
        )
        if remaining_schedule:
            raise HTTPException(
                status_code=409,
                detail="Loan has remaining scheduled payments; pay or cancel them before archiving",
            )
    if "account_id" in data and data["account_id"] is not None:
        account = db.get(Account, data["account_id"])
        if not account:
            missing("Account")
        settings = settings_for_user(db)
        if account.currency != (settings.currency if settings else "RUB"):
            raise HTTPException(status_code=422, detail="Кредитный счёт должен быть в основной валюте")
    start_date = data.get("start_date", value.start_date)
    end_date = data.get("end_date", value.end_date)
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date cannot precede start_date")
    if changed & {"schedule_mode", "first_payment_date"}:
        existing_rows = db.scalar(
            select(func.count())
            .select_from(LoanScheduleItem)
            .where(LoanScheduleItem.loan_id == entity_id)
        )
        if existing_rows and data.get("schedule_mode", value.schedule_mode) == "auto":
            raise HTTPException(status_code=409, detail="Сначала удалите ручной график кредита")
    if {"principal_minor", "principal_as_of"} & changed:
        if value.principal_as_of:
            ensure_open(db, value.principal_as_of)
        principal_as_of = data.get("principal_as_of", value.principal_as_of)
        if principal_as_of:
            ensure_open(db, principal_as_of)
    for key, val in data.items():
        setattr(value, key, val)
    if value.interest_method is None or value.schedule_mode is None:
        raise HTTPException(status_code=422, detail="Способ расчёта не может быть пустым")
    if changed & {
        "principal_minor",
        "principal_as_of",
        "annual_rate_bps",
        "interest_method",
        "schedule_mode",
        "first_payment_date",
        "end_date",
    }:
        configure_loan_schedule(value)
    value.version += 1
    db.commit()
    db.refresh(value)
    return value


@router.delete("/loans/{entity_id}", status_code=204)
def delete_loan(
    entity_id: int,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    value = db.get(Loan, entity_id)
    if not value:
        missing("Loan")
    ensure_version(value, version)
    if db.scalar(
        select(func.count())
        .select_from(LoanScheduleItem)
        .where(LoanScheduleItem.loan_id == entity_id)
    ):
        raise HTTPException(
            status_code=409,
            detail="Loan has schedule or payment history; archive it instead",
        )
    if db.scalar(
        select(func.count()).select_from(PlanItem).where(PlanItem.loan_id == entity_id)
    ) or db.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.loan_id == entity_id)
    ):
        raise HTTPException(status_code=409, detail="Кредит связан с платежами; архивируйте его")
    effective_date = value.principal_as_of or value.start_date
    if effective_date:
        ensure_open(db, effective_date)
    audit_delete(db, "loan", value)
    db.delete(value)
    db.commit()
    return Response(status_code=204)


@router.get("/loans/{entity_id}/schedule")
def list_schedule(entity_id: int, _=Depends(require_user), db: Session = Depends(get_db)) -> dict:
    items = db.scalars(
        select(LoanScheduleItem)
        .where(LoanScheduleItem.loan_id == entity_id)
        .order_by(LoanScheduleItem.due_date)
    ).all()
    output = []
    today = date.today()
    for item in items:
        value = LoanScheduleOut.model_validate(item).model_dump(mode="json")
        remaining = (
            0
            if item.status in ("paid", "cancelled")
            else max(0, item.amount_minor - item.paid_minor)
        )
        value["remaining_minor"] = remaining
        value["overdue"] = bool(remaining and item.due_date < today)
        output.append(value)
    return {"items": output, "total": len(output)}


@router.get("/loans/{entity_id}/projection")
def get_loan_projection(
    entity_id: int,
    early_payment_date: date | None = None,
    early_amount_minor: int | None = Query(None, gt=0),
    early_strategy: str | None = None,
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    loan = db.get(Loan, entity_id)
    if not loan:
        missing("Loan")
    baseline = projected_loan(loan)
    result = {"baseline": jsonable_encoder(baseline)}
    if early_payment_date is None and early_amount_minor is None and early_strategy is None:
        return result
    if not (early_payment_date and early_amount_minor and early_strategy):
        raise HTTPException(
            status_code=422, detail="Укажите дату, сумму и вариант досрочного платежа"
        )
    if early_strategy not in ("reduce_term", "reduce_payment"):
        raise HTTPException(status_code=422, detail="Неизвестный вариант досрочного погашения")
    row = next((row for row in baseline.rows if row.due_date == early_payment_date), None)
    if row is None or row.remaining_principal_minor < early_amount_minor:
        raise HTTPException(
            status_code=422,
            detail="Досрочный платёж должен приходиться на дату графика и не превышать остаток долга",
        )
    scenario = projected_loan(
        loan,
        early_payment_date=early_payment_date,
        early_principal_minor=early_amount_minor,
        early_strategy=early_strategy,
    )
    result["scenario"] = jsonable_encoder(scenario)
    result["interest_savings_minor"] = baseline.interest_minor - scenario.interest_minor
    return result


def ensure_loan_schedule_mutable(loan: Loan) -> None:
    if loan.archived:
        raise HTTPException(
            status_code=409,
            detail="Loan is archived; restore it before changing its schedule",
        )
    if loan.schedule_mode == "auto":
        raise HTTPException(
            status_code=409,
            detail="У кредита автоматический график; ручные строки доступны после переключения режима",
        )


@router.post("/loans/{entity_id}/schedule", response_model=LoanScheduleOut, status_code=201)
def create_schedule(
    entity_id: int, body: LoanScheduleCreate, _=Depends(require_csrf), db: Session = Depends(get_db)
):
    loan = db.get(Loan, entity_id)
    if not loan:
        missing("Loan")
    ensure_loan_schedule_mutable(loan)
    ensure_open(db, body.due_date)
    value = LoanScheduleItem(loan_id=entity_id, **body.model_dump())
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


@router.patch("/loans/{loan_id}/schedule/{item_id}", response_model=LoanScheduleOut)
def update_schedule(
    loan_id: int,
    item_id: int,
    body: LoanScheduleUpdate,
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> LoanScheduleItem:
    loan = db.get(Loan, loan_id)
    if not loan:
        missing("Loan")
    value = db.get(LoanScheduleItem, item_id)
    if not value or value.loan_id != loan_id:
        missing("Loan schedule item")
    ensure_loan_schedule_mutable(loan)
    ensure_version(value, body.version)
    if value.paid_minor != 0 or value.status not in ("planned", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail="A schedule item with payment history cannot be edited",
        )
    ensure_open(db, value.due_date)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    for required_field in ("due_date", "amount_minor", "status"):
        if required_field in data and data[required_field] is None:
            raise HTTPException(status_code=422, detail=f"{required_field} cannot be null")
    due_date = data.get("due_date", value.due_date)
    amount_minor = data.get("amount_minor", value.amount_minor)
    principal_minor = data.get("principal_minor", value.principal_minor) or 0
    interest_minor = data.get("interest_minor", value.interest_minor) or 0
    if principal_minor + interest_minor > amount_minor:
        raise HTTPException(
            status_code=422,
            detail="principal and interest cannot exceed the payment amount",
        )
    ensure_open(db, due_date)
    for key, val in data.items():
        setattr(value, key, val)
    value.version += 1
    db.commit()
    db.refresh(value)
    return value


@router.delete("/loans/{loan_id}/schedule/{item_id}", status_code=204)
def delete_schedule(
    loan_id: int,
    item_id: int,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    loan = db.get(Loan, loan_id)
    if not loan:
        missing("Loan")
    value = db.get(LoanScheduleItem, item_id)
    if not value or value.loan_id != loan_id:
        missing("Loan schedule item")
    ensure_loan_schedule_mutable(loan)
    ensure_version(value, version)
    if value.status != "planned" or value.paid_minor != 0:
        raise HTTPException(
            status_code=409,
            detail="Only an unpaid planned schedule item can be deleted; cancel it instead",
        )
    if db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.external_source == f"loan_schedule:{item_id}")
    ):
        raise HTTPException(
            status_code=409,
            detail="Loan schedule item has payment history and cannot be deleted",
        )
    ensure_open(db, value.due_date)
    audit_delete(db, "loan_schedule_item", value)
    db.delete(value)
    db.commit()
    return Response(status_code=204)


@router.post("/loans/{loan_id}/schedule/{item_id}/payments", status_code=201)
def pay_loan_schedule_item(
    loan_id: int,
    item_id: int,
    body: LoanPaymentCreate,
    idempotency_key: str | None = Header(None),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    request = {"loan_id": loan_id, "schedule_item_id": item_id, **body.model_dump()}
    prior = idempotent_existing(db, idempotency_key, request)
    if prior:
        return prior
    loan = db.get(Loan, loan_id)
    if not loan:
        missing("Loan")
    item = db.get(LoanScheduleItem, item_id)
    if not item or item.loan_id != loan_id:
        missing("Loan schedule item")
    ensure_loan_schedule_mutable(loan)
    if item.status == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled loan payment cannot be fulfilled")
    ensure_open(db, body.date)
    account_id = body.account_id or loan.account_id
    if not account_id:
        raise HTTPException(status_code=422, detail="account_id is required for loan payment")
    account = db.get(Account, account_id)
    if not account:
        missing("Account")
    settings = settings_for_user(db)
    if account.currency != (settings.currency if settings else "RUB"):
        raise HTTPException(status_code=422, detail="Кредитный платёж требует счёт в основной валюте")
    ensure_transaction_account_date(account, body.date)
    ensure_category_kind(db, body.category_id, "expense")
    if body.principal_minor is not None and loan.principal_minor is not None:
        if body.principal_minor > loan.principal_minor:
            raise HTTPException(
                status_code=409, detail="Principal payment exceeds outstanding debt"
            )
        loan.principal_minor -= body.principal_minor
        loan.principal_as_of = body.date
        loan.version += 1
    transaction = Transaction(
        type="expense",
        amount_minor=body.amount_minor,
        date=body.date,
        account_id=account_id,
        category_id=body.category_id,
        loan_id=loan.id,
        principal_component_minor=body.principal_minor,
        interest_component_minor=body.interest_minor,
        loan_balance_applied=body.principal_minor is not None and loan.principal_minor is not None,
        description=loan.name,
        comment=body.comment,
        external_source=f"loan_schedule:{item.id}",
    )
    db.add(transaction)
    item.paid_minor += body.amount_minor
    item.status = (
        "paid" if body.completed or item.paid_minor >= item.amount_minor else "partially_paid"
    )
    item.version += 1
    db.flush()
    output = {
        "transaction_id": transaction.id,
        "schedule_item": LoanScheduleOut.model_validate(item).model_dump(mode="json"),
        "loan_principal_minor": loan.principal_minor,
        "loan_principal_as_of": loan.principal_as_of.isoformat() if loan.principal_as_of else None,
    }
    store_idempotent(db, idempotency_key, request, output)
    db.commit()
    return output


@router.post("/loans/{loan_id}/transactions/{transaction_id}/link")
def link_existing_loan_transaction(
    loan_id: int,
    transaction_id: int,
    body: LoanTransactionLink,
    idempotency_key: str | None = Header(None),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    request = {"loan_id": loan_id, "transaction_id": transaction_id, **body.model_dump()}
    prior = idempotent_existing(db, idempotency_key, request)
    if prior:
        return prior
    loan = db.get(Loan, loan_id)
    transaction = db.get(Transaction, transaction_id)
    if not loan:
        missing("Loan")
    if not transaction:
        missing("Transaction")
    settings = settings_for_user(db)
    account = db.get(Account, transaction.account_id)
    if not account or account.currency != (settings.currency if settings else "RUB"):
        raise HTTPException(status_code=422, detail="Кредитный платёж должен быть в основной валюте бюджета")
    if (
        loan.archived
        or transaction.type != "expense"
        or transaction.loan_id is not None
        or transaction.goal_id is not None
    ):
        raise HTTPException(status_code=409, detail="Платёж нельзя связать с этим кредитом")
    if transaction.external_source and transaction.external_source.startswith("loan_schedule:"):
        raise HTTPException(status_code=409, detail="Платёж уже относится к графику кредита")
    principal_part = body.principal_minor or 0
    interest_part = body.interest_minor or 0
    if principal_part + interest_part > transaction.amount_minor:
        raise HTTPException(status_code=422, detail="Долг и проценты превышают сумму платежа")
    if body.already_reflected_in_balance and body.prepayment_strategy:
        raise HTTPException(
            status_code=422,
            detail="Пересчёт досрочного погашения доступен только для нового изменения долга",
        )
    if not body.already_reflected_in_balance:
        ensure_open(db, transaction.date)
        if body.principal_minor is None:
            raise HTTPException(status_code=422, detail="Укажите часть платежа в основной долг")
        if (
            loan.schedule_mode != "auto"
            or loan.principal_minor is None
            or loan.principal_as_of is None
        ):
            raise HTTPException(status_code=422, detail="Автоматический расчёт кредита не настроен")
        if transaction.date < loan.principal_as_of or principal_part > loan.principal_minor:
            raise HTTPException(
                status_code=409,
                detail="Дата платежа или погашение долга не согласуется с текущим остатком",
            )
        loan.principal_minor -= principal_part
        loan.principal_as_of = transaction.date
        if body.prepayment_strategy == "reduce_payment" and loan.principal_minor:
            dates = monthly_dates(loan.first_payment_date, loan.end_date, transaction.date)
            loan.annuity_payment_minor = annuity_payment(
                loan.principal_minor,
                loan.annual_rate_bps,
                loan.interest_method,
                transaction.date,
                dates,
            )
        if loan.principal_minor == 0:
            loan.annuity_payment_minor = 0
        loan.version += 1
    transaction.loan_id = loan_id
    transaction.principal_component_minor = body.principal_minor
    transaction.interest_component_minor = body.interest_minor
    transaction.prepayment_strategy = body.prepayment_strategy
    transaction.loan_balance_applied = not body.already_reflected_in_balance
    transaction.version += 1
    output = {
        "transaction_id": transaction.id,
        "loan_id": loan.id,
        "principal_component_minor": transaction.principal_component_minor,
        "interest_component_minor": transaction.interest_component_minor,
        "loan_principal_minor": loan.principal_minor,
    }
    store_idempotent(db, idempotency_key, request, output)
    db.commit()
    return output


@router.delete("/loans/{loan_id}/transactions/{transaction_id}/link", status_code=204)
def unlink_historical_loan_transaction(
    loan_id: int,
    transaction_id: int,
    version: int = Query(ge=1),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    transaction = db.get(Transaction, transaction_id)
    if not transaction or transaction.loan_id != loan_id:
        missing("Loan payment link")
    ensure_version(transaction, version)
    if transaction.loan_balance_applied is not False:
        raise HTTPException(
            status_code=409,
            detail="Этот платёж изменил остаток долга; связь нельзя удалить отдельно",
        )
    transaction.loan_id = None
    transaction.principal_component_minor = None
    transaction.interest_component_minor = None
    transaction.prepayment_strategy = None
    transaction.loan_balance_applied = None
    transaction.version += 1
    db.commit()
    return Response(status_code=204)


@router.post("/months/{month}/close")
def close_month(month: str, _=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    month_date(month)
    value = budget_month_for_user(db, month)
    if value and value.status == "closed":
        return {"month": month, "status": "closed", "version": value.version}
    if value is None:
        value = BudgetMonth(month=month, version=1)
    else:
        value.version += 1
    value.status = "closed"
    value.closed_at = datetime.now(timezone.utc)
    db.add(value)
    db.add(
        AuditLog(
            entity_type="budget_month",
            entity_id=month,
            action="close",
            before_json=None,
            after_json='{"status":"closed"}',
        )
    )
    db.commit()
    return {"month": month, "status": "closed", "version": value.version}


@router.post("/months/{month}/reopen")
def reopen_month(month: str, _=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    month_date(month)
    value = budget_month_for_user(db, month)
    if not value:
        missing("Budget month")
    if value.status == "open":
        return {"month": month, "status": "open", "version": value.version}
    value.status = "open"
    value.closed_at = None
    value.version += 1
    db.add(
        AuditLog(
            entity_type="budget_month",
            entity_id=month,
            action="reopen",
            before_json='{"status":"closed"}',
            after_json='{"status":"open"}',
        )
    )
    db.commit()
    return {"month": month, "status": "open", "version": value.version}


@router.get("/forecast")
def forecast(
    from_month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    months: int = Query(12, ge=1, le=120),
    include_possible: bool = False,
    currency: str | None = Query(None, pattern=r"^[A-Z]{3}$"),
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    if currency is not None and currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=422, detail="Unsupported currency")
    return calculate_forecast(db, from_month, months, include_possible, currency=currency)


@router.get("/forecast/converted")
def converted_forecast(
    from_month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    months: int = Query(12, ge=1, le=120),
    include_possible: bool = False,
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    settings = settings_for_user(db)
    base_currency = settings.currency if settings else "RUB"
    currencies = {base_currency}
    currencies.update(db.scalars(select(Account.currency).distinct()).all())
    currencies.update(db.scalars(select(PlanItem.currency).distinct()).all())
    rates = parse_display_rates(settings.display_rates_json if settings else "{}", base_currency)
    missing_rates = sorted(currencies - set(rates))
    if missing_rates:
        raise HTTPException(
            status_code=409,
            detail=f"Задайте курсы в настройках: {', '.join(missing_rates)}",
        )
    forecasts = {
        currency: calculate_forecast(db, from_month, months, include_possible, currency=currency)
        for currency in sorted(currencies)
    }
    warnings = set().union(*(forecast["warnings"] for forecast in forecasts.values()))
    if any(forecast["months"] for forecast in forecasts.values()):
        warnings.discard("no_accounts")
    return {
        "from_month": from_month,
        "currency": base_currency,
        "mode": "converted",
        "indicative": True,
        "rate_source": "manual",
        "rates": {currency: format(rates[currency], "f") for currency in currencies},
        "months": combine_forecasts(forecasts, base_currency, rates),
        "warnings": sorted(warnings),
    }


@router.get("/reports/monthly")
def monthly_report(
    from_month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    months: int = Query(12, ge=1, le=120),
    include_possible: bool = False,
    currency: str | None = Query(None, pattern=r"^[A-Z]{3}$"),
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    if currency is not None and currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=422, detail="Unsupported currency")
    return calculate_forecast(db, from_month, months, include_possible, currency=currency)
