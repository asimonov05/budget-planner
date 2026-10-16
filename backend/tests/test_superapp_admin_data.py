from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.api.users import lock_user_command
from app.db import Base, SessionLocal
from app.models import (
    Account, AuditLog, Category, Goal, GoalReserveMovement, Loan, LoanScheduleItem,
    PlanItem, PlanMatch, SalaryMatch, SalaryRule, Transaction, User,
)
from app.security import hash_password


BASE = "/api/v1/superapp/admin/tables"


def record_url(table, key):
    return f"{BASE}/{table}/record?key={json.dumps(key)}"


def reveal_url(table, key):
    return f"{BASE}/{table}/record/reveal?key={json.dumps(key)}"


def second_user():
    with SessionLocal() as db:
        user = User(username="secret-person@example.test", password_hash=hash_password("a secure second password"))
        db.add(user)
        db.commit()
        return user.id


def test_catalog_and_access(client, auth):
    response = client.get(BASE)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    tables = {t["name"]: t for t in response.json()["tables"]}
    assert set(tables) == set(Base.metadata.tables)
    assert tables["accounts"]["can_create"]
    assert not tables["audit_logs"]["can_edit"]
    assert not tables["users"]["can_delete"]
    assert all(not tables[name]["can_edit"] for name in ("sessions", "application_availability", "user_app_access"))
    client.cookies.clear()
    assert client.get(BASE).status_code == 401
    second_user()
    assert client.post("/api/v1/auth/login", json={
        "username": "secret-person@example.test", "password": "a secure second password",
    }).status_code == 200
    assert client.get(BASE).status_code == 403
    assert client.post(f"{BASE}/categories", json={"values": {"user_id": 1, "name": "bad"}}).status_code == 403


def test_masking_covers_list_detail_credentials_json_and_old_admin(client, auth, account):
    assert "Основной" not in client.get(f"{BASE}/accounts").text
    row = client.get(record_url("accounts", {"id": account.id})).json()
    assert row["values"]["name"] == "[скрыто]"
    assert row["values"]["initial_balance_minor"] == "[скрыто]"
    assert row["values"]["initial_balance_date"] == "[скрыто]"
    assert row["values"]["user_id"] == 1
    user = client.get(record_url("users", {"id": 1})).json()["values"]
    assert user["username"] == user["password_hash"] == "[скрыто]"
    session = client.get(f"{BASE}/sessions").json()["rows"][0]["values"]
    assert session["token_hash"] == session["csrf_hash"] == "[скрыто]"
    assert client.get(f"{BASE}/app_settings").json()["rows"][0]["values"]["display_rates_json"] == "[скрыто]"
    assert "owner" not in client.get("/api/v1/users").text
    assert client.get("/admin/", follow_redirects=False).status_code == 404
    assert client.get(f"{BASE}/accounts?sort=name").status_code == 422
    assert client.get(f"{BASE}/accounts?search=Основной").status_code == 422
    assert client.get(f"{BASE}/accounts?search=1").json()["total"] == 1


def test_reveal_personal_financial_and_date_fields_are_explicit_and_audited(client, auth, account):
    catalog = {t["name"]: t for t in client.get(BASE).json()["tables"]}
    columns = {c["name"]: c for c in catalog["accounts"]["columns"]}
    assert columns["name"]["revealable"]
    assert not columns["id"]["revealable"]
    expected = {"name": account.name, "initial_balance_minor": account.initial_balance_minor,
                "initial_balance_date": account.initial_balance_date.isoformat()}
    for column, value in expected.items():
        response = client.post(reveal_url("accounts", {"id": account.id}), headers=auth, json={"column": column})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"column": column, "value": value}
    # Revealing one value does not change the default list/detail contract.
    assert client.get(record_url("accounts", {"id": account.id})).json()["values"]["name"] == "[скрыто]"
    assert account.name not in client.get(f"{BASE}/accounts").text
    with SessionLocal() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.action == "admin_reveal")).all()
        assert len(logs) == 3
        assert {tuple(json.loads(log.after_json)["fields"]) for log in logs} == {(c,) for c in expected}
        assert all(log.before_json is None and account.name not in log.after_json for log in logs)
        assert db.get(Account, account.id).name == account.name


def test_reveal_allows_admin_to_inspect_another_owner_but_not_regular_user(client, auth):
    owner_id = second_user()
    with SessionLocal() as db:
        db.info["user_id"] = owner_id
        account = Account(user_id=owner_id, name="other-owner-private", initial_balance_date=date(2026, 1, 1))
        db.add(account)
        db.commit()
        account_id = account.id
    url = reveal_url("accounts", {"id": account_id})
    assert client.post(url, headers=auth, json={"column": "name"}).json() == {"column": "name", "value": "other-owner-private"}
    client.cookies.clear()
    assert client.post(url, headers=auth, json={"column": "name"}).status_code == 401
    response = client.post("/api/v1/auth/login", json={
        "username": "secret-person@example.test", "password": "a secure second password",
    })
    assert response.status_code == 200
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    assert client.post(url, headers=headers, json={"column": "name"}).status_code == 403


@pytest.mark.parametrize(("table", "column"), [
    ("users", "password_hash"), ("sessions", "token_hash"), ("sessions", "csrf_hash"),
    ("app_settings", "display_rates_json"), ("audit_logs", "before_json"),
    ("idempotency_records", "key"), ("idempotency_records", "response_json"),
    ("import_batches", "fingerprint"), ("accounts", "id"), ("accounts", "unknown_column"),
])
def test_reveal_rejects_credentials_json_and_unreviewed_fields(client, auth, table, column):
    response = client.post(reveal_url(table, {"id": 1}), headers=auth, json={"column": column})
    assert response.status_code == 403
    assert response.json()["message"] == "Это поле нельзя раскрыть"
    assert "value" not in response.json()
    catalog = next(t for t in client.get(BASE).json()["tables"] if t["name"] == table)
    assert all(not c["revealable"] for c in catalog["columns"] if c["name"] == column)


def test_reveal_checks_csrf_origin_key_and_current_admin_role(client, auth, account):
    url = reveal_url("accounts", {"id": account.id})
    data = {"column": "name"}
    assert client.post(url, json=data).status_code == 403
    assert client.post(url, headers={**auth, "Origin": "https://attacker.invalid"}, json=data).status_code == 403
    assert client.get(url).status_code == 405
    assert client.post(reveal_url("accounts", {"id": 999999}), headers=auth, json=data).status_code == 404
    assert client.post(reveal_url("accounts", {"wrong": 1}), headers=auth, json=data).status_code == 422
    assert client.post(url, headers=auth, json={**data, "all": True}).status_code == 422
    assert client.post(url, headers=auth, json={"column": "name; SELECT 1"}).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog.id).where(AuditLog.action == "admin_reveal")) is None
        db.execute(update(User).where(User.id == 1).values(is_admin=False))
        db.commit()
    assert client.post(url, headers=auth, json=data).status_code == 403


def test_crud_other_owner_and_revision(client, auth):
    owner_id = second_user()
    response = client.post(f"{BASE}/categories", headers=auth, json={"values": {
        "user_id": owner_id, "name": "private groceries", "kind": "expense",
    }})
    assert response.status_code == 201, response.text
    created = response.json()
    assert "private groceries" not in response.text
    url = record_url("categories", created["key"])
    original = client.get(url).json()
    changed = client.patch(url, headers=auth, json={"values": {"name": "private renamed", "archived": True}, "revision": original["revision"]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["values"]["archived"] is True
    assert changed.json()["values"]["version"] == 2
    assert client.patch(url, headers=auth, json={"values": {"archived": False}, "revision": original["revision"]}).status_code == 409
    with SessionLocal() as db:
        value = db.get(Category, created["key"]["id"])
        assert value.user_id == owner_id and value.name == "private renamed"
        audits = db.scalars(select(AuditLog).where(AuditLog.user_id == owner_id)).all()
        assert len(audits) == 2
        assert all("private" not in audit.after_json for audit in audits)
    assert client.request("DELETE", url, headers=auth, json={"revision": changed.json()["revision"]}).status_code == 204
    assert client.get(url).status_code == 404


def test_reject_mutations_without_csrf_foreign_origin_mask_and_owner_change(client, auth, account):
    url = record_url("accounts", {"id": account.id})
    revision = client.get(url).json()["revision"]
    data = {"values": {"archived": True}, "revision": revision}
    assert client.patch(url, json=data).status_code == 403
    assert client.patch(url, json=data, headers={**auth, "Origin": "https://attacker.invalid"}).status_code == 403
    for values in ({"name": "[скрыто]"}, {"user_id": 2}, {"initial_balance_minor": True}, {"unknown": "value"}):
        assert client.patch(url, headers=auth, json={"values": values, "revision": revision}).status_code == 422
    with SessionLocal() as db:
        assert not db.get(Account, account.id).archived


def test_composite_keys_relational_constraints_and_readonly(client, auth):
    result = client.post(f"{BASE}/budget_months", headers=auth, json={"values": {"user_id": 1, "month": "2026-08", "status": "open"}})
    assert result.status_code == 201, result.text
    record = result.json()
    url = record_url("budget_months", record["key"])
    assert client.get(url).status_code == 200
    assert client.request("DELETE", url, headers=auth, json={"revision": record["revision"]}).status_code == 204
    assert client.post(f"{BASE}/audit_logs", headers=auth, json={"values": {}}).status_code == 403
    owner_id = second_user()
    with SessionLocal() as db:
        db.add(Account(user_id=owner_id, name="not yours", initial_balance_date=date(2026, 1, 1)))
        # Fixture owner guard deliberately requires explicit target scope.
        db.info["user_id"] = owner_id
        db.commit()
    result = client.post(f"{BASE}/transactions", headers=auth, json={"values": {
        "user_id": 1, "account_id": 1, "type": "expense", "amount_minor": 100, "date": "2026-01-01",
    }})
    assert result.status_code == 409, result.text
    assert "not yours" not in result.text


def test_admin_cannot_disable_self_or_edit_credentials(client, auth):
    url = record_url("users", {"id": 1})
    revision = client.get(url).json()["revision"]
    for values in ({"active": False}, {"is_admin": False}):
        assert client.patch(url, headers=auth, json={"values": values, "revision": revision}).status_code == 409
    assert client.patch(url, headers=auth, json={"values": {"password_hash": "oops"}, "revision": revision}).status_code == 422


def test_coupled_ledger_tables_are_readonly_with_explanation(client, auth):
    catalog = {table["name"]: table for table in client.get(BASE).json()["tables"]}
    for name in ("plan_matches", "salary_matches", "goal_reserve_movements", "loan_schedule_items"):
        assert not any(catalog[name][key] for key in ("can_create", "can_edit", "can_delete"))
        assert catalog[name]["readonly_reason"]
        assert client.post(f"{BASE}/{name}", headers=auth, json={"values": {}}).status_code == 403


@pytest.mark.parametrize("link", ["plan", "salary", "goal", "loan", "manual_loan"])
def test_linked_transactions_cannot_be_edited_or_deleted(client, auth, db, account, link):
    transaction = Transaction(account_id=account.id, amount_minor=500, type="expense", date=date(2026, 2, 1))
    db.add(transaction)
    db.flush()
    if link == "plan":
        parent = PlanItem(kind="expense", title="private plan", amount_minor=500)
        db.add(parent)
        db.flush()
        db.add(PlanMatch(plan_item_id=parent.id, transaction_id=transaction.id,
                         occurrence_month="2026-02", amount_minor=500))
    elif link == "salary":
        parent = SalaryRule(name="private salary", gross_minor=100000, start_month="2026-01")
        db.add(parent)
        db.flush()
        db.add(SalaryMatch(salary_rule_id=parent.id, transaction_id=transaction.id,
                           earning_month="2026-02", component="salary", amount_minor=500))
    elif link == "goal":
        parent = Goal(name="private goal", target_amount_minor=10000)
        db.add(parent)
        db.flush()
        db.add(GoalReserveMovement(goal_id=parent.id, transaction_id=transaction.id,
                                  kind="spend", amount_minor=500, date=transaction.date))
    elif link == "loan":
        loan = Loan(name="private loan", principal_minor=10000)
        db.add(loan)
        db.flush()
        transaction.loan_id = loan.id
        transaction.loan_balance_applied = True
    else:
        transaction.external_source = "loan_schedule:17"
    db.commit()
    url = record_url("transactions", {"id": transaction.id})
    revision = client.get(url).json()["revision"]
    assert client.patch(url, headers=auth, json={
        "values": {"amount_minor": 100}, "revision": revision,
    }).status_code == 409
    assert client.request("DELETE", url, headers=auth, json={"revision": revision}).status_code == 409
    db.refresh(transaction)
    assert transaction.amount_minor == 500


def test_admin_cannot_forge_loan_payment_or_change_scheduled_loan(client, auth, db, account):
    loan = Loan(name="private loan", principal_minor=10000)
    db.add(loan)
    db.flush()
    db.add(LoanScheduleItem(loan_id=loan.id, due_date=date(2026, 2, 1), amount_minor=500))
    db.commit()
    result = client.post(f"{BASE}/transactions", headers=auth, json={"values": {
        "user_id": 1, "account_id": account.id, "type": "expense", "amount_minor": 500,
        "date": "2026-02-01", "loan_id": loan.id,
    }})
    assert result.status_code == 409
    url = record_url("loans", {"id": loan.id})
    revision = client.get(url).json()["revision"]
    assert client.patch(url, headers=auth, json={
        "values": {"principal_minor": 0}, "revision": revision,
    }).status_code == 409
    assert client.request("DELETE", url, headers=auth, json={"revision": revision}).status_code == 409
    renamed = client.patch(url, headers=auth, json={
        "values": {"name": "private replacement"}, "revision": revision,
    })
    assert renamed.status_code == 200
    assert "private" not in renamed.text
    db.refresh(loan)
    assert loan.principal_minor == 10000


def test_user_command_rechecks_cached_actor_after_role_change(db):
    cached_actor = db.get(User, 1)
    assert cached_actor.is_admin
    with SessionLocal() as other:
        other.execute(update(User).where(User.id == 1).values(is_admin=False))
        other.commit()
    with pytest.raises(HTTPException) as rejected:
        lock_user_command(db, cached_actor.id)
    assert rejected.value.status_code == 403
