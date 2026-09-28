from __future__ import annotations

from datetime import date

from app.core.calculations import calculate_forecast, occurrence_date, split_evenly
from app.models import (
    BudgetLimit,
    Category,
    Goal,
    GoalReserveMovement,
    Loan,
    LoanScheduleItem,
    PlanItem,
    PlanMatch,
    PlanOverride,
    Transaction,
)


def month(result, value):
    return next(x for x in result["months"] if x["month"] == value)


def test_salary_once_override_zero_and_inherit(db, account):
    salary = PlanItem(
        kind="income",
        title="Зарплата",
        amount_minor=120_000_00,
        recurrence="monthly",
        start_date=date(2026, 10, 10),
        account_id=account.id,
    )
    extra = PlanItem(
        kind="income",
        title="Подработка",
        amount_minor=25_000_00,
        recurrence="none",
        month="2026-11",
        account_id=account.id,
    )
    db.add_all([salary, extra])
    db.commit()
    result = calculate_forecast(db, "2026-10", 3)
    assert [x["income"] for x in result["months"]] == [120_000_00, 145_000_00, 120_000_00]
    db.add(PlanOverride(plan_item_id=salary.id, month="2026-11", amount_minor=0))
    db.commit()
    assert month(calculate_forecast(db, "2026-11", 1), "2026-11")["income"] == 25_000_00
    db.query(PlanOverride).delete()
    db.commit()
    assert month(calculate_forecast(db, "2026-11", 1), "2026-11")["income"] == 145_000_00


def test_split_salary_and_end_date(db, account):
    db.add_all(
        [
            PlanItem(
                kind="income",
                title="Аванс",
                amount_minor=50_000_00,
                recurrence="monthly",
                start_date=date(2026, 1, 10),
                account_id=account.id,
            ),
            PlanItem(
                kind="income",
                title="Зарплата",
                amount_minor=70_000_00,
                recurrence="monthly",
                start_date=date(2026, 1, 25),
                account_id=account.id,
            ),
            PlanItem(
                kind="expense",
                title="Кредит",
                amount_minor=20_000_00,
                recurrence="monthly",
                start_date=date(2026, 1, 31),
                end_date=date(2026, 3, 31),
                account_id=account.id,
            ),
        ]
    )
    db.commit()
    result = calculate_forecast(db, "2026-03", 2)
    assert month(result, "2026-03")["income"] == 120_000_00
    assert month(result, "2026-03")["expense"] == 20_000_00
    assert month(result, "2026-04")["expense"] == 0


def test_matching_partial_and_complete_no_double_count(db, account):
    category = Category(name="Кредит", kind="expense")
    db.add(category)
    db.flush()
    plan = PlanItem(
        kind="expense",
        title="Платёж",
        amount_minor=20_000_00,
        date=date(2026, 2, 15),
        account_id=account.id,
        category_id=category.id,
    )
    fact = Transaction(
        type="expense",
        amount_minor=12_000_00,
        date=date(2026, 2, 15),
        account_id=account.id,
        category_id=category.id,
    )
    db.add_all([plan, fact])
    db.flush()
    db.add(
        PlanMatch(
            plan_item_id=plan.id,
            occurrence_month="2026-02",
            transaction_id=fact.id,
            amount_minor=12_000_00,
            completed=False,
        )
    )
    db.commit()
    feb = month(calculate_forecast(db, "2026-02", 1), "2026-02")
    assert feb["expense"] == 20_000_00
    match_record = db.query(PlanMatch).one()
    match_record.completed = True
    fact.amount_minor = 18_000_00
    match_record.amount_minor = 18_000_00
    db.commit()
    feb = month(calculate_forecast(db, "2026-02", 1), "2026-02")
    assert feb["expense"] == 18_000_00


def test_fully_matched_plan_and_fact_are_counted_once(db, account):
    category = Category(name="Кредит полный", kind="expense")
    db.add(category)
    db.flush()
    plan = PlanItem(
        kind="expense",
        title="Платёж",
        amount_minor=20_000_00,
        date=date(2026, 2, 15),
        account_id=account.id,
        category_id=category.id,
    )
    fact = Transaction(
        type="expense",
        amount_minor=20_000_00,
        date=date(2026, 2, 15),
        account_id=account.id,
        category_id=category.id,
    )
    db.add_all([plan, fact])
    db.flush()
    db.add(
        PlanMatch(
            plan_item_id=plan.id,
            occurrence_month="2026-02",
            transaction_id=fact.id,
            amount_minor=20_000_00,
            completed=True,
        )
    )
    db.commit()
    february = month(calculate_forecast(db, "2026-02", 1), "2026-02")
    assert february["expense"] == 20_000_00


def test_category_limit_inside_not_added_twice(db, account):
    category = Category(name="Авто", kind="expense")
    db.add(category)
    db.flush()
    db.add(BudgetLimit(category_id=category.id, amount_minor=15_000_00, start_month="2026-01"))
    db.add(
        PlanItem(
            kind="expense",
            title="Масло",
            amount_minor=8_000_00,
            month="2026-02",
            category_id=category.id,
        )
    )
    db.commit()
    feb = month(calculate_forecast(db, "2026-02", 1), "2026-02")
    assert feb["expense"] == 15_000_00
    assert feb["category_details"][0]["unallocated_minor"] == 7_000_00
    db.add(
        Transaction(
            type="expense",
            amount_minor=9_000_00,
            date=date(2026, 2, 5),
            account_id=account.id,
            category_id=category.id,
        )
    )
    db.commit()
    feb = month(calculate_forecast(db, "2026-02", 1), "2026-02")
    assert feb["expense"] == 17_000_00
    assert feb["category_details"][0]["exceeded_minor"] == 2_000_00


def test_goal_reserve_transitions_and_recommendation(db, account):
    goal = Goal(name="Отпуск", target_amount_minor=150_000_00, initial_reserved_minor=30_000_00)
    db.add(goal)
    db.flush()
    db.add(
        GoalReserveMovement(
            goal_id=goal.id, kind="allocation", amount_minor=20_000_00, date=date(2026, 1, 5)
        )
    )
    db.add(
        GoalReserveMovement(
            goal_id=goal.id, kind="expense", amount_minor=40_000_00, date=date(2026, 1, 10)
        )
    )
    db.add(
        Transaction(
            type="expense",
            amount_minor=40_000_00,
            date=date(2026, 1, 10),
            account_id=account.id,
            goal_id=goal.id,
        )
    )
    db.add(
        GoalReserveMovement(
            goal_id=goal.id, kind="refund", amount_minor=10_000_00, date=date(2026, 1, 12)
        )
    )
    db.add(
        Transaction(
            type="refund",
            amount_minor=10_000_00,
            date=date(2026, 1, 12),
            account_id=account.id,
            goal_id=goal.id,
        )
    )
    db.commit()
    jan = month(calculate_forecast(db, "2026-01", 1), "2026-01")
    assert (jan["c_end"], jan["r_end"], jan["f_end"]) == (170_000_00, 20_000_00, 150_000_00)
    assert sum(split_evenly(120_000_00, 6)) == 120_000_00
    assert split_evenly(120_000_00, 6) == [20_000_00] * 6


def test_goal_cash_reserve_free_staged_transitions(db, account):
    goal = Goal(
        name="Отпуск поэтапно", target_amount_minor=150_000_00, initial_reserved_minor=30_000_00
    )
    db.add(goal)
    db.flush()
    db.add(
        GoalReserveMovement(
            goal_id=goal.id,
            kind="allocation",
            amount_minor=20_000_00,
            date=date(2026, 2, 5),
        )
    )
    db.add_all(
        [
            GoalReserveMovement(
                goal_id=goal.id,
                kind="expense",
                amount_minor=40_000_00,
                date=date(2026, 3, 10),
            ),
            Transaction(
                type="expense",
                amount_minor=40_000_00,
                date=date(2026, 3, 10),
                account_id=account.id,
                goal_id=goal.id,
            ),
            GoalReserveMovement(
                goal_id=goal.id,
                kind="refund",
                amount_minor=10_000_00,
                date=date(2026, 4, 12),
            ),
            Transaction(
                type="refund",
                amount_minor=10_000_00,
                date=date(2026, 4, 12),
                account_id=account.id,
                goal_id=goal.id,
            ),
        ]
    )
    db.commit()
    result = calculate_forecast(db, "2026-01", 4)
    assert (
        month(result, "2026-01")["c_end"],
        month(result, "2026-01")["r_end"],
        month(result, "2026-01")["f_end"],
    ) == (200_000_00, 30_000_00, 170_000_00)
    assert (
        month(result, "2026-02")["c_end"],
        month(result, "2026-02")["r_end"],
        month(result, "2026-02")["f_end"],
    ) == (200_000_00, 50_000_00, 150_000_00)
    assert (
        month(result, "2026-03")["c_end"],
        month(result, "2026-03")["r_end"],
        month(result, "2026-03")["f_end"],
    ) == (160_000_00, 10_000_00, 150_000_00)
    assert (
        month(result, "2026-04")["c_end"],
        month(result, "2026-04")["r_end"],
        month(result, "2026-04")["f_end"],
    ) == (170_000_00, 20_000_00, 150_000_00)


def test_last_day_rule_recovers_after_february(db):
    item = PlanItem(
        kind="expense",
        title="31-е",
        amount_minor=1,
        recurrence="monthly",
        start_date=date(2028, 1, 31),
    )
    assert occurrence_date(item, "2028-02") == date(2028, 2, 29)
    assert occurrence_date(item, "2028-03") == date(2028, 3, 31)
    assert occurrence_date(item, "2027-02") == date(2027, 2, 28)


def test_loan_schedule_remaining_once(db, account):
    loan = Loan(name="Кредит", account_id=account.id)
    db.add(loan)
    db.flush()
    db.add(
        LoanScheduleItem(
            loan_id=loan.id,
            due_date=date(2026, 3, 5),
            amount_minor=20_000_00,
            paid_minor=12_000_00,
            status="partially_paid",
        )
    )
    db.commit()
    result = calculate_forecast(db, "2026-03", 2)
    assert month(result, "2026-03")["expense"] == 8_000_00
    assert month(result, "2026-04")["expense"] == 0


def test_account_opening_balance_enters_own_month(db):
    from app.models import Account

    db.add(
        Account(
            name="Поздний",
            type="bank",
            initial_balance_minor=50_000_00,
            initial_balance_date=date(2026, 3, 1),
        )
    )
    db.commit()
    result = calculate_forecast(db, "2026-02", 2)
    assert month(result, "2026-02")["c_end"] == 0
    assert month(result, "2026-03")["c_start"] == 50_000_00


def test_forecast_window_does_not_shift_carrying_balance(db, account):
    db.add(
        Transaction(
            type="expense",
            amount_minor=10_000_00,
            date=date(2026, 2, 10),
            account_id=account.id,
        )
    )
    db.commit()
    wide = calculate_forecast(db, "2026-01", 3)
    march_only = calculate_forecast(db, "2026-03", 1)
    assert month(wide, "2026-03")["c_start"] == 190_000_00
    assert month(march_only, "2026-03")["c_start"] == 190_000_00


def test_month_only_or_accountless_plan_marks_daily_forecast_incomplete(db, account):
    db.add_all(
        [
            PlanItem(
                kind="income",
                title="Подработка без даты",
                amount_minor=25_000_00,
                month="2026-11",
                account_id=account.id,
            ),
            PlanItem(
                kind="expense",
                title="Платёж без счёта",
                amount_minor=5_000_00,
                date=date(2026, 11, 20),
            ),
        ]
    )
    db.commit()
    november = month(calculate_forecast(db, "2026-11", 1), "2026-11")
    assert november["incomplete"] is True
    assert november["income"] == 25_000_00
    assert november["expense"] == 5_000_00
