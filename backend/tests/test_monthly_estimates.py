from __future__ import annotations

from datetime import date

from app.core.calculations import calculate_forecast, monthly_category_average
from app.models import BudgetLimit, Category, Loan, PlanItem, Transaction


def test_only_expense_categories_can_enable_monthly_estimates(client, auth):
    invalid = client.post(
        "/api/v1/categories",
        json={"name": "Зарплата", "kind": "income", "monthly_estimate": True},
        headers=auth,
    )
    assert invalid.status_code == 422
    income = client.post(
        "/api/v1/categories",
        json={"name": "Другой доход", "kind": "income"},
        headers=auth,
    ).json()
    invalid_update = client.patch(
        f"/api/v1/categories/{income['id']}",
        json={"version": income["version"], "monthly_estimate": True},
        headers=auth,
    )
    assert invalid_update.status_code == 422
    category = client.post(
        "/api/v1/categories",
        json={"name": "Продукты", "kind": "expense"},
        headers=auth,
    ).json()
    assert category["monthly_estimate"] is False
    updated = client.patch(
        f"/api/v1/categories/{category['id']}",
        json={"version": category["version"], "monthly_estimate": True},
        headers=auth,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["monthly_estimate"] is True


def test_monthly_average_includes_zero_months_and_uses_only_completed_months():
    history = {
        (1, "2026-06"): 10_000,
        (1, "2026-08"): 20_000,
        (1, "2026-09"): 100_000,
    }
    assert monthly_category_average(history, 1, "2026-09", "2026-09", "2026-01") == (
        10_000,
        3,
    )
    assert monthly_category_average(history, 1, "2026-12", "2026-09", "2026-01") == (
        10_000,
        3,
    )
    assert monthly_category_average(history, 1, "2026-02", "2026-09", "2026-01") == (
        0,
        1,
    )
    assert monthly_category_average(history, 1, "2026-01", "2026-09", "2026-01") == (
        None,
        0,
    )
    assert monthly_category_average(history, 1, "2026-09", "2026-09", "2026-08") == (
        20_000,
        1,
    )
    assert monthly_category_average({(1, "2026-06"): 2}, 1, "2026-09", "2026-09", "2026-01") == (
        1,
        3,
    )


def test_monthly_category_estimate_fills_only_unplanned_spending(db, account):
    category = Category(name="Продукты", kind="expense", monthly_estimate=True)
    db.add(category)
    db.flush()
    for month, amount in ((6, 20_000_00), (7, 40_000_00), (8, 30_000_00), (9, 5_000_00)):
        db.add(
            Transaction(
                type="expense",
                amount_minor=amount,
                date=date(2026, month, 5),
                account_id=account.id,
                category_id=category.id,
                description="Продукты",
            )
        )
    loan = Loan(name="Кредит")
    db.add(loan)
    db.flush()
    db.add(
        Transaction(
            type="expense",
            amount_minor=90_000_00,
            date=date(2026, 6, 10),
            account_id=account.id,
            category_id=category.id,
            loan_id=loan.id,
            description="Кредитный платёж",
        )
    )
    db.add(
        PlanItem(
            kind="expense",
            title="Продукты по плану",
            amount_minor=10_000_00,
            date=date(2026, 10, 20),
            category_id=category.id,
            account_id=account.id,
        )
    )
    db.add(BudgetLimit(category_id=category.id, amount_minor=15_000_00, start_month="2026-10"))
    db.commit()

    september, october = calculate_forecast(db, "2026-09", 2, as_of=date(2026, 9, 15))["months"]
    assert september["expense"] == 30_000_00
    assert september["estimated_expense_minor"] == 25_000_00
    assert october["expense"] == 30_000_00
    assert october["estimated_expense_minor"] == 15_000_00
    detail = october["category_details"][0]
    assert detail["estimated_monthly_minor"] == 30_000_00
    assert detail["estimated_from_months"] == 3
    assert detail["estimated_added_minor"] == 15_000_00
    assert detail["forecast_minor"] == 30_000_00
    assert october["incomplete"] is True
    category.monthly_estimate = False
    category.version += 1
    db.commit()
    without_estimate = calculate_forecast(db, "2026-09", 2, as_of=date(2026, 9, 15))["months"][-1]
    assert october["f_end"] == without_estimate["f_end"] - 40_000_00


def test_budget_limit_already_covering_average_does_not_add_estimate(db, account):
    category = Category(name="Быт", kind="expense", monthly_estimate=True)
    db.add(category)
    db.flush()
    db.add(
        Transaction(
            type="expense",
            amount_minor=12_000_00,
            date=date(2026, 8, 10),
            account_id=account.id,
            category_id=category.id,
            description="Быт",
        )
    )
    db.add(BudgetLimit(category_id=category.id, amount_minor=10_000_00, start_month="2026-10"))
    db.commit()

    october = calculate_forecast(db, "2026-10", 1, as_of=date(2026, 9, 15))["months"][0]
    assert october["category_details"][0]["estimated_monthly_minor"] == 4_000_00
    assert october["expense"] == 10_000_00
    assert october["estimated_expense_minor"] == 0
