"""A paginated, day-grouped ledger of transactions and transfers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from ..models import Account, Transaction, Transfer, User
from ..schemas import TransactionOut, TransferOut
from ..security import get_db, require_user


router = APIRouter(tags=["activity"])


def _transaction_matches(search: str):
    return or_(
        Transaction.description.icontains(search, autoescape=True),
        Transaction.comment.icontains(search, autoescape=True),
    )


def _transfer_matches(search: str, user_id: int):
    source_name = select(Account.id).where(
        Account.id == Transfer.from_account_id,
        Account.user_id == user_id,
        Account.name.icontains(search, autoescape=True),
    ).exists()
    target_name = select(Account.id).where(
        Account.id == Transfer.to_account_id,
        Account.user_id == user_id,
        Account.name.icontains(search, autoescape=True),
    ).exists()
    return or_(Transfer.comment.icontains(search, autoescape=True), source_name, target_name)


@router.get("/activity")
def list_activity(
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    term = search.strip()
    transactions = select(
        literal("transaction").label("entry_kind"),
        Transaction.id.label("entry_id"),
        Transaction.date.label("entry_date"),
        Transaction.created_at.label("created_at"),
    ).where(Transaction.user_id == user.id)
    transfers = select(
        literal("transfer").label("entry_kind"),
        Transfer.id.label("entry_id"),
        Transfer.date.label("entry_date"),
        Transfer.created_at.label("created_at"),
    ).where(Transfer.user_id == user.id)
    if term:
        transactions = transactions.where(_transaction_matches(term))
        transfers = transfers.where(_transfer_matches(term, user.id))
    entries = union_all(transactions, transfers).subquery("activity_entries")
    total = db.scalar(select(func.count()).select_from(entries)) or 0
    rows = db.execute(
        select(entries.c.entry_kind, entries.c.entry_id, entries.c.entry_date)
        .order_by(
            entries.c.entry_date.desc(), entries.c.created_at.desc(),
            entries.c.entry_kind.desc(), entries.c.entry_id.desc(),
        )
        .limit(limit).offset(offset)
    ).all()
    if not rows:
        return {"days": [], "total": total, "limit": limit, "offset": offset}

    transaction_ids = [row.entry_id for row in rows if row.entry_kind == "transaction"]
    transfer_ids = [row.entry_id for row in rows if row.entry_kind == "transfer"]
    transaction_items = {
        item.id: item for item in db.scalars(select(Transaction).where(
            Transaction.user_id == user.id, Transaction.id.in_(transaction_ids)
        )).unique().all()
    } if transaction_ids else {}
    transfer_items = {
        item.id: item for item in db.scalars(select(Transfer).where(
            Transfer.user_id == user.id, Transfer.id.in_(transfer_ids)
        )).all()
    } if transfer_ids else {}
    currencies = {
        account.id: account.currency for account in db.scalars(
            select(Account).where(Account.user_id == user.id)
        ).all()
    }
    dates = list(dict.fromkeys(row.entry_date for row in rows))
    day_counts = dict(db.execute(
        select(entries.c.entry_date, func.count())
        .where(entries.c.entry_date.in_(dates))
        .group_by(entries.c.entry_date)
    ).all())

    amount = func.coalesce(Transaction.merchant_amount_minor, Transaction.amount_minor)
    currency = func.coalesce(Transaction.merchant_currency, Account.currency)
    totals_query = select(
        Transaction.date,
        currency.label("currency"),
        func.sum(case((Transaction.type == "income", amount), else_=0)).label("income_minor"),
        func.sum(case(
            (Transaction.type == "expense", amount),
            (Transaction.type == "refund", -amount),
            else_=0,
        )).label("expense_minor"),
    ).join(Account, Account.id == Transaction.account_id).where(
        Transaction.user_id == user.id,
        Account.user_id == user.id,
        Transaction.date.in_(dates),
        Transaction.type.in_(("income", "expense", "refund")),
    )
    if term:
        totals_query = totals_query.where(_transaction_matches(term))
    totals_by_date: dict = {day: [] for day in dates}
    for day, unit, income, expense in db.execute(
        totals_query.group_by(Transaction.date, currency)
        .order_by(Transaction.date.desc(), currency)
    ):
        totals_by_date[day].append({
            "currency": unit,
            "income_minor": int(income or 0),
            "expense_minor": int(expense or 0),
        })

    grouped = {
        day: {"date": day, "total_items": day_counts[day], "totals": totals_by_date[day], "items": []}
        for day in dates
    }
    for row in rows:
        if row.entry_kind == "transaction":
            item = transaction_items[row.entry_id]
            payload = TransactionOut.model_validate(item).model_dump(mode="json")
            payload["account_currency"] = currencies.get(item.account_id)
            grouped[row.entry_date]["items"].append({"kind": "transaction", "transaction": payload})
        else:
            item = transfer_items[row.entry_id]
            grouped[row.entry_date]["items"].append({
                "kind": "transfer", "transfer": TransferOut.model_validate(item).model_dump(mode="json")
            })
    return {"days": list(grouped.values()), "total": total, "limit": limit, "offset": offset}
