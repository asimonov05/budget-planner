from __future__ import annotations

from sqlalchemy import delete

from app.api.io import EXPORT_MODELS
from app.models import Loan, PlanItem, Transaction


def test_auto_loan_links_plan_and_actual_payment_without_double_counting(client, auth, account):
    loan_response = client.post(
        "/api/v1/loans",
        json={
            "name": "Ипотека",
            "account_id": account.id,
            "principal_minor": 1_000_000,
            "principal_as_of": "2026-01-01",
            "annual_rate_bps": 1_200,
            "interest_method": "simple",
            "schedule_mode": "auto",
            "first_payment_date": "2026-02-01",
            "end_date": "2027-01-01",
        },
        headers=auth,
    )
    assert loan_response.status_code == 201, loan_response.text
    loan = loan_response.json()
    projection_response = client.get(f"/api/v1/loans/{loan['id']}/projection")
    assert projection_response.status_code == 200, projection_response.text
    projection = projection_response.json()["baseline"]
    first = projection["rows"][0]
    assert first["interest_minor"] == 10_192
    assert first["principal_minor"] + first["interest_minor"] == first["payment_minor"]
    assert projection["rows"][-1]["remaining_principal_minor"] == 0

    planned = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "expense",
            "title": "Платёж по ипотеке",
            "amount_minor": first["payment_minor"],
            "date": "2026-02-01",
            "loan_id": loan["id"],
        },
        headers=auth,
    )
    assert planned.status_code == 201, planned.text
    assert planned.json()["loan_id"] == loan["id"]
    february = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 1}).json()[
        "months"
    ][0]
    assert february["expense"] == first["payment_minor"]

    actual = client.post(
        "/api/v1/transactions",
        json={
            "type": "expense",
            "amount_minor": first["payment_minor"],
            "date": "2026-02-01",
            "account_id": account.id,
            "loan_id": loan["id"],
            "description": "Платёж по ипотеке",
        },
        headers=auth,
    )
    assert actual.status_code == 201, actual.text
    assert actual.json()["loan_id"] == loan["id"]
    assert actual.json()["interest_component_minor"] == first["interest_minor"]
    assert actual.json()["principal_component_minor"] == first["principal_minor"]
    assert client.get("/api/v1/transactions", params={"loan_id": loan["id"]}).json()["total"] == 1
    assert (
        client.get("/api/v1/loans?include_archived=true").json()["items"][0]["principal_minor"]
        == first["remaining_principal_minor"]
    )
    february = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 1}).json()[
        "months"
    ][0]
    assert february["expense"] == first["payment_minor"]

    early = client.post(
        "/api/v1/transactions",
        json={
            "type": "expense",
            "amount_minor": 100_000,
            "date": "2026-02-01",
            "account_id": account.id,
            "loan_id": loan["id"],
            "prepayment_strategy": "reduce_payment",
            "description": "Досрочное погашение",
        },
        headers=auth,
    )
    assert early.status_code == 201, early.text
    assert early.json()["principal_component_minor"] == 100_000
    updated_loan = client.get("/api/v1/loans").json()["items"][0]
    assert updated_loan["annuity_payment_minor"] < loan["annuity_payment_minor"]

    delete = client.delete(
        f"/api/v1/transactions/{actual.json()['id']}",
        params={"version": actual.json()["version"]},
        headers=auth,
    )
    assert delete.status_code == 409


def test_early_repayment_preview_shows_both_strategies(client, auth):
    loan = client.post(
        "/api/v1/loans",
        json={
            "name": "Кредит",
            "principal_minor": 1_000_000,
            "principal_as_of": "2026-01-01",
            "annual_rate_bps": 1_200,
            "schedule_mode": "auto",
            "first_payment_date": "2026-02-01",
            "end_date": "2027-01-01",
        },
        headers=auth,
    ).json()
    previews = {}
    for strategy in ("reduce_term", "reduce_payment"):
        response = client.get(
            f"/api/v1/loans/{loan['id']}/projection",
            params={
                "early_payment_date": "2026-04-01",
                "early_amount_minor": 200_000,
                "early_strategy": strategy,
            },
        )
        assert response.status_code == 200, response.text
        previews[strategy] = response.json()
        assert response.json()["interest_savings_minor"] > 0
    assert (
        previews["reduce_term"]["scenario"]["payoff_date"]
        < previews["reduce_payment"]["scenario"]["payoff_date"]
    )
    assert (
        previews["reduce_term"]["scenario"]["interest_minor"]
        < previews["reduce_payment"]["scenario"]["interest_minor"]
    )


def test_existing_expense_can_be_linked_without_reducing_debt_twice(client, auth, account):
    loan = client.post(
        "/api/v1/loans",
        json={
            "name": "Кредит",
            "principal_minor": 50_000,
            "principal_as_of": "2026-02-01",
            "annual_rate_bps": 1_000,
            "schedule_mode": "auto",
            "first_payment_date": "2026-03-01",
            "end_date": "2026-08-01",
        },
        headers=auth,
    ).json()
    transaction = client.post(
        "/api/v1/transactions",
        json={
            "type": "expense",
            "amount_minor": 10_000,
            "date": "2026-01-15",
            "account_id": account.id,
            "description": "Старый платёж",
        },
        headers=auth,
    ).json()
    assert client.post("/api/v1/months/2026-01/close", headers=auth).status_code == 200

    linked = client.post(
        f"/api/v1/loans/{loan['id']}/transactions/{transaction['id']}/link",
        json={
            "principal_minor": 8_000,
            "interest_minor": 2_000,
            "already_reflected_in_balance": True,
        },
        headers={**auth, "Idempotency-Key": "historical-loan-link"},
    )
    assert linked.status_code == 200, linked.text
    repeated = client.post(
        f"/api/v1/loans/{loan['id']}/transactions/{transaction['id']}/link",
        json={
            "principal_minor": 8_000,
            "interest_minor": 2_000,
            "already_reflected_in_balance": True,
        },
        headers={**auth, "Idempotency-Key": "historical-loan-link"},
    )
    assert repeated.status_code == 200 and repeated.json() == linked.json()
    assert linked.json()["loan_principal_minor"] == 50_000
    detail = client.get("/api/v1/transactions").json()["items"][0]
    assert detail["loan_id"] == loan["id"]
    assert detail["principal_component_minor"] == 8_000
    assert detail["interest_component_minor"] == 2_000
    assert detail["loan_balance_applied"] is False
    unlinked = client.delete(
        f"/api/v1/loans/{loan['id']}/transactions/{transaction['id']}/link",
        params={"version": detail["version"]},
        headers=auth,
    )
    assert unlinked.status_code == 204
    assert client.get("/api/v1/transactions").json()["items"][0]["loan_id"] is None


def test_actual_early_payment_can_keep_annuity_and_shorten_term(client, auth, account):
    loan = client.post(
        "/api/v1/loans",
        json={
            "name": "Кредит",
            "account_id": account.id,
            "principal_minor": 1_000_000,
            "principal_as_of": "2026-01-01",
            "annual_rate_bps": 1_200,
            "schedule_mode": "auto",
            "first_payment_date": "2026-02-01",
            "end_date": "2027-01-01",
        },
        headers=auth,
    ).json()
    first = client.get(f"/api/v1/loans/{loan['id']}/projection").json()["baseline"]["rows"][0]
    for amount, strategy in (
        (first["payment_minor"], None),
        (200_000, "reduce_term"),
    ):
        response = client.post(
            "/api/v1/transactions",
            json={
                "type": "expense",
                "amount_minor": amount,
                "date": "2026-02-01",
                "account_id": account.id,
                "loan_id": loan["id"],
                "prepayment_strategy": strategy,
                "description": "Платёж по кредиту",
            },
            headers=auth,
        )
        assert response.status_code == 201, response.text
    current = client.get("/api/v1/loans").json()["items"][0]
    assert current["annuity_payment_minor"] == loan["annuity_payment_minor"]
    projected = client.get(f"/api/v1/loans/{loan['id']}/projection").json()["baseline"]
    assert projected["payoff_date"] < loan["end_date"]

    assert client.post("/api/v1/months/2026-02/close", headers=auth).status_code == 200
    renamed = client.patch(
        f"/api/v1/loans/{loan['id']}",
        json={
            "version": current["version"],
            "name": "Кредит после погашения",
            "principal_minor": current["principal_minor"],
            "principal_as_of": current["principal_as_of"],
            "annual_rate_bps": current["annual_rate_bps"],
            "interest_method": current["interest_method"],
            "schedule_mode": current["schedule_mode"],
            "first_payment_date": current["first_payment_date"],
            "end_date": current["end_date"],
        },
        headers=auth,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["annuity_payment_minor"] == loan["annuity_payment_minor"]


def test_project_archive_preserves_auto_loan_and_payment_links(client, auth, account, db):
    loan = client.post(
        "/api/v1/loans",
        json={
            "name": "Кредит",
            "account_id": account.id,
            "principal_minor": 100_000,
            "principal_as_of": "2026-01-01",
            "annual_rate_bps": 1_250,
            "interest_method": "compound",
            "schedule_mode": "auto",
            "first_payment_date": "2026-02-01",
            "end_date": "2026-12-01",
        },
        headers=auth,
    ).json()
    plan = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "expense",
            "title": "Кредитный платёж",
            "amount_minor": loan["annuity_payment_minor"],
            "date": "2026-02-01",
            "loan_id": loan["id"],
        },
        headers=auth,
    ).json()
    payment = client.post(
        "/api/v1/transactions",
        json={
            "type": "expense",
            "amount_minor": loan["annuity_payment_minor"],
            "date": "2026-02-01",
            "account_id": account.id,
            "loan_id": loan["id"],
            "description": "Кредитный платёж",
        },
        headers=auth,
    ).json()
    before = client.get("/api/v1/forecast", params={"from_month": "2026-03", "months": 1}).json()
    exported = client.get("/api/v1/exports/project")
    assert exported.status_code == 200

    for model in reversed(EXPORT_MODELS):
        db.execute(delete(model))
    db.commit()
    imported = client.post(
        "/api/v1/imports/project",
        files={"file": ("project.zip", exported.content, "application/zip")},
        headers=auth,
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["schema_version"] == 3
    db.expire_all()
    restored_loan = db.get(Loan, loan["id"])
    restored_plan = db.get(PlanItem, plan["id"])
    restored_payment = db.get(Transaction, payment["id"])
    assert restored_loan.annual_rate_bps == 1_250
    assert restored_loan.interest_method == "compound"
    assert restored_plan.loan_id == restored_payment.loan_id == restored_loan.id
    assert (
        restored_payment.principal_component_minor + restored_payment.interest_component_minor
        == (restored_payment.amount_minor)
    )
    assert (
        client.get("/api/v1/forecast", params={"from_month": "2026-03", "months": 1}).json()
        == before
    )


def test_archived_loan_does_not_leave_linked_plan_in_forecast(client, auth, account):
    loan = client.post("/api/v1/loans", json={"name": "Закрытый кредит"}, headers=auth).json()
    planned = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "expense",
            "title": "Платёж",
            "amount_minor": 10_000,
            "date": "2026-06-01",
            "loan_id": loan["id"],
        },
        headers=auth,
    )
    assert planned.status_code == 201
    before = client.get("/api/v1/forecast", params={"from_month": "2026-06", "months": 1}).json()[
        "months"
    ][0]
    assert before["expense"] == 10_000
    archived = client.patch(
        f"/api/v1/loans/{loan['id']}",
        json={"version": loan["version"], "archived": True},
        headers=auth,
    )
    assert archived.status_code == 200, archived.text
    after = client.get("/api/v1/forecast", params={"from_month": "2026-06", "months": 1}).json()[
        "months"
    ][0]
    assert after["expense"] == 0


def test_manual_schedule_and_linked_plan_count_once(client, auth, account):
    loan = client.post(
        "/api/v1/loans",
        json={"name": "Ручной кредит", "account_id": account.id},
        headers=auth,
    ).json()
    scheduled = client.post(
        f"/api/v1/loans/{loan['id']}/schedule",
        json={"due_date": "2026-02-01", "amount_minor": 10_000},
        headers=auth,
    ).json()
    linked_plan = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "expense",
            "title": "По кредиту",
            "amount_minor": 10_000,
            "date": "2026-02-01",
            "loan_id": loan["id"],
        },
        headers=auth,
    )
    assert linked_plan.status_code == 201
    before = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 1}).json()[
        "months"
    ][0]
    assert before["expense"] == 10_000

    paid = client.post(
        f"/api/v1/loans/{loan['id']}/schedule/{scheduled['id']}/payments",
        json={"amount_minor": 10_000, "date": "2026-02-01", "completed": True},
        headers=auth,
    )
    assert paid.status_code == 201, paid.text
    after = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 1}).json()[
        "months"
    ][0]
    assert after["expense"] == 10_000
