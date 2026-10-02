from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from .. import __version__
from ..core.ru_payroll import SalaryRule as PayrollRule, salary_payouts
from ..core.tenant import budget_month_for_user, settings_for_user, tenant_id
from ..application.currency import SUPPORTED_CURRENCIES, convert_minor, minor_digits
from ..db import reserve_write_slot
from ..models import (
    Account,
    AppSettings,
    BudgetLimit,
    BudgetLimitOverride,
    BudgetMonth,
    Category,
    Goal,
    GoalReserveMovement,
    ImportBatch,
    Loan,
    LoanScheduleItem,
    PlanItem,
    PlanItemTag,
    PlanMatch,
    PlanOverride,
    SalaryMatch,
    SalaryRule,
    Tag,
    Transaction,
    TransactionTag,
    Transfer,
    SessionToken,
)
from ..schemas import MAX_SAFE_INTEGER
from ..security import current_session, get_db, require_csrf, require_csrf_unlocked, require_user


router = APIRouter(tags=["data"])
MAX_UPLOAD = 20 * 1024 * 1024
MAX_ROWS = 100_000
MAX_FIELD = 16_384
IMPORT_TYPES = {"transactions", "loan_schedule", "plan_items"}
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")



def decode_csv(data: bytes, encoding: str | None) -> tuple[str, str]:
    aliases = {
        "utf-8": "utf-8-sig",
        "utf8": "utf-8-sig",
        "utf-8-sig": "utf-8-sig",
        "cp1251": "cp1251",
        "windows-1251": "cp1251",
    }
    if encoding and encoding.lower() not in aliases:
        raise HTTPException(status_code=422, detail="Unsupported CSV encoding")
    candidates = [aliases[encoding.lower()]] if encoding else ["utf-8-sig", "cp1251"]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return data.decode(candidate), candidate
        except UnicodeDecodeError:
            pass
    raise HTTPException(status_code=422, detail="CSV encoding is not UTF-8/BOM or Windows-1251")


def parse_amount(value: str, currency: str = "RUB") -> int:
    clean = value.strip().replace("\u00a0", "").replace(" ", "")
    if "," in clean and "." in clean:
        # Last separator is decimal; the other is grouping.
        decimal_sep = "," if clean.rfind(",") > clean.rfind(".") else "."
        clean = clean.replace("." if decimal_sep == "," else ",", "").replace(decimal_sep, ".")
    else:
        clean = clean.replace(",", ".")
    try:
        return int(
            (Decimal(clean) * (10 ** minor_digits(currency))).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    except (InvalidOperation, ValueError):
        raise ValueError("invalid monetary amount")


def decimal_amount(value: int, currency: str) -> str:
    digits = minor_digits(currency)
    major, minor = divmod(abs(value), 10 ** digits)
    fraction = f",{minor:0{digits}d}" if digits else ""
    return f"{'-' if value < 0 else ''}{major}{fraction}"


def validate_amount(value: int, *, allow_zero: bool = False, allow_negative: bool = False) -> None:
    if (value < 0 and not allow_negative) or (value == 0 and not allow_zero):
        raise ValueError(
            "amount must be positive" if not allow_zero else "amount cannot be negative"
        )
    if abs(value) > MAX_SAFE_INTEGER:
        raise ValueError("amount exceeds the supported safe range")


def parse_date(value: str, fmt: str | None) -> date:
    value = value.strip()
    if "/" in value and not fmt:
        raise ValueError("ambiguous date requires date_format")
    formats = {"iso": "%Y-%m-%d", "dmy": "%d/%m/%Y", "mdy": "%m/%d/%Y", "dmy_dot": "%d.%m.%Y"}
    try:
        return datetime.strptime(value, formats.get(fmt or "iso", fmt or "%Y-%m-%d")).date()
    except ValueError as exc:
        raise ValueError("invalid date") from exc


def safe_excel(value: object) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def ensure_import_month_open(db: Session, value: date) -> None:
    month = budget_month_for_user(db, value.strftime("%Y-%m"))
    if month and month.status == "closed":
        raise HTTPException(
            status_code=409,
            detail="Import contains financial data in a closed month; reopen it first",
        )


@router.post("/imports/preview")
def preview_import(
    file: UploadFile = File(...),
    import_type: str = Form("transactions"),
    encoding: str | None = Form(None),
    delimiter: str | None = Form(None),
    date_format: str | None = Form(None),
    _=Depends(require_csrf_unlocked),
    db: Session = Depends(get_db),
) -> dict:
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="CSV exceeds 20 MiB")
    text, actual_encoding = decode_csv(data, encoding)
    if import_type not in IMPORT_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported import_type")
    if delimiter == "tab":
        delimiter = "\t"
    if delimiter not in (None, ",", ";", "\t"):
        raise HTTPException(status_code=422, detail="Unsupported delimiter")
    try:
        actual_delimiter = (
            delimiter or csv.Sniffer().sniff(text[:8192], delimiters=",;\t").delimiter
        )
    except csv.Error as exc:
        raise HTTPException(status_code=422, detail="Could not detect CSV delimiter") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=actual_delimiter)
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail="CSV header is missing")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise HTTPException(status_code=422, detail="CSV contains duplicate column names")
    if any(len(field or "") > 120 for field in reader.fieldnames):
        raise HTTPException(status_code=422, detail="CSV column name is too long")
    rows, errors = [], []
    accounts = db.scalars(select(Account)).all()
    account_names = {x.name: x.id for x in accounts}
    accounts_by_id = {x.id: x for x in accounts}
    settings = settings_for_user(db)
    base_currency = settings.currency if settings else "RUB"
    category_names = {x.name: x.id for x in db.scalars(select(Category)).all()}
    tag_names = {x.name for x in db.scalars(select(Tag)).all()}
    loan_names = {x.name: x.id for x in db.scalars(select(Loan)).all()}
    fingerprint = hashlib.sha256(
        data
        + json.dumps(
            {
                "type": import_type,
                "encoding": actual_encoding,
                "delimiter": actual_delimiter,
                "date_format": date_format,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    existing = db.scalar(select(ImportBatch).where(ImportBatch.fingerprint == fingerprint))
    if existing:
        return {
            "batch_id": existing.id,
            "status": existing.status,
            "rows": json.loads(existing.rows_json),
            "errors": [],
            "duplicate_batch": True,
        }
    for number, raw in enumerate(reader, start=2):
        if number > MAX_ROWS + 1:
            raise HTTPException(status_code=413, detail="CSV exceeds 100000 rows")
        if None in raw:
            errors.append({"row": number, "message": "row contains extra columns", "raw": raw})
            continue
        if any(len(value or "") > MAX_FIELD for value in raw.values()):
            errors.append({"row": number, "message": "field exceeds maximum length"})
            continue
        try:
            if import_type == "transactions":
                account_value = (raw.get("account") or raw.get("account_id") or "").strip()
                account_id = (
                    int(account_value)
                    if account_value.isdigit()
                    else account_names.get(account_value)
                )
                account = accounts_by_id.get(account_id)
                currency = (raw.get("currency") or (account.currency if account else base_currency)).strip()
                if currency not in SUPPORTED_CURRENCIES or (account and currency != account.currency):
                    raise ValueError("currency does not match account")
                normalized = {
                    "date": parse_date(raw.get("date", ""), date_format).isoformat(),
                    "amount_minor": parse_amount(raw.get("amount", ""), currency),
                    "currency": currency,
                    "type": (raw.get("type") or "").strip().lower(),
                    "account_id": account_id,
                    "account": account_value,
                    "category": (raw.get("category") or "").strip() or None,
                    "category_id": category_names.get((raw.get("category") or "").strip()),
                    "tags": [x.strip() for x in (raw.get("tags") or "").split("|") if x.strip()],
                    "description": raw.get("description", ""),
                    "comment": raw.get("comment") or None,
                    "external_id": raw.get("external_id") or None,
                }
                normalized["requires_reference_confirmation"] = (
                    [f"category:{normalized['category']}"]
                    if normalized["category"] and normalized["category_id"] is None
                    else []
                ) + [f"tag:{tag}" for tag in normalized["tags"] if tag not in tag_names]
                if normalized["type"] not in ("income", "expense", "refund", "adjustment"):
                    raise ValueError("invalid type")
                if not account_id:
                    raise ValueError("unknown or missing account")
                if not account:
                    raise ValueError("unknown or missing account")
                validate_amount(
                    normalized["amount_minor"],
                    allow_negative=normalized["type"] == "adjustment",
                )
                if normalized["category"] and len(normalized["category"]) > 120:
                    raise ValueError("category name is too long")
                if any(len(tag) > 80 for tag in normalized["tags"]):
                    raise ValueError("tag name is too long")
                if len(normalized["description"]) > 300:
                    raise ValueError("description is too long")
                if normalized["comment"] and len(normalized["comment"]) > 4000:
                    raise ValueError("comment is too long")
                if normalized["external_id"] and len(normalized["external_id"]) > 160:
                    raise ValueError("external_id is too long")
                if normalized["type"] == "adjustment" and not (normalized["comment"] or "").strip():
                    raise ValueError("adjustment requires a comment")
                normalized["duplicate_candidate"] = bool(
                    db.scalar(
                        select(func.count())
                        .select_from(Transaction)
                        .where(
                            Transaction.date == date.fromisoformat(normalized["date"]),
                            Transaction.amount_minor == normalized["amount_minor"],
                            Transaction.description == normalized["description"],
                        )
                    )
                )
            elif import_type == "loan_schedule":
                loan_value = (raw.get("loan_id") or raw.get("loan") or "").strip()
                loan_id = int(loan_value) if loan_value.isdigit() else loan_names.get(loan_value)
                if not loan_id:
                    raise ValueError("unknown or missing loan")
                if not db.get(Loan, loan_id):
                    raise ValueError("unknown or missing loan")
                normalized = {
                    "loan_id": loan_id,
                    "due_date": parse_date(raw["due_date"], date_format).isoformat(),
                    "amount_minor": parse_amount(raw["amount"]),
                    "principal_minor": parse_amount(raw["principal"])
                    if raw.get("principal")
                    else None,
                    "interest_minor": parse_amount(raw["interest"])
                    if raw.get("interest")
                    else None,
                }
                validate_amount(normalized["amount_minor"])
                for component in (normalized["principal_minor"], normalized["interest_minor"]):
                    if component is not None:
                        validate_amount(component, allow_zero=True)
                if (normalized["principal_minor"] or 0) + (
                    normalized["interest_minor"] or 0
                ) > normalized["amount_minor"]:
                    raise ValueError("principal and interest exceed payment amount")
            elif import_type == "plan_items":
                category_name = (raw.get("category") or "").strip() or None
                plan_account_id = int(raw["account_id"]) if raw.get("account_id") else None
                plan_account = accounts_by_id.get(plan_account_id)
                plan_currency = (raw.get("currency") or (plan_account.currency if plan_account else base_currency)).strip()
                if plan_currency not in SUPPORTED_CURRENCIES or (plan_account and plan_currency != plan_account.currency):
                    raise ValueError("currency does not match account")
                normalized = {
                    "kind": raw["kind"].strip(),
                    "title": raw["title"].strip(),
                    "amount_minor": parse_amount(raw["amount"], plan_currency),
                    "currency": plan_currency,
                    "date": parse_date(raw["date"], date_format).isoformat()
                    if raw.get("date")
                    else None,
                    "month": raw.get("month") or None,
                    "recurrence": raw.get("recurrence") or "none",
                    "start_date": parse_date(raw["start_date"], date_format).isoformat()
                    if raw.get("start_date")
                    else None,
                    "end_date": parse_date(raw["end_date"], date_format).isoformat()
                    if raw.get("end_date")
                    else None,
                    "certainty": raw.get("certainty") or "confirmed",
                    "category": category_name,
                    "category_id": category_names.get(category_name) if category_name else None,
                    "account_id": plan_account_id,
                }
                validate_amount(normalized["amount_minor"], allow_zero=True)
                if not normalized["title"] or len(normalized["title"]) > 200:
                    raise ValueError("title must contain between 1 and 200 characters")
                if normalized["category"] and len(normalized["category"]) > 120:
                    raise ValueError("category name is too long")
                normalized["requires_reference_confirmation"] = (
                    [f"category:{category_name}"]
                    if category_name and normalized["category_id"] is None
                    else []
                )
                if normalized["kind"] not in ("income", "expense"):
                    raise ValueError("invalid kind")
                if normalized["recurrence"] not in ("none", "monthly", "yearly"):
                    raise ValueError("invalid recurrence")
                if normalized["certainty"] not in ("confirmed", "possible"):
                    raise ValueError("invalid certainty")
                if normalized["account_id"] and not db.get(Account, normalized["account_id"]):
                    raise ValueError("unknown account")
                if normalized["month"] and not MONTH_PATTERN.fullmatch(normalized["month"]):
                    raise ValueError("invalid month")
                if normalized["recurrence"] == "none" and not (
                    normalized["date"] or normalized["month"]
                ):
                    raise ValueError("one-time plan item requires date or month")
                if normalized["recurrence"] != "none" and not (
                    normalized["start_date"] or normalized["date"]
                ):
                    raise ValueError("recurring plan item requires start_date or date")
                if (
                    normalized["start_date"]
                    and normalized["end_date"]
                    and normalized["end_date"] < normalized["start_date"]
                ):
                    raise ValueError("end_date cannot precede start_date")
            rows.append({"row": number, "raw": raw, "normalized": normalized, "selected": True})
        except (ValueError, KeyError) as exc:
            errors.append({"row": number, "message": str(exc), "raw": raw})
    settings = {
        "encoding": actual_encoding,
        "delimiter": actual_delimiter,
        "date_format": date_format,
    }
    batch = ImportBatch(
        fingerprint=fingerprint,
        import_type=import_type,
        settings_json=json.dumps(settings),
        rows_json=json.dumps(rows, ensure_ascii=False),
        status="invalid" if errors else "previewed",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "rows": rows,
        "errors": errors,
        "settings": settings,
        "duplicate_batch": False,
    }


@router.post("/imports/{batch_id}/confirm")
def confirm_import(
    batch_id: int,
    body: dict = Body(default={}),
    _=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    if batch.status == "confirmed":
        return {"batch_id": batch.id, "created_count": batch.created_count, "idempotent": True}
    if batch.status == "invalid":
        raise HTTPException(status_code=409, detail="Invalid batch cannot be confirmed")
    claimed = db.execute(
        update(ImportBatch)
        .where(ImportBatch.id == batch_id, ImportBatch.user_id == tenant_id(db), ImportBatch.status == "previewed")
        .values(status="confirming")
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.expire_all()
        current = db.get(ImportBatch, batch_id)
        if current and current.status == "confirmed":
            return {
                "batch_id": current.id,
                "created_count": current.created_count,
                "idempotent": True,
            }
        raise HTTPException(status_code=409, detail="Import batch is already being confirmed")
    batch.status = "confirming"
    excluded = set(body.get("excluded_rows", []))
    create_refs = bool(body.get("create_references", False))
    created = 0
    seen_external_ids = {
        (account_id, external_id)
        for account_id, external_id in db.execute(
            select(Transaction.account_id, Transaction.external_id).where(
                Transaction.external_source == "csv",
                Transaction.external_id.is_not(None),
            )
        ).all()
    }
    for item in json.loads(batch.rows_json):
        if item["row"] in excluded:
            continue
        row = item["normalized"]
        if batch.import_type == "transactions":
            transaction_date = date.fromisoformat(row["date"])
            ensure_import_month_open(db, transaction_date)
            account = db.get(Account, row["account_id"])
            if not account:
                raise HTTPException(status_code=409, detail="Import account no longer exists")
            if account.currency != row.get("currency", account.currency):
                raise HTTPException(status_code=409, detail="Import account currency changed")
            if transaction_date < account.initial_balance_date:
                raise HTTPException(
                    status_code=422,
                    detail="Imported transaction predates the account opening balance",
                )
            external_key = (row["account_id"], row.get("external_id"))
            if row.get("external_id"):
                if external_key in seen_external_ids:
                    continue
                seen_external_ids.add(external_key)
            category_id = row.get("category_id")
            if row.get("category") and not category_id:
                category = db.scalar(select(Category).where(Category.name == row["category"]))
                if category:
                    category_id = category.id
                else:
                    if not create_refs:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Category requires confirmation: {row['category']}",
                        )
                    category = Category(
                        name=row["category"],
                        kind="income" if row["type"] == "income" else "expense",
                    )
                    db.add(category)
                    db.flush()
                    category_id = category.id
            if category_id:
                category = db.get(Category, category_id)
                if not category:
                    raise HTTPException(status_code=409, detail="Import category no longer exists")
                expected_kind = "income" if row["type"] == "income" else "expense"
                if category.kind != expected_kind:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Category kind does not match transaction: {category.name}",
                    )
            tags = []
            for name in row.get("tags", []):
                tag = db.scalar(select(Tag).where(Tag.name == name))
                if not tag:
                    if not create_refs:
                        raise HTTPException(
                            status_code=409, detail=f"Tag requires confirmation: {name}"
                        )
                    tag = Tag(name=name)
                    db.add(tag)
                    db.flush()
                tags.append(tag)
            db.add(
                Transaction(
                    type=row["type"],
                    amount_minor=row["amount_minor"],
                    date=transaction_date,
                    account_id=row["account_id"],
                    category_id=category_id,
                    description=row["description"],
                    comment=row["comment"],
                    external_source="csv",
                    external_id=row.get("external_id"),
                    import_batch_id=batch.id,
                    tags=tags,
                )
            )
            created += 1
        elif batch.import_type == "loan_schedule":
            ensure_import_month_open(db, date.fromisoformat(row["due_date"]))
            db.add(
                LoanScheduleItem(
                    loan_id=row["loan_id"],
                    due_date=date.fromisoformat(row["due_date"]),
                    amount_minor=row["amount_minor"],
                    principal_minor=row["principal_minor"],
                    interest_minor=row["interest_minor"],
                )
            )
            created += 1
        elif batch.import_type == "plan_items":
            first_occurrence = row.get("start_date") or row.get("date")
            if first_occurrence:
                ensure_import_month_open(db, date.fromisoformat(first_occurrence))
            elif row.get("month"):
                ensure_import_month_open(db, date.fromisoformat(f"{row['month']}-01"))
            category_id = row.get("category_id")
            if row.get("category"):
                category = db.get(Category, category_id) if category_id else None
                category = category or db.scalar(
                    select(Category).where(Category.name == row["category"])
                )
                if not category:
                    if not create_refs:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Category requires confirmation: {row['category']}",
                        )
                    category = Category(name=row["category"], kind=row["kind"])
                    db.add(category)
                    db.flush()
                if category.kind != row["kind"]:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Category kind does not match plan item: {row['category']}",
                    )
                category_id = category.id
            db.add(
                PlanItem(
                    kind=row["kind"],
                    title=row["title"],
                    amount_minor=row["amount_minor"],
                    currency=row.get("currency", "RUB"),
                    date=date.fromisoformat(row["date"]) if row.get("date") else None,
                    month=row.get("month"),
                    recurrence=row["recurrence"],
                    start_date=date.fromisoformat(row["start_date"])
                    if row.get("start_date")
                    else None,
                    end_date=date.fromisoformat(row["end_date"]) if row.get("end_date") else None,
                    certainty=row["certainty"],
                    category_id=category_id,
                    account_id=row.get("account_id"),
                )
            )
            created += 1
    batch.status = "confirmed"
    batch.created_count = created
    db.commit()
    return {"batch_id": batch.id, "created_count": created, "idempotent": False}


@router.get("/exports/transactions.csv")
def export_transactions(
    delimiter: str = ";", _=Depends(require_user), db: Session = Depends(get_db)
) -> Response:
    if delimiter == "tab":
        delimiter = "\t"
    if delimiter not in (",", ";", "\t"):
        raise HTTPException(status_code=422, detail="Unsupported delimiter")
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter)
    accounts = {item.id: item for item in db.scalars(select(Account)).all()}
    category_names = {item.id: item.name for item in db.scalars(select(Category)).all()}
    type_labels = {
        "income": "Доход",
        "expense": "Расход",
        "refund": "Возврат расхода",
        "adjustment": "Корректировка остатка",
    }
    writer.writerow(
        [
            "Дата",
            "Сумма",
            "Валюта",
            "Сумма покупки",
            "Валюта покупки",
            "Курс оплаты",
            "Тип",
            "Счёт",
            "Категория",
            "Теги",
            "Описание",
            "Комментарий",
            "Внешний ID",
        ]
    )
    for tx in db.scalars(select(Transaction).order_by(Transaction.date, Transaction.id)).all():
        account = accounts.get(tx.account_id)
        currency = account.currency if account else "RUB"
        amount = decimal_amount(tx.amount_minor, currency)
        writer.writerow(
            [
                tx.date.isoformat(),
                amount,
                currency,
                decimal_amount(tx.merchant_amount_minor, tx.merchant_currency)
                if tx.merchant_amount_minor is not None and tx.merchant_currency else "",
                tx.merchant_currency or "",
                str(tx.merchant_exchange_rate) if tx.merchant_exchange_rate is not None else "",
                type_labels[tx.type],
                safe_excel(account.name if account else ""),
                safe_excel(category_names.get(tx.category_id, "")),
                "|".join(safe_excel(x.name) for x in tx.tags),
                safe_excel(tx.description),
                safe_excel(tx.comment),
                safe_excel(tx.external_id),
            ]
        )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )


EXPORT_MODELS = [
    AppSettings,
    Account,
    Category,
    Tag,
    Goal,
    Loan,
    Transaction,
    TransactionTag,
    Transfer,
    PlanItem,
    PlanItemTag,
    PlanOverride,
    PlanMatch,
    SalaryRule,
    SalaryMatch,
    BudgetLimit,
    BudgetLimitOverride,
    GoalReserveMovement,
    LoanScheduleItem,
    BudgetMonth,
]

LEGACY_V1_COLUMNS = {
    AppSettings: {"salary_enabled": False},
    Category: {"monthly_estimate": False},
    Transaction: {
        "loan_id": None,
        "principal_component_minor": None,
        "interest_component_minor": None,
        "prepayment_strategy": None,
        "loan_balance_applied": None,
    },
    PlanItem: {"loan_id": None},
    Loan: {
        "annual_rate_bps": None,
        "interest_method": "simple",
        "schedule_mode": "manual",
        "first_payment_date": None,
        "annuity_payment_minor": None,
    },
}
LEGACY_V2_COLUMNS = {AppSettings: {"salary_enabled": False}, Category: {"monthly_estimate": False}}
LEGACY_V3_COLUMNS = {AppSettings: {"salary_enabled": False}}


def model_rows(db: Session, model) -> list[dict]:
    rows = []
    for item in db.scalars(select(model)).all():
        row = {}
        for column in model.__table__.columns:
            value = getattr(item, column.name)
            if model is Transaction and column.name == "import_batch_id":
                value = None  # import provenance is installation-local, not a portable FK
            if column.name == "user_id":
                continue  # archive ownership is assigned by the importing session
            row[column.name] = value.isoformat() if isinstance(value, (date, datetime)) else value
        rows.append(row)
    return rows


def canonical_value(column, raw: str | None):
    if raw is None:
        raise ValueError(f"missing canonical column: {column.name}")
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        python_type = str
    if raw == "":
        if column.nullable:
            return None
        if python_type is str:
            return ""
        raise ValueError(f"required canonical value is empty: {column.name}")
    if python_type is datetime:
        return datetime.fromisoformat(raw)
    if python_type is date:
        return date.fromisoformat(raw)
    if python_type is bool:
        lowered = raw.lower()
        if lowered not in ("0", "1", "false", "true"):
            raise ValueError(f"invalid boolean value for {column.name}")
        return lowered in ("1", "true")
    if python_type is int:
        return int(raw)
    if python_type is Decimal:
        value = Decimal(raw)
        if not value.is_finite():
            raise ValueError(f"invalid exchange rate for {column.name}")
        return value
    return raw


def validate_canonical_row(model, values: dict) -> None:
    for column in model.__table__.columns:
        value = values[column.name]
        length = getattr(column.type, "length", None)
        if isinstance(value, str) and length and len(value) > length:
            raise ValueError(f"{model.__tablename__}.{column.name} is too long")
        if column.name.endswith("_minor") and value is not None:
            if abs(value) > MAX_SAFE_INTEGER:
                raise ValueError(f"{model.__tablename__}.{column.name} exceeds safe range")
    version = values.get("version")
    if version is not None and version < 1:
        raise ValueError(f"{model.__tablename__}.version must be positive")

    allowed_values = {
        Account: {"type": {"cash", "bank", "savings"}},
        Category: {"kind": {"income", "expense"}},
        Transaction: {"type": {"income", "expense", "refund", "adjustment"}},
        PlanItem: {
            "kind": {"income", "expense"},
            "recurrence": {"none", "monthly", "yearly"},
            "certainty": {"confirmed", "possible"},
            "status": {"planned", "fulfilled", "cancelled"},
            "funding_source": {"free", "goal"},
        },
        GoalReserveMovement: {"kind": {"allocation", "release", "expense", "refund"}},
        LoanScheduleItem: {"status": {"planned", "partially_paid", "paid", "cancelled"}},
        BudgetMonth: {"status": {"open", "closed"}},
        SalaryMatch: {"component": {"advance", "salary"}},
    }
    for field, allowed in allowed_values.get(model, {}).items():
        if values.get(field) not in allowed:
            raise ValueError(f"invalid {model.__tablename__}.{field}")

    if model is AppSettings:
        if not re.fullmatch(r"[A-Z]{3}", values["currency"]):
            raise ValueError("invalid settings currency")
    elif model is Category:
        if values["monthly_estimate"] and values["kind"] != "expense":
            raise ValueError("monthly estimate requires an expense category")
    elif model is Transaction:
        if values["type"] == "adjustment" and values["amount_minor"] == 0:
            raise ValueError("balance adjustment cannot be zero")
        if values["type"] != "adjustment" and values["amount_minor"] <= 0:
            raise ValueError("transaction amount must be positive")
        if values["type"] == "adjustment":
            if values.get("category_id") is not None:
                raise ValueError("balance adjustment cannot have a category")
            if not (values.get("comment") or "").strip():
                raise ValueError("balance adjustment requires a comment")
        if values.get("loan_id") is not None:
            if values["type"] != "expense":
                raise ValueError("loan-linked transaction must be an expense")
            principal = values.get("principal_component_minor") or 0
            interest = values.get("interest_component_minor") or 0
            if principal < 0 or interest < 0 or principal + interest > values["amount_minor"]:
                raise ValueError("invalid loan payment breakdown")
            if (
                values.get("loan_balance_applied") is True
                and values.get("principal_component_minor") is None
            ):
                raise ValueError("applied loan payment needs a principal component")
            if (
                values.get("loan_balance_applied") is False
                and values.get("prepayment_strategy") is not None
            ):
                raise ValueError("historical loan link cannot change repayment strategy")
        elif any(
            values.get(field) is not None
            for field in (
                "principal_component_minor",
                "interest_component_minor",
                "prepayment_strategy",
                "loan_balance_applied",
            )
        ):
            raise ValueError("loan payment breakdown requires a linked loan")
        if values.get("prepayment_strategy") not in (None, "reduce_term", "reduce_payment"):
            raise ValueError("invalid early repayment strategy")
    elif model is Transfer:
        if values["amount_minor"] <= 0 or values["from_account_id"] == values["to_account_id"]:
            raise ValueError("invalid transfer")
    elif model is PlanItem:
        if values["amount_minor"] < 0:
            raise ValueError("plan amount cannot be negative")
        if values["recurrence"] == "none" and not (values.get("date") or values.get("month")):
            raise ValueError("one-time plan item requires date or month")
        if values["recurrence"] != "none" and not (values.get("start_date") or values.get("date")):
            raise ValueError("recurring plan item requires a start date")
        if values.get("month") and not MONTH_PATTERN.fullmatch(values["month"]):
            raise ValueError("invalid plan month")
        if values["funding_source"] == "goal" and values.get("goal_id") is None:
            raise ValueError("goal-funded plan item requires goal_id")
        if values.get("loan_id") is not None and (
            values["kind"] != "expense" or values["funding_source"] == "goal"
        ):
            raise ValueError("loan-linked plan item must be a free-funded expense")
    elif model is PlanOverride:
        if not MONTH_PATTERN.fullmatch(values["month"]):
            raise ValueError("invalid plan override month")
        if values.get("amount_minor") is not None and values["amount_minor"] < 0:
            raise ValueError("plan override amount cannot be negative")
    elif model is PlanMatch:
        if not MONTH_PATTERN.fullmatch(values["occurrence_month"]):
            raise ValueError("invalid plan match month")
        if values["amount_minor"] <= 0:
            raise ValueError("plan match amount must be positive")
    elif model is SalaryRule:
        if not values["name"].strip() or values["gross_minor"] <= 0:
            raise ValueError("invalid salary rule")
        if not 0 < values["advance_share_bps"] < 10_000 or not 16 <= values["advance_day"] <= 31 or not 1 <= values["salary_day"] <= 15:
            raise ValueError("invalid salary payout schedule")
        if not MONTH_PATTERN.fullmatch(values["start_month"]) or (values["end_month"] and (not MONTH_PATTERN.fullmatch(values["end_month"]) or values["end_month"] < values["start_month"])):
            raise ValueError("invalid salary period")
        if not 2025 <= int(values["start_month"][:4]) <= 2100 or (values["end_month"] and not 2025 <= int(values["end_month"][:4]) <= 2100):
            raise ValueError("invalid salary year")
        if values["initial_tax_base_minor"] < 0 or (values["initial_tax_base_minor"] and values["initial_tax_year"] != int(values["start_month"][:4])):
            raise ValueError("invalid initial salary tax base")
    elif model is SalaryMatch:
        if not MONTH_PATTERN.fullmatch(values["earning_month"]) or values["amount_minor"] <= 0:
            raise ValueError("invalid salary match")
    elif model in (BudgetLimit, BudgetLimitOverride):
        if values["amount_minor"] < 0:
            raise ValueError("budget limit cannot be negative")
        for field in ("month", "start_month", "end_month"):
            if values.get(field) and not MONTH_PATTERN.fullmatch(values[field]):
                raise ValueError(f"invalid budget limit {field}")
    elif model is Goal:
        if values["target_amount_minor"] < 0 or values["initial_reserved_minor"] < 0:
            raise ValueError("goal amounts cannot be negative")
    elif model is GoalReserveMovement:
        if values["amount_minor"] <= 0:
            raise ValueError("goal movement amount must be positive")
    elif model is Loan:
        if values.get("principal_minor") is not None and values["principal_minor"] < 0:
            raise ValueError("loan principal cannot be negative")
        if values["interest_method"] not in ("simple", "compound"):
            raise ValueError("invalid loan interest method")
        if values["schedule_mode"] not in ("manual", "auto"):
            raise ValueError("invalid loan schedule mode")
        if (
            values.get("annual_rate_bps") is not None
            and not 0 <= values["annual_rate_bps"] <= 100_000
        ):
            raise ValueError("invalid annual loan rate")
        if values["schedule_mode"] == "auto" and any(
            values.get(field) is None
            for field in (
                "principal_minor",
                "principal_as_of",
                "annual_rate_bps",
                "first_payment_date",
                "end_date",
                "annuity_payment_minor",
            )
        ):
            raise ValueError("automatic loan schedule is incomplete")
    elif model is LoanScheduleItem:
        if values["amount_minor"] <= 0 or values["paid_minor"] < 0:
            raise ValueError("invalid loan schedule amounts")
        if (values.get("principal_minor") or 0) + (values.get("interest_minor") or 0) > values[
            "amount_minor"
        ]:
            raise ValueError("loan components exceed payment amount")


def validate_canonical_relationships(db: Session) -> None:
    for transaction in db.scalars(select(Transaction)).all():
        account = db.get(Account, transaction.account_id)
        if not account or transaction.date < account.initial_balance_date:
            raise ValueError("transaction predates or references a missing account")
        if account.currency not in SUPPORTED_CURRENCIES:
            raise ValueError("transaction account currency is unsupported")
        if transaction.merchant_currency is not None:
            if transaction.merchant_amount_minor is None or transaction.merchant_exchange_rate is None:
                raise ValueError("cross-currency payment lacks amount or rate")
            payment_debit = convert_minor(
                transaction.merchant_amount_minor,
                transaction.merchant_currency,
                account.currency,
                transaction.merchant_exchange_rate,
            )
            if abs(payment_debit - transaction.amount_minor) > 1:
                raise ValueError("cross-currency payment rate does not match account debit")
        elif transaction.merchant_amount_minor is not None or transaction.merchant_exchange_rate is not None:
            raise ValueError("payment conversion is incomplete")
        if transaction.loan_id is not None and not db.get(Loan, transaction.loan_id):
            raise ValueError("transaction references a missing loan")
    for plan in db.scalars(select(PlanItem)).all():
        if plan.currency not in SUPPORTED_CURRENCIES:
            raise ValueError("plan currency is unsupported")
        if plan.account_id is not None:
            account = db.get(Account, plan.account_id)
            if not account or account.currency != plan.currency:
                raise ValueError("plan currency does not match account")
        if plan.loan_id is not None and not db.get(Loan, plan.loan_id):
            raise ValueError("plan item references a missing loan")
    for transfer in db.scalars(select(Transfer)).all():
        source = db.get(Account, transfer.from_account_id)
        target = db.get(Account, transfer.to_account_id)
        if (
            not source
            or not target
            or transfer.date < source.initial_balance_date
            or transfer.date < target.initial_balance_date
        ):
            raise ValueError("transfer predates or references a missing account")
        if convert_minor(
            transfer.amount_minor,
            source.currency,
            target.currency,
            transfer.exchange_rate,
        ) != transfer.to_amount_minor:
            raise ValueError("transfer amount and exchange rate disagree")
    for match in db.scalars(select(PlanMatch)).all():
        plan = db.get(PlanItem, match.plan_item_id)
        transaction = db.get(Transaction, match.transaction_id)
        expected_type = "income" if plan and plan.kind == "income" else "expense"
        if (
            not plan
            or not transaction
            or transaction.type != expected_type
            or match.amount_minor > transaction.amount_minor
            or (db.get(Account, transaction.account_id).currency != plan.currency)
            or (
                transaction.external_source
                and transaction.external_source.startswith("loan_schedule:")
            )
        ):
            raise ValueError("invalid plan-to-transaction match")
    plan_transaction_ids = {match.transaction_id for match in db.scalars(select(PlanMatch)).all()}
    for rule in db.scalars(select(SalaryRule)).all():
        account = db.get(Account, rule.account_id) if rule.account_id else None
        category = db.get(Category, rule.category_id) if rule.category_id else None
        if not account or (rule.category_id and (not category or category.kind != "income")):
            raise ValueError("salary rule references invalid account or category")
    salary_matches = db.scalars(select(SalaryMatch)).all()
    payout_amounts: dict[tuple[int, str, str], int] = {}
    matched_amounts: dict[tuple[int, str, str], int] = {}
    for rule in db.scalars(select(SalaryRule)).all():
        rule_matches = [match for match in salary_matches if match.salary_rule_id == rule.id]
        if not rule_matches:
            continue
        through = max(match.earning_month for match in rule_matches)
        for payout in salary_payouts(PayrollRule(
            gross_minor=rule.gross_minor, advance_share_bps=rule.advance_share_bps,
            advance_day=rule.advance_day, salary_day=rule.salary_day,
            start_month=rule.start_month, end_month=rule.end_month,
            initial_tax_base_minor=rule.initial_tax_base_minor,
            initial_tax_year=rule.initial_tax_year,
        ), through):
            payout_amounts[rule.id, payout.earning_month, payout.component] = payout.net_minor
    for match in salary_matches:
        rule = db.get(SalaryRule, match.salary_rule_id)
        transaction = db.get(Transaction, match.transaction_id)
        key = match.salary_rule_id, match.earning_month, match.component
        matched_amounts[key] = matched_amounts.get(key, 0) + match.amount_minor
        if not rule or not transaction or transaction.type != "income" or transaction.goal_id is not None or transaction.account_id != rule.account_id or match.amount_minor > transaction.amount_minor or match.transaction_id in plan_transaction_ids or key not in payout_amounts:
            raise ValueError("invalid salary-to-transaction match")
    if any(amount > payout_amounts[key] for key, amount in matched_amounts.items()):
        raise ValueError("salary match exceeds net payout")
    for schedule_item in db.scalars(select(LoanScheduleItem)).all():
        payments = db.scalars(
            select(Transaction).where(
                Transaction.external_source == f"loan_schedule:{schedule_item.id}"
            )
        ).all()
        if sum(payment.amount_minor for payment in payments) != schedule_item.paid_minor:
            raise ValueError("loan schedule paid amount does not match linked transactions")
        if payments and any(payment.type != "expense" for payment in payments):
            raise ValueError("loan schedule is linked to a non-expense transaction")
    for goal in db.scalars(select(Goal)).all():
        reserve = goal.initial_reserved_minor
        movements = db.scalars(
            select(GoalReserveMovement)
            .where(GoalReserveMovement.goal_id == goal.id)
            .order_by(GoalReserveMovement.date, GoalReserveMovement.id)
        ).all()
        for movement in movements:
            reserve += (
                movement.amount_minor
                if movement.kind in ("allocation", "refund")
                else -movement.amount_minor
            )
            if reserve < 0:
                raise ValueError("goal reserve becomes negative")
            if movement.kind in ("expense", "refund"):
                if movement.transaction_id is None:
                    raise ValueError("goal movement is missing its transaction")
                transaction = db.get(Transaction, movement.transaction_id)
                if (
                    not transaction
                    or transaction.goal_id != movement.goal_id
                    or transaction.type != movement.kind
                    or transaction.amount_minor != movement.amount_minor
                    or transaction.date != movement.date
                ):
                    raise ValueError("goal movement is not paired with its transaction")
    # A canonical archive must preserve an existing installation even if its
    # historical opening free balance is negative. Forecasts report that
    # deficit; rejecting the archive here would make export non-restorable.


@router.get("/exports/project")
def export_project(_=Depends(require_user), db: Session = Depends(get_db)) -> StreamingResponse:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        files = []
        for model in EXPORT_MODELS:
            name = f"{model.__tablename__}.csv"
            files.append(name)
            rows = model_rows(db, model)
            output = io.StringIO(newline="")
            fields = [x.name for x in model.__table__.columns if x.name != "user_id"]
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(name, output.getvalue())
        manifest = {
            "schema_version": 6,
            "app_version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    data.seek(0)
    return StreamingResponse(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=budget-project.zip"},
    )


@router.post("/imports/project")
def import_project(
    file: UploadFile = File(...), _=Depends(require_csrf_unlocked),
    auth=Depends(current_session), db: Session = Depends(get_db)
) -> dict:
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="Archive exceeds 20 MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            listed_names = archive.namelist()
            names = set(listed_names)
            if len(listed_names) != len(names):
                raise HTTPException(status_code=422, detail="Archive contains duplicate file names")
            if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
                raise HTTPException(status_code=422, detail="Unsafe archive path")
            if sum(x.file_size for x in archive.infolist()) > 100 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Expanded archive is too large")
            manifest = json.loads(archive.read("manifest.json"))
            schema_version = manifest.get("schema_version")
            if schema_version not in (1, 2, 3, 4, 5, 6):
                raise HTTPException(status_code=422, detail="Unsupported schema version")
            models = EXPORT_MODELS if schema_version in (4, 5, 6) else [model for model in EXPORT_MODELS if model not in (SalaryRule, SalaryMatch)]
            expected = {f"{model.__tablename__}.csv" for model in models} | {"manifest.json"}
            if names != expected:
                raise HTTPException(status_code=422, detail="Archive file list does not match schema")
            if set(manifest.get("files", [])) != expected - {"manifest.json"}:
                raise HTTPException(
                    status_code=422, detail="Manifest file list does not match archive"
                )
            reserve_write_slot(db)
            current = db.get(SessionToken, auth[1].id)
            if not current or current.revoked:
                raise HTTPException(status_code=401, detail="Session expired")
            if any(
                (db.scalar(select(func.count()).select_from(model).where(model.user_id == tenant_id(db))) or 0)
                for model in EXPORT_MODELS
                if model is not AppSettings
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Canonical project import requires an empty installation",
                )
            # GET /settings creates a harmless singleton on a new installation.
            # It must not make a canonical restore impossible; the imported row
            # replaces it within the same all-or-nothing transaction.
            db.execute(delete(AppSettings).where(AppSettings.user_id == tenant_id(db)))
            legacy_columns = (
                LEGACY_V1_COLUMNS
                if schema_version == 1
                else LEGACY_V2_COLUMNS
                if schema_version == 2
                else LEGACY_V3_COLUMNS
                if schema_version == 3
                else {}
            )
            legacy_currency = "RUB"
            if schema_version < 6:
                settings_reader = csv.DictReader(
                    io.StringIO(archive.read("app_settings.csv").decode("utf-8"))
                )
                settings_row = next(settings_reader, None)
                if settings_row and settings_row.get("currency"):
                    legacy_currency = settings_row["currency"]
                if legacy_currency not in SUPPORTED_CURRENCIES:
                    raise ValueError("Unsupported base currency in legacy archive")
            parsed: dict[type, list[dict]] = {}
            for model in EXPORT_MODELS:
                name = f"{model.__tablename__}.csv"
                if name not in names:
                    continue
                rows = []
                reader = csv.DictReader(io.StringIO(archive.read(name).decode("utf-8")))
                for row_number, raw in enumerate(reader, start=2):
                    if row_number > MAX_ROWS + 1:
                        raise ValueError(f"{name} exceeds {MAX_ROWS} rows")
                    if any(len(value or "") > MAX_FIELD for value in raw.values()):
                        raise ValueError(f"{name} contains an oversized field")
                    values = {}
                    for column in model.__table__.columns:
                        if column.name == "user_id":
                            values[column.name] = tenant_id(db)
                        elif schema_version < 6 and column.name == "currency" and model in (Account, PlanItem):
                            values[column.name] = legacy_currency
                        elif schema_version < 6 and model is Transfer and column.name == "to_amount_minor":
                            values[column.name] = int(raw["amount_minor"])
                        elif schema_version < 6 and model is Transfer and column.name == "exchange_rate":
                            values[column.name] = Decimal(1)
                        elif schema_version < 6 and model is Transaction and column.name in (
                            "merchant_currency", "merchant_amount_minor", "merchant_exchange_rate"
                        ):
                            values[column.name] = None
                        elif column.name not in raw and column.name in legacy_columns.get(model, {}):
                            values[column.name] = legacy_columns[model][column.name]
                        else:
                            values[column.name] = canonical_value(column, raw.get(column.name))
                    validate_canonical_row(model, values)
                    rows.append(values)
                parsed[model] = rows

            # Archive IDs are local to the source installation. Allocate fresh
            # PostgreSQL sequence IDs before resolving any cross-table links.
            id_maps: dict[str, dict[int, int]] = {}
            for model, rows in parsed.items():
                if "id" not in model.__table__.c or not rows:
                    continue
                previous = [row["id"] for row in rows]
                if len(previous) != len(set(previous)):
                    raise ValueError(f"{model.__tablename__} contains duplicate IDs")
                if db.bind.dialect.name == "sqlite":  # TD-003 legacy test fixture
                    highest = db.connection().execute(
                        select(func.max(model.__table__.c.id))
                    ).scalar_one() or 0
                    allocated = list(range(highest + 1, highest + 1 + len(rows)))
                else:
                    sequence = db.scalar(
                        text("SELECT pg_get_serial_sequence(:table, 'id')"),
                        {"table": model.__tablename__},
                    )
                    if not sequence:
                        raise ValueError(f"{model.__tablename__} has no ID sequence")
                    allocated = db.execute(
                        text("SELECT nextval(CAST(:sequence AS regclass)) FROM generate_series(1, :count)"),
                        {"sequence": sequence, "count": len(rows)},
                    ).scalars().all()
                id_maps[model.__tablename__] = dict(zip(previous, allocated, strict=True))

            created = {}
            for model, rows in parsed.items():
                for values in rows:
                    for column in model.__table__.columns:
                        value = values[column.name]
                        if value is None or column.name == "user_id":
                            continue
                        if column.name == "id":
                            values["id"] = id_maps[model.__tablename__][value]
                            continue
                        for foreign_key in column.foreign_keys:
                            target = foreign_key.column.table.name
                            if target in id_maps:
                                try:
                                    values[column.name] = id_maps[target][value]
                                except KeyError as exc:
                                    raise ValueError(
                                        f"{model.__tablename__}.{column.name} references missing {target} row"
                                    ) from exc
                    if model is Transaction and (values.get("external_source") or "").startswith("loan_schedule:"):
                        old_item_id = int(values["external_source"].split(":", 1)[1])
                        values["external_source"] = (
                            f"loan_schedule:{id_maps['loan_schedule_items'][old_item_id]}"
                        )
                    db.add(model(**values))
                db.flush()
                created[model.__tablename__] = len(rows)
            if schema_version == 1:
                for item in db.scalars(select(LoanScheduleItem)).all():
                    for payment in db.scalars(
                        select(Transaction).where(
                            Transaction.external_source == f"loan_schedule:{item.id}"
                        )
                    ).all():
                        payment.loan_id = item.loan_id
            validate_canonical_relationships(db)
            db.commit()
            return {"schema_version": 6, "created": created}
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Invalid ZIP archive") from exc
    except (UnicodeError, ValueError, InvalidOperation, csv.Error, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid canonical archive: {exc}") from exc
