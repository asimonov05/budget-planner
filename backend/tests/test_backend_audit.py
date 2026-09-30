from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm.exc import StaleDataError

from app.api.io import EXPORT_MODELS
from app.core.calculations import calculate_forecast
from app.db import SessionLocal
from app.models import (
    Account,
    AppSettings,
    Category,
    Goal,
    PlanItem,
    PlanOverride,
    Transaction,
)


def test_origin_cannot_be_whitelisted_by_spoofed_forwarded_host(client, auth):
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Карта",
            "type": "bank",
            "initial_balance_minor": 100,
            "initial_balance_date": "2026-01-01",
        },
        headers={
            **auth,
            "Origin": "https://attacker.example",
            "X-Forwarded-Host": "attacker.example",
            "X-Forwarded-Proto": "https",
        },
    )
    assert response.status_code == 403


def test_goal_without_initial_reserve_can_be_created_when_opening_free_cash_is_negative(
    client, auth, db
):
    db.add(Goal(name="Существующая", target_amount_minor=10_000, initial_reserved_minor=1_000))
    db.commit()

    empty_reserve = client.post(
        "/api/v1/goals",
        json={"name": "Новая", "target_amount_minor": 300_000_00, "initial_reserved_minor": 0},
        headers=auth,
    )
    assert empty_reserve.status_code == 201, empty_reserve.text

    positive_reserve = client.post(
        "/api/v1/goals",
        json={"name": "Ещё одна", "target_amount_minor": 300_000_00, "initial_reserved_minor": 1},
        headers=auth,
    )
    assert positive_reserve.status_code == 409
    assert positive_reserve.json()["message"] == (
        "Начальный резерв цели превышает свободные деньги на дату начала учёта"
    )


def test_goal_movements_preserve_reserve_invariants(client, auth, account, db):
    goal = client.post(
        "/api/v1/goals",
        json={
            "name": "Отпуск",
            "target_amount_minor": 150_000_00,
            "initial_reserved_minor": 30_000_00,
        },
        headers=auth,
    )
    assert goal.status_code == 201
    goal_id = goal.json()["id"]

    too_much = client.post(
        f"/api/v1/goals/{goal_id}/allocations",
        json={"kind": "allocation", "amount_minor": 170_000_01, "date": "2026-01-02"},
        headers=auth,
    )
    assert too_much.status_code == 409

    generic_goal_expense = client.post(
        "/api/v1/transactions",
        json={
            "type": "expense",
            "amount_minor": 100,
            "date": "2026-01-02",
            "account_id": account.id,
            "goal_id": goal_id,
        },
        headers=auth,
    )
    assert generic_goal_expense.status_code == 422

    spent = client.post(
        f"/api/v1/goals/{goal_id}/allocations",
        json={
            "kind": "expense",
            "amount_minor": 40_000_00,
            "date": "2026-01-10",
            "account_id": account.id,
            "allow_allocate_shortfall": True,
        },
        headers={**auth, "Idempotency-Key": "goal-expense-once"},
    )
    assert spent.status_code == 201, spent.text
    transaction_id = spent.json()["transaction_id"]

    invalid_refund = client.post(
        f"/api/v1/goals/{goal_id}/allocations",
        json={
            "kind": "refund",
            "amount_minor": 40_000_01,
            "date": "2026-01-11",
            "account_id": account.id,
        },
        headers=auth,
    )
    assert invalid_refund.status_code == 409

    db.rollback()
    transaction = db.get(Transaction, transaction_id)
    update = client.patch(
        f"/api/v1/transactions/{transaction_id}",
        json={"version": transaction.version, "amount_minor": 39_000_00},
        headers=auth,
    )
    assert update.status_code == 409

    forecast = client.get("/api/v1/forecast", params={"from_month": "2026-01", "months": 1}).json()[
        "months"
    ][0]
    assert (forecast["c_end"], forecast["r_end"], forecast["f_end"]) == (
        160_000_00,
        0,
        160_000_00,
    )


def test_initial_goal_reserve_does_not_exist_before_accounting_start(db, account):
    db.add(Goal(name="Отпуск", target_amount_minor=30_000_00, initial_reserved_minor=30_000_00))
    db.commit()
    result = calculate_forecast(db, "2025-12", 2)
    december, january = result["months"]
    assert (december["c_end"], december["r_end"], december["f_end"]) == (0, 0, 0)
    assert (january["c_start"], january["r_start"], january["f_start"]) == (
        200_000_00,
        30_000_00,
        170_000_00,
    )


def test_moved_recurring_occurrence_changes_month_without_losing_identity(db, account):
    plan = PlanItem(
        kind="expense",
        title="Платёж",
        amount_minor=10_000,
        recurrence="monthly",
        start_date=date(2026, 1, 15),
        account_id=account.id,
    )
    db.add(plan)
    db.flush()
    db.add(
        PlanOverride(
            plan_item_id=plan.id,
            month="2026-02",
            moved_date=date(2026, 3, 5),
        )
    )
    db.commit()
    result = calculate_forecast(db, "2026-02", 2)
    february, march = result["months"]
    assert february["expense"] == 0
    assert march["expense"] == 20_000
    assert {detail["occurrence_month"] for detail in march["details"]} == {
        "2026-02",
        "2026-03",
    }


def test_loan_payments_are_atomic_idempotent_and_not_double_counted(client, auth, account, db):
    loan = client.post(
        "/api/v1/loans", json={"name": "Кредит", "account_id": account.id}, headers=auth
    ).json()
    scheduled = client.post(
        f"/api/v1/loans/{loan['id']}/schedule",
        json={"due_date": "2026-03-05", "amount_minor": 20_000_00},
        headers=auth,
    ).json()
    partial_body = {"amount_minor": 12_000_00, "date": "2026-03-05"}
    partial_headers = {**auth, "Idempotency-Key": "loan-partial"}
    first = client.post(
        f"/api/v1/loans/{loan['id']}/schedule/{scheduled['id']}/payments",
        json=partial_body,
        headers=partial_headers,
    )
    repeated = client.post(
        f"/api/v1/loans/{loan['id']}/schedule/{scheduled['id']}/payments",
        json=partial_body,
        headers=partial_headers,
    )
    assert first.status_code == repeated.status_code == 201
    assert first.json() == repeated.json()
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Transaction)) == 1
    march = client.get("/api/v1/forecast", params={"from_month": "2026-03", "months": 1}).json()[
        "months"
    ][0]
    assert march["expense"] == 20_000_00

    completed = client.post(
        f"/api/v1/loans/{loan['id']}/schedule/{scheduled['id']}/payments",
        json={"amount_minor": 6_000_00, "date": "2026-03-06", "completed": True},
        headers={**auth, "Idempotency-Key": "loan-complete-under-plan"},
    )
    assert completed.status_code == 201
    march = client.get("/api/v1/forecast", params={"from_month": "2026-03", "months": 1}).json()[
        "months"
    ][0]
    assert march["expense"] == 18_000_00


def test_import_confirmation_is_atomic_and_respects_closed_month(client, auth, account, db):
    from app.models import BudgetMonth, ImportBatch

    db.add(BudgetMonth(month="2026-02", status="closed"))
    db.commit()
    content = (
        "date;amount;type;account;category;description\n"
        "2026-02-01;10,00;expense;Основной;Еда;Первая\n"
        "2026-02-02;20,00;expense;Основной;Еда;Вторая\n"
    ).encode()
    preview = client.post(
        "/api/v1/imports/preview",
        files={"file": ("closed.csv", content, "text/csv")},
        data={"delimiter": ";", "date_format": "iso"},
        headers=auth,
    )
    assert preview.status_code == 200
    batch_id = preview.json()["batch_id"]
    confirmed = client.post(
        f"/api/v1/imports/{batch_id}/confirm",
        json={"create_references": True},
        headers=auth,
    )
    assert confirmed.status_code == 409
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Transaction)) == 0
    assert db.get(ImportBatch, batch_id).status == "previewed"
    assert db.scalar(select(func.count()).select_from(Category)) == 0


def test_plan_item_import_requires_explicit_new_category_confirmation(client, auth, db):
    from app.models import ImportBatch

    content = (
        "kind;title;amount;month;category\nexpense;Страховка;1 000,00;2026-04;Обязательные\n"
    ).encode()
    preview = client.post(
        "/api/v1/imports/preview",
        files={"file": ("plans.csv", content, "text/csv")},
        data={"import_type": "plan_items", "delimiter": ";"},
        headers=auth,
    )
    assert preview.status_code == 200, preview.text
    normalized = preview.json()["rows"][0]["normalized"]
    assert normalized["category_id"] is None
    assert normalized["requires_reference_confirmation"] == ["category:Обязательные"]
    batch_id = preview.json()["batch_id"]

    rejected = client.post(f"/api/v1/imports/{batch_id}/confirm", json={}, headers=auth)
    assert rejected.status_code == 409
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Category)) == 0
    assert db.scalar(select(func.count()).select_from(PlanItem)) == 0
    assert db.get(ImportBatch, batch_id).status == "previewed"

    confirmed = client.post(
        f"/api/v1/imports/{batch_id}/confirm",
        json={"create_references": True},
        headers=auth,
    )
    assert confirmed.status_code == 200, confirmed.text
    db.rollback()
    plan = db.scalar(select(PlanItem))
    category = db.scalar(select(Category))
    assert plan is not None and category is not None
    assert plan.category_id == category.id
    assert category.name == "Обязательные" and category.kind == "expense"


def test_project_round_trip_accepts_default_settings_and_empty_strings(client, auth, account, db):
    db.add(
        Transaction(
            type="expense",
            amount_minor=100,
            date=date(2026, 1, 2),
            account_id=account.id,
            description="",
        )
    )
    db.commit()
    exported = client.get("/api/v1/exports/project")
    assert exported.status_code == 200

    for model in reversed(EXPORT_MODELS):
        db.query(model).delete()
    db.add(AppSettings(id=1, accounting_start_date=date(2026, 1, 1)))
    db.commit()

    imported = client.post(
        "/api/v1/imports/project",
        files={"file": ("project.zip", exported.content, "application/zip")},
        headers=auth,
    )
    assert imported.status_code == 200, imported.text
    transaction = db.scalar(select(Transaction))
    assert transaction is not None and transaction.description == ""


def test_invalid_project_archive_rolls_back_all_rows(client, auth, account, db):
    db.add(
        Transaction(
            type="expense",
            amount_minor=100,
            date=date(2026, 1, 2),
            account_id=account.id,
        )
    )
    db.commit()
    exported = client.get("/api/v1/exports/project").content
    source = zipfile.ZipFile(io.BytesIO(exported))
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as target:
        for name in source.namelist():
            value = source.read(name)
            if name == "transactions.csv":
                value = value.replace(b",100,", b",not-an-integer,")
            target.writestr(name, value)
    source.close()

    for model in reversed(EXPORT_MODELS):
        db.query(model).delete()
    db.add(AppSettings(id=1, accounting_start_date=date(2026, 1, 1)))
    db.commit()
    response = client.post(
        "/api/v1/imports/project",
        files={"file": ("broken.zip", payload.getvalue(), "application/zip")},
        headers=auth,
    )
    assert response.status_code == 422
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Account)) == 0
    assert db.scalar(select(func.count()).select_from(Transaction)) == 0
    assert db.get(AppSettings, 1) is not None


def test_sqlalchemy_version_guard_rejects_actual_concurrent_update(db):
    category = Category(name="Еда", kind="expense")
    db.add(category)
    db.commit()
    category_id = category.id
    with SessionLocal() as first, SessionLocal() as second:
        first_value = first.get(Category, category_id)
        second_value = second.get(Category, category_id)
        second.expunge(second_value)
        second.rollback()
        first_value.name = "Продукты"
        first_value.version += 1
        first.commit()
        second_value.name = "Старое имя"
        with SessionLocal() as stale_writer, pytest.raises(StaleDataError):
            stale_writer.merge(second_value)
