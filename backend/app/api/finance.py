from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.calculations import (
    calculate_forecast,
    effective_plan_amount,
    goal_remaining_need,
    goal_reserved,
    projected_plan_occurrences,
    split_evenly,
)
from ..db import get_db
from ..models import (
    Account,
    AppSettings,
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
from ..security import require_csrf, require_user


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
    month = db.get(BudgetMonth, value.strftime("%Y-%m"))
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
    cash = sum(
        account.initial_balance_minor
        for account in db.scalars(
            select(Account).where(Account.initial_balance_date <= through)
        ).all()
    )
    for transaction in db.scalars(select(Transaction).where(Transaction.date <= through)).all():
        cash += (
            transaction.amount_minor
            if transaction.type in ("income", "refund", "adjustment")
            else -transaction.amount_minor
        )
    return cash


def total_reserved_through(db: Session, through: date) -> int:
    return sum(goal_reserved(db, goal, through) for goal in db.scalars(select(Goal)).all())


def ensure_transaction_account_date(account: Account, value: date) -> None:
    if value < account.initial_balance_date:
        raise HTTPException(
            status_code=422,
            detail="Transaction date cannot be before the account opening balance date",
        )


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
    items = []
    for transaction in page:
        item = TransactionOut.model_validate(transaction).model_dump(mode="json")
        match = matches.get(transaction.id)
        if match:
            item.update(
                matched_plan_item_id=match.plan_item_id,
                matched_occurrence_month=match.occurrence_month,
                matched_amount_minor=match.amount_minor,
                match_completed=match.completed,
            )
        items.append(item)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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
    if body.goal_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Goal expenses and refunds must use the atomic goal allocation endpoint",
        )
    if body.type == "adjustment" and body.category_id is not None:
        raise HTTPException(status_code=422, detail="Balance adjustment cannot have a category")
    if body.type != "adjustment":
        ensure_category_kind(
            db,
            body.category_id,
            "income" if body.type == "income" else "expense",
        )
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
    if "amount_minor" in data and value.type != "adjustment":
        matched_amount = db.scalar(
            select(func.coalesce(func.sum(PlanMatch.amount_minor), 0)).where(
                PlanMatch.transaction_id == value.id
            )
        )
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
    value = Transfer(**body.model_dump())
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
    for key, val in data.items():
        setattr(value, key, val)
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
            projected.append(value)
    return {"items": projected, "total": len(projected)}


@router.post("/plan-items", response_model=PlanItemOut, status_code=201)
def create_plan_item(body: PlanItemCreate, _=Depends(require_csrf), db: Session = Depends(get_db)):
    data = body.model_dump()
    tag_ids = data.pop("tag_ids")
    if body.account_id and not db.get(Account, body.account_id):
        missing("Account")
    ensure_category_kind(db, body.category_id, body.kind)
    if body.goal_id and not db.get(Goal, body.goal_id):
        missing("Goal")
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
    if data.get("account_id") and not db.get(Account, data["account_id"]):
        missing("Account")
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
    if not db.get(PlanItem, entity_id):
        missing("Plan item")
    existing = db.scalar(
        select(PlanOverride).where(
            PlanOverride.plan_item_id == entity_id, PlanOverride.month == month
        )
    )
    # null + no cancellation/date explicitly means inherit and removes the exception; zero remains an explicit value.
    if body.amount_minor is None and not body.cancelled and body.moved_date is None:
        if existing:
            db.delete(existing)
        db.commit()
        return {"plan_item_id": entity_id, "month": month, "inherited": True}
    value = existing or PlanOverride(plan_item_id=entity_id, month=month)
    value.amount_minor, value.cancelled, value.moved_date = (
        body.amount_minor,
        body.cancelled,
        body.moved_date,
    )
    db.add(value)
    db.commit()
    db.refresh(value)
    return {
        "id": value.id,
        "plan_item_id": entity_id,
        "month": month,
        "amount_minor": value.amount_minor,
        "cancelled": value.cancelled,
        "moved_date": value.moved_date,
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
    if transaction.external_source and transaction.external_source.startswith("loan_schedule:"):
        raise HTTPException(
            status_code=422,
            detail="Loan schedule payments cannot also be matched to a separate plan item",
        )
    if body.amount_minor > transaction.amount_minor:
        raise HTTPException(status_code=422, detail="Matched amount exceeds transaction amount")
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
    settings = db.get(AppSettings, 1)
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
    settings = db.get(AppSettings, 1)
    accounting_start = settings.accounting_start_date if settings else date.today()
    opening_cash = sum(
        account.initial_balance_minor
        for account in db.scalars(
            select(Account).where(Account.initial_balance_date <= accounting_start)
        ).all()
    )
    opening_reserved = sum(goal.initial_reserved_minor for goal in db.scalars(select(Goal)).all())
    if body.initial_reserved_minor > opening_cash - opening_reserved:
        raise HTTPException(
            status_code=409, detail="Initial goal reserves exceed money outside goals"
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
        items.append(value)
    return {"items": items, "total": len(items)}


@router.post("/loans", response_model=LoanOut, status_code=201)
def create_loan(body: LoanCreate, _=Depends(require_csrf), db: Session = Depends(get_db)):
    if body.account_id and not db.get(Account, body.account_id):
        missing("Account")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(status_code=422, detail="end_date cannot precede start_date")
    value = Loan(**body.model_dump())
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
    if "name" in data and data["name"] is None:
        raise HTTPException(status_code=422, detail="name cannot be null")
    if data.get("archived") is True:
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
        if not db.get(Account, data["account_id"]):
            missing("Account")
    start_date = data.get("start_date", value.start_date)
    end_date = data.get("end_date", value.end_date)
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date cannot precede start_date")
    if {"principal_minor", "principal_as_of"} & data.keys():
        if value.principal_as_of:
            ensure_open(db, value.principal_as_of)
        principal_as_of = data.get("principal_as_of", value.principal_as_of)
        if principal_as_of:
            ensure_open(db, principal_as_of)
    for key, val in data.items():
        setattr(value, key, val)
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


def ensure_loan_schedule_mutable(loan: Loan) -> None:
    if loan.archived:
        raise HTTPException(
            status_code=409,
            detail="Loan is archived; restore it before changing its schedule",
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


@router.post("/months/{month}/close")
def close_month(month: str, _=Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    month_date(month)
    value = db.get(BudgetMonth, month)
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
    value = db.get(BudgetMonth, month)
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
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    return calculate_forecast(db, from_month, months, include_possible)


@router.get("/reports/monthly")
def monthly_report(
    from_month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    months: int = Query(12, ge=1, le=120),
    include_possible: bool = False,
    _=Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    return calculate_forecast(db, from_month, months, include_possible)
