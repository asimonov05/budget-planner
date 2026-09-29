from __future__ import annotations

import csv
import io
import json
import sqlite3
import zipfile
from datetime import date

from sqlalchemy import delete, func, select

from app.api.io import EXPORT_MODELS
from app.config import config
from app.models import (
    Account,
    AuditLog,
    BudgetLimit,
    Category,
    Goal,
    Loan,
    LoanScheduleItem,
    PlanItem,
    PlanItemTag,
    PlanOverride,
    Tag,
    Transaction,
    TransactionTag,
    Transfer,
)


def test_auth_and_csrf(client):
    assert client.get("/api/v1/accounts").status_code == 401
    assert client.get("/api/v1/exports/project").status_code == 401
    assert client.get("/api/v1/backups").status_code == 401
    login = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "correct horse battery staple"}
    )
    assert login.status_code == 200
    assert login.cookies.get("budget_session")
    assert login.cookies.get("csrf_token") == login.json()["csrf_token"]
    body = {
        "name": "Карта",
        "type": "bank",
        "initial_balance_minor": 10000,
        "initial_balance_date": "2026-01-01",
    }
    assert client.post("/api/v1/accounts", json=body).status_code == 403
    assert client.post("/api/v1/backups").status_code == 403
    assert (
        client.post(
            "/api/v1/accounts", json=body, headers={"X-CSRF-Token": login.json()["csrf_token"]}
        ).status_code
        == 201
    )


def test_version_conflict(client, auth):
    made = client.post(
        "/api/v1/categories", json={"name": "Еда", "kind": "expense"}, headers=auth
    ).json()
    assert (
        client.patch(
            f"/api/v1/categories/{made['id']}",
            json={"version": made["version"], "name": "Продукты"},
            headers=auth,
        ).status_code
        == 200
    )
    conflict = client.patch(
        f"/api/v1/categories/{made['id']}",
        json={"version": made["version"], "name": "Старое"},
        headers=auth,
    )
    assert conflict.status_code == 409


def test_idempotent_transaction(client, auth, account):
    body = {
        "type": "expense",
        "amount_minor": 1000,
        "date": "2026-02-01",
        "account_id": account.id,
        "description": "Кофе",
    }
    headers = {**auth, "Idempotency-Key": "once"}
    first = client.post("/api/v1/transactions", json=body, headers=headers)
    second = client.post("/api/v1/transactions", json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    changed = {**body, "amount_minor": 1001}
    assert client.post("/api/v1/transactions", json=changed, headers=headers).status_code == 409


def test_negative_balance_adjustment_and_csv_format(client, auth, account):
    response = client.post(
        "/api/v1/transactions",
        json={
            "type": "adjustment",
            "amount_minor": -12_345,
            "date": "2026-02-01",
            "account_id": account.id,
            "description": "Сверка",
            "comment": "Списание по результам сверки",
        },
        headers=auth,
    )
    assert response.status_code == 201, response.text
    forecast = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 1}).json()[
        "months"
    ][0]
    assert forecast["adjustments"] == -12_345
    exported = client.get("/api/v1/exports/transactions.csv")
    assert "-123,45" in exported.text


def test_idempotent_plan_match_is_exposed_on_transaction_list(client, auth, account, db):
    category = Category(name="Аренда", kind="expense")
    db.add(category)
    db.flush()
    plan = PlanItem(
        kind="expense",
        title="Аренда",
        amount_minor=20_000_00,
        date=date(2026, 2, 5),
        account_id=account.id,
        category_id=category.id,
    )
    transaction = Transaction(
        type="expense",
        amount_minor=12_000_00,
        date=date(2026, 2, 5),
        account_id=account.id,
        category_id=category.id,
        description="Часть аренды",
    )
    db.add_all([plan, transaction])
    db.commit()

    payload = {
        "transaction_id": transaction.id,
        "occurrence_month": "2026-02",
        "amount_minor": 12_000_00,
        "completed": False,
    }
    headers = {**auth, "Idempotency-Key": "same-plan-match"}
    first = client.post(f"/api/v1/plan-items/{plan.id}/matches", json=payload, headers=headers)
    second = client.post(f"/api/v1/plan-items/{plan.id}/matches", json=payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listed = client.get("/api/v1/transactions").json()["items"]
    item = next(value for value in listed if value["id"] == transaction.id)
    assert item["matched_plan_item_id"] == plan.id
    assert item["matched_amount_minor"] == 12_000_00
    assert item["match_completed"] is False


def test_internal_transfer_is_idempotent_and_total_neutral(client, auth, account, db):
    savings = Account(
        name="Накопительный",
        type="savings",
        initial_balance_minor=50_000_00,
        initial_balance_date=date(2026, 1, 1),
    )
    db.add(savings)
    db.commit()
    db.refresh(savings)
    before_accounts = client.get("/api/v1/accounts").json()["items"]
    before_total = sum(value["current_balance_minor"] for value in before_accounts)
    before_forecast = client.get(
        "/api/v1/forecast", params={"from_month": "2026-02", "months": 1}
    ).json()["months"][0]

    payload = {
        "from_account_id": account.id,
        "to_account_id": savings.id,
        "amount_minor": 10_000_00,
        "date": "2026-02-01",
    }
    headers = {**auth, "Idempotency-Key": "same-transfer"}
    first = client.post("/api/v1/transfers", json=payload, headers=headers)
    second = client.post("/api/v1/transfers", json=payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    after_accounts = client.get("/api/v1/accounts").json()["items"]
    assert sum(value["current_balance_minor"] for value in after_accounts) == before_total
    assert client.get("/api/v1/transfers").json()["total"] == 1
    after_forecast = client.get(
        "/api/v1/forecast", params={"from_month": "2026-02", "months": 1}
    ).json()["months"][0]
    assert (
        after_forecast["income"],
        after_forecast["expense"],
        after_forecast["c_end"],
        after_forecast["r_end"],
        after_forecast["f_end"],
    ) == (
        before_forecast["income"],
        before_forecast["expense"],
        before_forecast["c_end"],
        before_forecast["r_end"],
        before_forecast["f_end"],
    )


def test_multi_tag_filter_counts_transaction_once(client, auth, account, db):
    family = Tag(name="семья")
    vacation = Tag(name="отпуск-2027")
    transaction = Transaction(
        type="expense",
        amount_minor=1_000_00,
        date=date(2026, 2, 2),
        account_id=account.id,
        description="Покупка",
        tags=[family, vacation],
    )
    db.add(transaction)
    db.commit()
    db.refresh(family)
    db.refresh(vacation)

    params = [("tag_ids", family.id), ("tag_ids", vacation.id), ("tag_mode", "or")]
    response = client.get("/api/v1/transactions", params=params)
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["amount_minor"] == 1_000_00

    params[-1] = ("tag_mode", "and")
    assert client.get("/api/v1/transactions", params=params).json()["total"] == 1


def test_identical_real_purchases_without_external_id_are_both_kept(client, auth, account):
    payload = {
        "type": "expense",
        "amount_minor": 750_00,
        "date": "2026-02-03",
        "account_id": account.id,
        "description": "Одинаковые покупки",
    }
    first = client.post(
        "/api/v1/transactions",
        json=payload,
        headers={**auth, "Idempotency-Key": "real-purchase-1"},
    )
    second = client.post(
        "/api/v1/transactions",
        json=payload,
        headers={**auth, "Idempotency-Key": "real-purchase-2"},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert client.get("/api/v1/transactions").json()["total"] == 2


def test_close_and_reopen_month_switches_fact_only_and_preserves_audit(client, auth, account, db):
    db.add(
        PlanItem(
            kind="expense",
            title="Ожидаемый платёж",
            amount_minor=20_000_00,
            month="2026-02",
            account_id=account.id,
        )
    )
    fact = Transaction(
        type="expense",
        amount_minor=9_000_00,
        date=date(2026, 2, 5),
        account_id=account.id,
        description="Факт",
    )
    db.add(fact)
    db.commit()
    open_month = client.get(
        "/api/v1/forecast", params={"from_month": "2026-02", "months": 2}
    ).json()["months"]
    assert open_month[0]["expense"] == 29_000_00

    closed = client.post("/api/v1/months/2026-02/close", headers=auth)
    assert closed.status_code == 200
    closed_month = client.get(
        "/api/v1/forecast", params={"from_month": "2026-02", "months": 2}
    ).json()["months"]
    assert closed_month[0]["closed"] is True
    assert closed_month[0]["expense"] == 9_000_00
    assert closed_month[1]["c_start"] == 191_000_00
    blocked = client.post(
        "/api/v1/transactions",
        json={
            "type": "expense",
            "amount_minor": 100,
            "date": "2026-02-06",
            "account_id": account.id,
        },
        headers=auth,
    )
    assert blocked.status_code == 409

    reopened = client.post("/api/v1/months/2026-02/reopen", headers=auth)
    assert reopened.status_code == 200
    changed = client.patch(
        f"/api/v1/transactions/{fact.id}",
        json={"version": fact.version, "amount_minor": 10_000_00},
        headers=auth,
    )
    assert changed.status_code == 200
    assert db.scalar(select(func.count()).select_from(AuditLog)) == 2
    recalculated = client.get(
        "/api/v1/forecast", params={"from_month": "2026-02", "months": 2}
    ).json()["months"]
    assert recalculated[0]["closed"] is False
    assert recalculated[1]["c_start"] == 170_000_00


def test_archiving_account_and_category_preserves_history_and_forecast(client, auth, account, db):
    category = Category(name="Историческая", kind="expense")
    goal = Goal(
        name="Историческая цель",
        target_amount_minor=30_000_00,
        initial_reserved_minor=5_000_00,
    )
    db.add_all([category, goal])
    db.flush()
    db.add(
        Transaction(
            type="expense",
            amount_minor=4_000_00,
            date=date(2026, 2, 10),
            account_id=account.id,
            category_id=category.id,
            description="Старая операция",
        )
    )
    db.commit()
    db.refresh(category)
    before = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 1}).json()[
        "months"
    ][0]

    archived_category = client.patch(
        f"/api/v1/categories/{category.id}",
        json={"version": category.version, "archived": True},
        headers=auth,
    )
    archived_account = client.patch(
        f"/api/v1/accounts/{account.id}",
        json={"version": account.version, "archived": True},
        headers=auth,
    )
    archived_goal = client.patch(
        f"/api/v1/goals/{goal.id}",
        json={
            "version": goal.version,
            "status": "archived",
            "archived": True,
            "reserve_disposition": "keep",
        },
        headers=auth,
    )
    assert (
        archived_category.status_code
        == archived_account.status_code
        == archived_goal.status_code
        == 200
    )
    assert client.get("/api/v1/categories").json()["total"] == 0
    assert client.get("/api/v1/accounts").json()["total"] == 0
    assert client.get("/api/v1/categories?include_archived=true").json()["total"] == 1
    assert client.get("/api/v1/accounts?include_archived=true").json()["total"] == 1
    assert client.get("/api/v1/goals").json()["total"] == 0
    assert client.get("/api/v1/goals?include_archived=true").json()["total"] == 1
    assert client.get("/api/v1/transactions").json()["total"] == 1
    after = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 1}).json()[
        "months"
    ][0]
    assert (after["expense"], after["c_end"], after["f_end"]) == (
        before["expense"],
        before["c_end"],
        before["f_end"],
    )


def test_cp1251_csv_import_and_repeat_batch(client, auth, account, db):
    content = 'date;amount;type;account;category;tags;description;comment;external_id\n01.02.2026;"1 234,56";expense;Основной;Еда;семья|дом;Покупка;тест;x1\n'.encode(
        "cp1251"
    )
    files = {"file": ("fact.csv", content, "text/csv")}
    data = {
        "import_type": "transactions",
        "encoding": "cp1251",
        "delimiter": ";",
        "date_format": "dmy_dot",
    }
    preview = client.post("/api/v1/imports/preview", files=files, data=data, headers=auth)
    assert (
        preview.status_code == 200
        and preview.json()["rows"][0]["normalized"]["amount_minor"] == 123456
    )
    confirmed = client.post(
        f"/api/v1/imports/{preview.json()['batch_id']}/confirm",
        json={"create_references": True},
        headers=auth,
    )
    assert confirmed.json()["created_count"] == 1
    repeated = client.post("/api/v1/imports/preview", files=files, data=data, headers=auth)
    assert repeated.json()["duplicate_batch"] is True
    again = client.post(
        f"/api/v1/imports/{preview.json()['batch_id']}/confirm", json={}, headers=auth
    )
    assert again.json()["created_count"] == 1 and again.json()["idempotent"] is True


def test_utf8_bom_csv_preserves_quoted_newline_and_russian_tags(client, auth, account, db):
    content = (
        "\ufeffdate;amount;type;account;category;tags;description;comment;external_id\n"
        '2026-02-02;"1 234,56";expense;Основной;Путешествия;семья|отпуск;"две\nстроки";тест;utf8-1\n'
    ).encode("utf-8")
    preview = client.post(
        "/api/v1/imports/preview",
        files={"file": ("bom.csv", content, "text/csv")},
        data={
            "import_type": "transactions",
            "encoding": "utf-8-sig",
            "delimiter": ";",
            "date_format": "iso",
        },
        headers=auth,
    )
    assert preview.status_code == 200, preview.text
    normalized = preview.json()["rows"][0]["normalized"]
    assert normalized["description"] == "две\nстроки"
    assert normalized["tags"] == ["семья", "отпуск"]
    confirmed = client.post(
        f"/api/v1/imports/{preview.json()['batch_id']}/confirm",
        json={"create_references": True},
        headers=auth,
    )
    assert confirmed.status_code == 200
    transaction = db.scalar(select(Transaction).where(Transaction.external_id == "utf8-1"))
    assert transaction and transaction.description == "две\nстроки"
    assert {tag.name for tag in transaction.tags} == {"семья", "отпуск"}


def test_formula_safe_csv_export(client, auth, account, db):
    db.add(
        Transaction(
            type="expense",
            amount_minor=100,
            date=date(2026, 1, 2),
            account_id=account.id,
            description="=CMD()",
        )
    )
    db.commit()
    response = client.get("/api/v1/exports/transactions.csv")
    assert response.status_code == 200
    assert "Дата;Сумма;Тип;Счёт;Категория" in response.text
    assert "Основной" in response.text
    assert "'=CMD()" in response.text


def test_project_export_is_safe_zip_and_backup_valid(client, auth, account, db):
    category = Category(name="Еда", kind="expense")
    db.add(category)
    db.flush()
    db.add(
        Transaction(
            type="expense",
            amount_minor=500,
            date=date(2026, 1, 2),
            account_id=account.id,
            category_id=category.id,
        )
    )
    db.commit()
    response = client.get("/api/v1/exports/project")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "manifest.json" in archive.namelist()
        assert all(".." not in name for name in archive.namelist())
    backup = client.post("/api/v1/backups", headers=auth)
    assert backup.status_code == 201
    path = config.backup_dir / backup.json()["name"]
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert connection.execute("PRAGMA foreign_key_check").fetchone() is None


def test_project_export_import_round_trip_preserves_links_and_totals(client, auth, account, db):
    savings = Account(
        name="Накопительный",
        type="savings",
        initial_balance_minor=50_000_00,
        initial_balance_date=date(2026, 1, 1),
    )
    category = Category(name="Путешествия", kind="expense", monthly_estimate=True)
    tag = Tag(name="отпуск-2027")
    goal = Goal(name="Отпуск", target_amount_minor=150_000_00, initial_reserved_minor=30_000_00)
    db.add_all([savings, category, tag, goal])
    db.flush()
    transaction = Transaction(
        type="expense",
        amount_minor=1_000_00,
        date=date(2026, 2, 10),
        account_id=account.id,
        category_id=category.id,
        description="Билеты",
        tags=[tag],
    )
    plan = PlanItem(
        kind="expense",
        title="Гостиница",
        amount_minor=8_000_00,
        month="2026-02",
        account_id=account.id,
        category_id=category.id,
        tags=[tag],
    )
    db.add_all(
        [
            transaction,
            Transaction(
                type="adjustment",
                amount_minor=-500_00,
                date=date(2026, 2, 11),
                account_id=account.id,
                description="Сверка",
                comment="Уменьшение остатка",
            ),
            plan,
            Transfer(
                from_account_id=account.id,
                to_account_id=savings.id,
                amount_minor=10_000_00,
                date=date(2026, 2, 1),
            ),
            BudgetLimit(category_id=category.id, amount_minor=15_000_00, start_month="2026-01"),
        ]
    )
    db.flush()
    db.add(PlanOverride(plan_item_id=plan.id, month="2026-03", amount_minor=0))
    db.commit()

    before = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 2}).json()
    exported = client.get("/api/v1/exports/project")
    assert exported.status_code == 200
    expected_counts = {
        model.__tablename__: db.scalar(select(func.count()).select_from(model)) or 0
        for model in EXPORT_MODELS
    }

    for model in reversed(EXPORT_MODELS):
        db.execute(delete(model))
    db.commit()
    imported = client.post(
        "/api/v1/imports/project",
        files={"file": ("budget-project.zip", exported.content, "application/zip")},
        headers=auth,
    )
    assert imported.status_code == 200, imported.text
    db.expire_all()
    assert db.get(Category, category.id).monthly_estimate is True

    actual_counts = {
        model.__tablename__: db.scalar(select(func.count()).select_from(model)) or 0
        for model in EXPORT_MODELS
    }
    assert actual_counts == expected_counts
    assert db.scalar(select(func.count()).select_from(TransactionTag)) == 1
    assert db.scalar(select(func.count()).select_from(PlanItemTag)) == 1
    after = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 2}).json()
    assert after == before


def test_legacy_project_archive_restores_loan_payment_links(client, auth, account, db):
    loan = Loan(name="Старый кредит", principal_minor=100_000, principal_as_of=date(2026, 1, 1))
    db.add(loan)
    db.flush()
    scheduled = LoanScheduleItem(
        loan_id=loan.id,
        due_date=date(2026, 2, 1),
        amount_minor=1_000,
        paid_minor=1_000,
        status="paid",
    )
    db.add(scheduled)
    db.flush()
    db.add(
        Transaction(
            type="expense",
            amount_minor=1_000,
            date=date(2026, 2, 1),
            account_id=account.id,
            description="Платёж",
            external_source=f"loan_schedule:{scheduled.id}",
        )
    )
    db.commit()

    exported = client.get("/api/v1/exports/project")
    assert exported.status_code == 200
    legacy = io.BytesIO()
    removed = {
        "app_settings.csv": {"salary_enabled"},
        "categories.csv": {"monthly_estimate"},
        "loans.csv": {
            "annual_rate_bps",
            "interest_method",
            "schedule_mode",
            "first_payment_date",
            "annuity_payment_minor",
        },
        "transactions.csv": {
            "loan_id",
            "principal_component_minor",
            "interest_component_minor",
            "prepayment_strategy",
            "loan_balance_applied",
        },
        "plan_items.csv": {"loan_id"},
    }
    with (
        zipfile.ZipFile(io.BytesIO(exported.content)) as source,
        zipfile.ZipFile(legacy, "w") as destination,
    ):
        for name in source.namelist():
            if name in ("salary_rules.csv", "salary_matches.csv"):
                continue
            if name == "manifest.json":
                manifest = json.loads(source.read(name))
                manifest["schema_version"] = 1
                manifest["files"] = [file for file in manifest["files"] if file not in ("salary_rules.csv", "salary_matches.csv")]
                destination.writestr(name, json.dumps(manifest))
            elif name in removed:
                reader = csv.DictReader(io.StringIO(source.read(name).decode("utf-8")))
                fields = [field for field in reader.fieldnames or [] if field not in removed[name]]
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                for row in reader:
                    writer.writerow({field: row[field] for field in fields})
                destination.writestr(name, output.getvalue())
            else:
                destination.writestr(name, source.read(name))

    for model in reversed(EXPORT_MODELS):
        db.execute(delete(model))
    db.commit()
    imported = client.post(
        "/api/v1/imports/project",
        files={"file": ("legacy.zip", legacy.getvalue(), "application/zip")},
        headers=auth,
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["schema_version"] == 4
    db.expire_all()
    restored_loan = db.scalar(select(Loan))
    restored_payment = db.scalar(
        select(Transaction).where(Transaction.external_source.is_not(None))
    )
    assert restored_loan.schedule_mode == "manual"
    assert restored_payment.loan_id == restored_loan.id


def test_version_2_project_archive_defaults_monthly_category_estimate(client, auth, account, db):
    db.add(Category(name="Продукты", kind="expense"))
    db.commit()
    exported = client.get("/api/v1/exports/project")
    assert exported.status_code == 200
    legacy = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(exported.content)) as source,
        zipfile.ZipFile(legacy, "w") as destination,
    ):
        for name in source.namelist():
            if name in ("salary_rules.csv", "salary_matches.csv"):
                continue
            if name == "manifest.json":
                manifest = json.loads(source.read(name))
                manifest["schema_version"] = 2
                manifest["files"] = [file for file in manifest["files"] if file not in ("salary_rules.csv", "salary_matches.csv")]
                destination.writestr(name, json.dumps(manifest))
            elif name in ("categories.csv", "app_settings.csv"):
                reader = csv.DictReader(io.StringIO(source.read(name).decode("utf-8")))
                removed = "monthly_estimate" if name == "categories.csv" else "salary_enabled"
                fields = [field for field in reader.fieldnames or [] if field != removed]
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                for row in reader:
                    writer.writerow({field: row[field] for field in fields})
                destination.writestr(name, output.getvalue())
            else:
                destination.writestr(name, source.read(name))

    for model in reversed(EXPORT_MODELS):
        db.execute(delete(model))
    db.commit()
    imported = client.post(
        "/api/v1/imports/project",
        files={"file": ("version2.zip", legacy.getvalue(), "application/zip")},
        headers=auth,
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["schema_version"] == 4
    db.expire_all()
    assert db.scalar(select(Category).where(Category.name == "Продукты")).monthly_estimate is False


def test_project_import_rejects_traversal(client, auth):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../manifest.json", '{"schema_version": 1}')
    response = client.post(
        "/api/v1/imports/project",
        files={"file": ("unsafe.zip", payload.getvalue(), "application/zip")},
        headers=auth,
    )
    assert response.status_code == 422
