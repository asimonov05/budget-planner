"""Masked table administration. Reads and writes deliberately use different DB roles.

The diagnostic role can read all tenants but cannot write. Mutations use the normal
runtime role, one explicit owner scope and the same advisory lock as the budget API.
Ordinary responses never include private values. A separate audited command can
reveal one reviewed field; credentials and embedded JSON remain inaccessible.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import (
    Boolean, Date, DateTime, Integer, Numeric, create_engine, delete,
    func, insert, or_, select, text, update,
)
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from .config import config
from .db import Base, SessionLocal, database_connect_args, engine, reserve_write_slot
from .models import (
    AuditLog, BudgetMonth, GoalReserveMovement, LoanScheduleItem, PlanMatch,
    SalaryMatch, SessionToken, Transaction, User, utcnow,
)


MASK = "[скрыто]"
REVISION_KEY = secrets.token_bytes(32)
READ_ONLY = {
    "audit_logs", "idempotency_records", "import_batches", "sessions", "release_notes",
    "notifications", "application_availability", "user_app_access",
    "plan_matches", "salary_matches", "goal_reserve_movements", "loan_schedule_items",
}
DOMAIN_MANAGED = {
    "plan_matches", "salary_matches", "goal_reserve_movements", "loan_schedule_items",
}
DOMAIN_REASON = "Связанные финансовые записи изменяются через операции приложения с пересчётом сумм"
SYSTEM = {"created_at", "updated_at", "version"}
SECRET_PARTS = ("password", "token", "secret", "credential", "hash", "fingerprint")
VISIBLE_NUMBERS = {"version", "sort_order", "priority", "created_count", "status_code"}
# An explicit review is required before a newly added private column can be read.
REVEALABLE_COLUMNS = {
    "users": {"username"},
    "accounts": {"name", "type", "currency", "initial_balance_minor", "initial_balance_date"},
    "app_settings": {"currency", "currency_display_mode", "timezone", "accounting_start_date"},
    "audit_logs": {"entity_type", "entity_id", "action"},
    "budget_months": {"status", "closed_at"},
    "categories": {"name", "kind", "color"},
    "goals": {"name", "target_amount_minor", "target_date", "initial_reserved_minor", "color", "status"},
    "import_batches": {"import_type", "status"},
    "notifications": {"kind", "title", "body", "read_at"},
    "release_notes": {"release_version", "title", "summary", "body", "status", "published_at"},
    "sessions": {"expires_at"},
    "tags": {"name", "color"},
    "budget_limits": {"amount_minor", "start_month", "end_month"},
    "budget_limit_overrides": {"month", "amount_minor"},
    "loans": {"name", "creditor", "principal_minor", "principal_as_of", "annual_rate_bps",
              "interest_method", "schedule_mode", "first_payment_date", "annuity_payment_minor",
              "start_date", "end_date", "comment"},
    "salary_rules": {"name", "gross_minor", "advance_share_bps", "advance_day", "salary_day",
                     "start_month", "end_month", "initial_tax_base_minor", "initial_tax_year"},
    "transfers": {"amount_minor", "to_amount_minor", "exchange_rate", "date", "comment"},
    "loan_schedule_items": {"due_date", "amount_minor", "principal_minor", "interest_minor", "status", "paid_minor"},
    "plan_items": {"kind", "title", "amount_minor", "currency", "date", "month", "recurrence",
                   "start_date", "end_date", "certainty", "status", "funding_source", "comment"},
    "transactions": {"type", "amount_minor", "merchant_currency", "merchant_amount_minor",
                     "merchant_exchange_rate", "date", "principal_component_minor", "interest_component_minor",
                     "prepayment_strategy", "description", "comment", "external_source", "external_id"},
    "goal_reserve_movements": {"kind", "amount_minor", "date", "comment"},
    "plan_matches": {"occurrence_month", "amount_minor"},
    "plan_overrides": {"month", "amount_minor", "moved_date"},
    "salary_matches": {"earning_month", "component", "amount_minor"},
}
LABELS = {
    "users": "Пользователи", "sessions": "Сессии", "accounts": "Счета",
    "categories": "Категории", "tags": "Теги", "transactions": "Операции",
    "transfers": "Переводы", "goals": "Цели", "loans": "Кредиты",
    "app_settings": "Настройки бюджета", "audit_logs": "Журнал изменений",
    "plan_items": "Планы", "plan_item_tags": "Теги планов", "plan_matches": "Исполнение планов",
    "plan_overrides": "Изменения планов", "transaction_tags": "Теги операций",
    "salary_rules": "Правила зарплаты", "salary_matches": "Начисления зарплаты",
    "budget_limits": "Лимиты", "budget_limit_overrides": "Изменения лимитов",
    "budget_months": "Бюджетные месяцы", "loan_schedule_items": "График кредитов",
    "goal_reserve_movements": "Движения резервов", "import_batches": "Импорт",
    "idempotency_records": "Идемпотентность", "release_notes": "Заметки о версиях",
    "notifications": "Уведомления", "application_availability": "Доступность приложений",
    "user_app_access": "Доступ пользователей",
}


def tables():
    return {table.name: table for table in Base.metadata.sorted_tables}


def get_table(name: str):
    table = tables().get(name)
    if table is None:
        raise HTTPException(404, "Таблица не найдена")
    return table


def protected(column) -> bool:
    return any(part in column.name for part in SECRET_PARTS) or (
        column.name == "key" or column.name.endswith("_json")
    )


def masked(column) -> bool:
    if protected(column):
        return True
    if column.primary_key or column.foreign_keys or column.name in SYSTEM:
        return False
    if isinstance(column.type, Boolean):
        return False
    if isinstance(column.type, Integer) and column.name in VISIBLE_NUMBERS:
        return False
    # Free text, JSON, dates and financial values are private by default. New
    # columns fail closed instead of relying on a growing list of PII field names.
    return True


def revealable(table, column) -> bool:
    return (column.name in REVEALABLE_COLUMNS.get(table.name, set())
            and masked(column) and not protected(column))


def column_type(column) -> str:
    for cls, name in (
        (Boolean, "boolean"), (Integer, "integer"), (Numeric, "number"),
        (DateTime, "datetime"), (Date, "date"),
    ):
        if isinstance(column.type, cls):
            return name
    return "text"


def editable(table, column, *, creating: bool = False) -> bool:
    if table.name in READ_ONLY or protected(column) or column.name in SYSTEM:
        return False
    if table.name == "users":
        return not creating and column.name in {"active", "is_admin"}
    if column.name == "user_id":
        return creating
    if column.primary_key:
        return creating and not (
            len(table.primary_key.columns) == 1 and isinstance(column.type, Integer)
            and not column.foreign_keys
        )
    return True


def describe_table(table) -> dict:
    columns = []
    for column in table.columns:
        can_create = editable(table, column, creating=True)
        columns.append({
            "name": column.name, "type": column_type(column), "nullable": column.nullable,
            "primary_key": column.primary_key, "editable": editable(table, column),
            "create_editable": can_create, "masked": masked(column),
            "revealable": revealable(table, column),
            "write_only": masked(column) and (can_create or editable(table, column)),
            "required": can_create and not column.nullable and (
                column.name == "user_id" or (column.default is None and column.server_default is None)
            ),
            "max_length": getattr(column.type, "length", None),
            "references": [f"{fk.column.table.name}.{fk.column.name}" for fk in column.foreign_keys],
        })
    return {
        "name": table.name, "label": LABELS.get(table.name, table.name), "columns": columns,
        "primary_key": [column.name for column in table.primary_key.columns],
        "can_create": table.name not in READ_ONLY | {"users"},
        "can_edit": table.name not in READ_ONLY,
        "can_delete": table.name not in READ_ONLY | {"users"},
        "readonly_reason": DOMAIN_REASON if table.name in DOMAIN_MANAGED else None,
    }


def scalar(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def revision(table, row) -> str:
    payload = json.dumps([table.name, {k: scalar(v) for k, v in row.items()}], sort_keys=True)
    return hmac.new(REVISION_KEY, payload.encode(), hashlib.sha256).hexdigest()


def serialize(table, row) -> dict:
    return {
        "key": {c.name: scalar(row[c.name]) for c in table.primary_key.columns},
        "values": {
            c.name: MASK if row[c.name] is not None and masked(c) else scalar(row[c.name])
            for c in table.columns
        },
        "revision": revision(table, row),
    }


@lru_cache(maxsize=1)
def read_engine():
    if engine.dialect.name == "sqlite":
        return engine
    if not config.debug_database_url or not config.debug_database_password_file:
        raise HTTPException(503, "Не настроено подключение администратора к данным")
    return create_engine(
        config.debug_database_url,
        connect_args=database_connect_args(config.debug_database_url, config.debug_database_password_file),
        pool_pre_ping=True,
    )


def convert(column, value):
    try:
        if value is None:
            if not column.nullable:
                raise ValueError
            return None
        kind = column_type(column)
        if kind == "boolean":
            if not isinstance(value, bool):
                raise ValueError
            return value
        if kind == "integer":
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                raise ValueError
            result = int(value)
            if not -(2**63) <= result < 2**63:
                raise ValueError
            return result
        if kind == "number":
            if isinstance(value, bool):
                raise ValueError
            result = Decimal(str(value))
            if not result.is_finite():
                raise ValueError
            return result
        if kind == "datetime":
            return datetime.fromisoformat(value)
        if kind == "date":
            return date.fromisoformat(value)
        if not isinstance(value, str) or len(value) > (getattr(column.type, "length", None) or 16384):
            raise ValueError
        return value
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise HTTPException(422, f"Недопустимое значение поля {column.name}") from None


def key_condition(table, key: dict):
    if set(key) != {c.name for c in table.primary_key.columns}:
        raise HTTPException(422, "Неверный ключ записи")
    return [c == convert(c, key[c.name]) for c in table.primary_key.columns]


def read_record(table, key: dict) -> dict:
    with read_engine().connect() as connection:
        row = connection.execute(select(table).where(*key_condition(table, key))).mappings().first()
        if row is None:
            raise HTTPException(404, "Запись не найдена")
        return dict(row)


def reveal_record(table, key: dict, column_name: str, actor_id: int) -> dict:
    column = table.c.get(column_name)
    if column is None or not revealable(table, column):
        raise HTTPException(403, "Это поле нельзя раскрыть")
    # Serialize with role changes and re-check the actor before accessing the
    # diagnostic connection. The audit stores identifiers, never the value.
    with write_session(actor_id, actor_id, admin_accounts=True) as db:
        row = read_record(table, key)
        audit(db, table, row, actor_id, "reveal", [column_name])
        value = scalar(row[column_name])
    return {"column": column_name, "value": value}


def list_records(table, limit: int, offset: int, search: str, sort: str, direction: str) -> dict:
    order = table.c.get(sort) if sort else next(iter(table.primary_key.columns))
    if order is None or masked(order):
        raise HTTPException(422, "Сортировка по этому полю недоступна")
    conditions = []
    if search:
        # Searching private values, even with masked output, reveals their presence.
        if not search.isascii() or not search.isdecimal() or len(search) > 18:
            raise HTTPException(422, "Поиск доступен по числовому ID записи или пользователя")
        conditions.append(or_(*[
            c == int(search) for c in table.columns
            if isinstance(c.type, Integer) and (c.primary_key or c.foreign_keys) and not masked(c)
        ]))
    statement = select(table).where(*conditions)
    ordering = [order.desc() if direction == "desc" else order.asc()]
    ordering.extend(c.asc() for c in table.primary_key.columns if c.name != order.name)
    with read_engine().connect() as connection:
        total = connection.scalar(select(func.count()).select_from(table).where(*conditions))
        rows = connection.execute(statement.order_by(*ordering).limit(limit).offset(offset)).mappings()
        return {"rows": [serialize(table, row) for row in rows], "total": total, "limit": limit, "offset": offset}


def values_for_write(table, values: dict, creating: bool) -> dict:
    result = {}
    for name, value in values.items():
        column = table.c.get(name)
        if column is None or not editable(table, column, creating=creating):
            raise HTTPException(422, "Поле недоступно для изменения")
        if value == MASK:
            raise HTTPException(422, "Введите новое значение вместо маски")
        result[name] = convert(column, value)
    if creating:
        for column in describe_table(table)["columns"]:
            if column["required"] and column["name"] not in result:
                raise HTTPException(422, f"Заполните поле {column['name']}")
    return result


@contextmanager
def write_session(actor_id: int, owner_id: int, *, admin_accounts: bool = False):
    with SessionLocal() as db:
        db.info.update(user_id=owner_id, admin_actor_id=actor_id)
        if admin_accounts and db.bind.dialect.name == "postgresql":
            # All account-role/status commands take the same lock before they
            # re-check the actor, preventing two admins from demoting each other.
            db.execute(text("SELECT pg_advisory_xact_lock(17021987, 1)"))
        reserve_write_slot(db)
        # Re-check after acquiring the lock: a stale browser must not retain an
        # admin capability after its account has been disabled or demoted.
        actor = db.get(User, actor_id)
        if not actor or not actor.active or not actor.is_admin:
            raise HTTPException(403, "Доступ администратора отозван")
        try:
            yield db
            db.commit()
        except (IntegrityError, DataError):
            db.rollback()
            raise HTTPException(409, "Запись связана с другими данными или нарушает ограничения таблицы") from None


def ensure_open_month(db: Session, table, row: dict):
    if "user_id" not in table.c or table.name == "users":
        return
    months = set()
    for name, value in row.items():
        if isinstance(value, date) and not isinstance(value, datetime):
            months.add(value.strftime("%Y-%m"))
        if name in {"month", "occurrence_month", "earning_month", "start_month"} and value:
            months.add(str(value))
    if months and db.scalar(select(BudgetMonth.month).where(
        BudgetMonth.user_id == row["user_id"], BudgetMonth.month.in_(months), BudgetMonth.status == "closed",
    )):
        raise HTTPException(409, "Сначала откройте бюджетный месяц через приложение")


def ensure_independent_financial_record(
    db: Session, table, row: dict, changes: dict | None = None, *, creating: bool = False,
) -> None:
    """Do not let raw CRUD bypass the application's coupled ledger commands."""
    if table.name == "transactions":
        proposed = {**row, **(changes or {})}
        for state in (row, proposed):
            if (
                any(state.get(name) is not None for name in (
                    "goal_id", "loan_id", "principal_component_minor", "interest_component_minor",
                    "prepayment_strategy",
                ))
                or state.get("loan_balance_applied")
                or str(state.get("external_source") or "").startswith("loan_schedule:")
            ):
                raise HTTPException(409, DOMAIN_REASON)
        if not creating:
            for model in (PlanMatch, SalaryMatch, GoalReserveMovement):
                if db.scalar(select(model.id).where(model.transaction_id == row["id"]).limit(1)):
                    raise HTTPException(409, DOMAIN_REASON)
    if table.name == "loans" and not creating:
        metadata = {"name", "creditor", "comment", "archived"}
        if changes is None or set(changes) - metadata:
            if (
                db.scalar(select(LoanScheduleItem.id).where(LoanScheduleItem.loan_id == row["id"]).limit(1))
                or db.scalar(select(Transaction.id).where(Transaction.loan_id == row["id"]).limit(1))
            ):
                raise HTTPException(409, DOMAIN_REASON)
    # Deleting these parents would cascade through protected matching records.
    if not creating and changes is None:
        for parent, model, key in (
            ("plan_items", PlanMatch, "plan_item_id"),
            ("salary_rules", SalaryMatch, "salary_rule_id"),
        ):
            if table.name == parent and db.scalar(
                select(model.id).where(getattr(model, key) == row["id"]).limit(1)
            ):
                raise HTTPException(409, DOMAIN_REASON)


def audit(db: Session, table, row: dict, actor_id: int, action: str, fields: list[str]):
    # Store field names, actor and identifiers only, never copies of personal data.
    db.add(AuditLog(
        user_id=db.info["user_id"], entity_type=f"admin:{table.name}"[:80],
        entity_id=json.dumps({c.name: scalar(row[c.name]) for c in table.primary_key.columns})[:80],
        action=f"admin_{action}", before_json=None,
        after_json=json.dumps({"actor_id": actor_id, "fields": sorted(fields)}),
    ))


def create_record(table, values: dict, actor_id: int) -> dict:
    if not describe_table(table)["can_create"]:
        raise HTTPException(403, "Создание записей в этой таблице запрещено")
    values = values_for_write(table, values, True)
    owner_id = values.get("user_id", actor_id)
    with write_session(actor_id, owner_id) as db:
        if "user_id" in table.c and not db.get(User, owner_id):
            raise HTTPException(422, "Пользователь не найден")
        ensure_independent_financial_record(db, table, values, creating=True)
        ensure_open_month(db, table, values)
        row = dict(db.execute(insert(table).values(**values).returning(*table.columns)).mappings().one())
        audit(db, table, row, actor_id, "create", list(values))
    return serialize(table, row)


def mutate_record(table, key: dict, values: dict | None, expected_revision: str, actor_id: int):
    deleting = values is None
    capability = "can_delete" if deleting else "can_edit"
    if not describe_table(table)[capability]:
        raise HTTPException(403, "Изменение записей в этой таблице запрещено")
    changes = {} if deleting else values_for_write(table, values, False)
    initial = read_record(table, key)
    owner_id = initial.get("user_id", actor_id)
    with write_session(actor_id, owner_id, admin_accounts=table.name == "users") as db:
        row = db.execute(select(table).where(*key_condition(table, key)).with_for_update()).mappings().first()
        if row is None:
            raise HTTPException(404, "Запись не найдена")
        row = dict(row)
        if not hmac.compare_digest(revision(table, row), expected_revision):
            raise HTTPException(409, "Запись изменилась. Откройте её заново")
        if table.name == "users" and row["id"] == actor_id and (
            changes.get("active") is False or changes.get("is_admin") is False
        ):
            raise HTTPException(409, "Нельзя отключить собственную учётную запись администратора")
        ensure_independent_financial_record(db, table, row, None if deleting else changes)
        ensure_open_month(db, table, row)
        ensure_open_month(db, table, {**row, **changes})
        if deleting:
            db.execute(delete(table).where(*key_condition(table, key)))
            audit(db, table, row, actor_id, "delete", [])
            return None
        if "version" in table.c:
            changes["version"] = row["version"] + 1
        if "updated_at" in table.c:
            changes["updated_at"] = utcnow()
        if changes:
            row = dict(db.execute(update(table).where(*key_condition(table, key)).values(**changes)
                       .returning(*table.columns)).mappings().one())
            if table.name == "users" and (changes.get("active") is False or changes.get("is_admin") is False):
                db.execute(delete(SessionToken).where(SessionToken.user_id == row["id"]))
            audit(db, table, row, actor_id, "update", list(changes))
    return serialize(table, row)
