from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date
from sqlalchemy import delete, select

from app.api.io import EXPORT_MODELS
from app.models import AppSettings, SalaryMatch, SalaryRule


def make_rule(client, auth, account, **changes):
    body = {
        "name": "Работодатель",
        "gross_minor": 10_000_000,
        "advance_share_bps": 4_000,
        "advance_day": 25,
        "salary_day": 10,
        "start_month": "2026-03",
        "account_id": account.id,
    }
    body.update(changes)
    response = client.post("/api/v1/salary-rules", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def enable(client, auth):
    settings = client.get("/api/v1/settings").json()
    response = client.patch("/api/v1/settings", json={"version": settings["version"], "salary_enabled": True}, headers=auth)
    assert response.status_code == 200, response.text


def test_net_salary_forecast_and_reconciliation(client, auth, account):
    rule = make_rule(client, auth, account)
    before = client.get("/api/v1/forecast", params={"from_month": "2026-03", "months": 1}).json()["months"][0]
    assert before["expected_income"] == 0
    enable(client, auth)
    payment = client.get("/api/v1/salary-payments", params={"month": "2026-03"}).json()["items"][0]
    assert (payment["gross_minor"], payment["tax_minor"], payment["net_minor"]) == (4_000_000, 520_000, 3_480_000)
    forecast = client.get("/api/v1/forecast", params={"from_month": "2026-03", "months": 1}).json()["months"][0]
    assert forecast["expected_income"] == 3_480_000
    receipt = client.post("/api/v1/transactions", json={
        "type": "income", "amount_minor": 3_480_000, "date": payment["date"],
        "account_id": account.id, "description": "Аванс",
    }, headers=auth)
    assert receipt.status_code == 201, receipt.text
    linked = client.post(f"/api/v1/salary-rules/{rule['id']}/matches", json={
        "earning_month": "2026-03", "component": "advance",
        "transaction_id": receipt.json()["id"], "amount_minor": 3_480_000,
    }, headers=auth)
    assert linked.status_code == 201, linked.text
    after = client.get("/api/v1/forecast", params={"from_month": "2026-03", "months": 1}).json()["months"][0]
    assert (after["actual_income"], after["expected_income"], after["income"]) == (3_480_000, 0, 3_480_000)
    assert client.delete(f"/api/v1/transactions/{receipt.json()['id']}", params={"version": receipt.json()["version"]}, headers=auth).status_code == 409
    assert client.delete(f"/api/v1/salary-matches/{linked.json()['id']}", headers=auth).status_code == 204
    assert client.get("/api/v1/salary-payments", params={"month": "2026-03"}).json()["items"][0]["remaining_minor"] == 3_480_000


def test_multiple_employers_have_separate_tax_bases(client, auth, account):
    make_rule(client, auth, account, name="Первый", gross_minor=300_000_00, initial_tax_base_minor=2_300_000_00, initial_tax_year=2026)
    make_rule(client, auth, account, name="Второй", gross_minor=100_000_00)
    enable(client, auth)
    payments = client.get("/api/v1/salary-payments", params={"month": "2026-03"}).json()["items"]
    assert len(payments) == 2
    by_name = {item["employer"]: item for item in payments}
    assert by_name["Первый"]["tax_minor"] == 1_600_000  # ₽100k at 13%, ₽20k at 15%
    assert by_name["Второй"]["tax_minor"] == 520_000


def test_salary_rule_can_start_before_account_opening_without_double_counting(client, auth, account, db):
    account.initial_balance_date = date(2026, 9, 29)
    db.commit()
    make_rule(client, auth, account, start_month="2026-09")
    enable(client, auth)

    september = client.get("/api/v1/salary-payments", params={"month": "2026-09"})
    assert september.status_code == 200
    assert september.json()["items"] == []  # The 25 September advance predates the opening balance.
    september_forecast = client.get("/api/v1/forecast", params={"from_month": "2026-09", "months": 1}).json()["months"][0]
    assert september_forecast["expected_income"] == 0

    october = client.get("/api/v1/salary-payments", params={"month": "2026-10"}).json()["items"]
    september_salary = next(item for item in october if item["earning_month"] == "2026-09" and item["component"] == "salary")
    assert september_salary["date"] == "2026-10-09"
    assert (september_salary["gross_minor"], september_salary["tax_minor"], september_salary["net_minor"]) == (6_000_000, 780_000, 5_220_000)


def test_salary_archive_roundtrip_and_old_export_compatibility(client, auth, account, db):
    rule = make_rule(client, auth, account)
    enable(client, auth)
    payment = client.get("/api/v1/salary-payments", params={"month": "2026-03"}).json()["items"][0]
    receipt = client.post("/api/v1/transactions", json={"type": "income", "amount_minor": payment["net_minor"], "date": payment["date"], "account_id": account.id, "description": "Аванс"}, headers=auth).json()
    assert client.post(f"/api/v1/salary-rules/{rule['id']}/matches", json={"earning_month": "2026-03", "component": "advance", "transaction_id": receipt["id"], "amount_minor": payment["net_minor"]}, headers=auth).status_code == 201
    before = client.get("/api/v1/forecast", params={"from_month": "2026-03", "months": 2}).json()
    exported = client.get("/api/v1/exports/project")
    assert exported.status_code == 200
    for model in reversed(EXPORT_MODELS):
        db.execute(delete(model))
    db.commit()
    imported = client.post("/api/v1/imports/project", files={"file": ("budget.zip", exported.content, "application/zip")}, headers=auth)
    assert imported.status_code == 200, imported.text
    assert imported.json()["schema_version"] == 7
    assert client.get("/api/v1/forecast", params={"from_month": "2026-03", "months": 2}).json() == before
    assert db.scalar(select(SalaryRule)) is not None
    assert db.scalar(select(SalaryMatch)) is not None
    db.expire_all()
    assert db.get(AppSettings, 1).salary_enabled is True


def test_v3_archive_restores_with_salary_disabled(client, auth, account, db):
    exported = client.get("/api/v1/exports/project").content
    legacy = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(exported)) as source, zipfile.ZipFile(legacy, "w") as target:
        for name in source.namelist():
            if name in ("salary_rules.csv", "salary_matches.csv"):
                continue
            if name == "manifest.json":
                manifest = json.loads(source.read(name))
                manifest["schema_version"] = 3
                manifest["files"] = [file for file in manifest["files"] if file not in ("salary_rules.csv", "salary_matches.csv")]
                target.writestr(name, json.dumps(manifest))
            elif name == "app_settings.csv":
                rows = csv.DictReader(io.StringIO(source.read(name).decode()))
                fields = [field for field in rows.fieldnames or [] if field != "salary_enabled"]
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                writer.writerows({field: row[field] for field in fields} for row in rows)
                target.writestr(name, output.getvalue())
            else:
                target.writestr(name, source.read(name))
    for model in reversed(EXPORT_MODELS):
        db.execute(delete(model))
    db.commit()
    result = client.post("/api/v1/imports/project", files={"file": ("old.zip", legacy.getvalue(), "application/zip")}, headers=auth)
    assert result.status_code == 200, result.text
    db.expire_all()
    assert db.get(AppSettings, 1).salary_enabled is False
