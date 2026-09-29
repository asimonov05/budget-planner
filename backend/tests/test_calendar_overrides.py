from __future__ import annotations


def test_calendar_edits_one_recurring_income_and_can_restore_series(client, auth, account):
    created = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "income",
            "title": "Зарплата",
            "amount_minor": 100_000,
            "date": "2026-01-15",
            "recurrence": "monthly",
            "start_date": "2026-01-15",
            "account_id": account.id,
        },
        headers=auth,
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    february = client.get("/api/v1/plan-items", params={"month": "2026-02"}).json()["items"]
    assert len(february) == 1
    assert february[0]["occurrence_month"] == "2026-02"
    assert february[0]["base_amount_minor"] == 100_000
    assert february[0]["base_date"] == "2026-02-15"
    assert february[0]["has_override"] is False

    changed = client.put(
        f"/api/v1/plan-items/{plan_id}/overrides/2026-02",
        json={
            "amount_minor": 120_000,
            "moved_date": "2026-03-05",
            "version": created.json()["version"],
        },
        headers=auth,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == created.json()["version"] + 1
    stale = client.put(
        f"/api/v1/plan-items/{plan_id}/overrides/2026-02",
        json={"amount_minor": 90_000, "version": created.json()["version"]},
        headers=auth,
    )
    assert stale.status_code == 409
    assert client.get("/api/v1/plan-items", params={"month": "2026-02"}).json()["items"] == []
    march = client.get("/api/v1/plan-items", params={"month": "2026-03"}).json()["items"]
    assert {item["occurrence_month"] for item in march} == {"2026-02", "2026-03"}
    moved = next(item for item in march if item["occurrence_month"] == "2026-02")
    regular = next(item for item in march if item["occurrence_month"] == "2026-03")
    assert (moved["date"], moved["amount_minor"], moved["base_date"], moved["has_override"]) == (
        "2026-03-05",
        120_000,
        "2026-02-15",
        True,
    )
    assert (regular["date"], regular["amount_minor"]) == ("2026-03-15", 100_000)
    forecast = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 2}).json()[
        "months"
    ]
    assert [month["income"] for month in forecast] == [0, 220_000]

    restored = client.put(
        f"/api/v1/plan-items/{plan_id}/overrides/2026-02",
        json={
            "amount_minor": None,
            "moved_date": None,
            "cancelled": False,
            "version": changed.json()["version"],
        },
        headers=auth,
    )
    assert restored.status_code == 200 and restored.json()["inherited"] is True
    assert restored.json()["version"] == changed.json()["version"] + 1
    february = client.get("/api/v1/plan-items", params={"month": "2026-02"}).json()["items"]
    assert (february[0]["date"], february[0]["amount_minor"], february[0]["has_override"]) == (
        "2026-02-15",
        100_000,
        False,
    )
    assert len(client.get("/api/v1/plan-items", params={"month": "2026-03"}).json()["items"]) == 1


def test_calendar_cannot_edit_nonexistent_or_matched_occurrence(client, auth, account):
    plan = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "income",
            "title": "Зарплата",
            "amount_minor": 100_000,
            "date": "2026-01-15",
            "recurrence": "monthly",
            "start_date": "2026-01-15",
            "account_id": account.id,
        },
        headers=auth,
    ).json()
    missing = client.put(
        f"/api/v1/plan-items/{plan['id']}/overrides/2025-12",
        json={"amount_minor": 120_000},
        headers=auth,
    )
    assert missing.status_code == 422

    transaction = client.post(
        "/api/v1/transactions",
        json={
            "type": "income",
            "amount_minor": 100_000,
            "date": "2026-02-15",
            "account_id": account.id,
            "description": "Зарплата",
        },
        headers=auth,
    ).json()
    matched = client.post(
        f"/api/v1/plan-items/{plan['id']}/matches",
        json={
            "transaction_id": transaction["id"],
            "occurrence_month": "2026-02",
            "amount_minor": 100_000,
            "completed": True,
        },
        headers=auth,
    )
    assert matched.status_code == 201, matched.text
    blocked = client.put(
        f"/api/v1/plan-items/{plan['id']}/overrides/2026-02",
        json={"amount_minor": 120_000},
        headers=auth,
    )
    assert blocked.status_code == 409
