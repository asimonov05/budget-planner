from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Account,
    AppSettings,
    BudgetLimit,
    BudgetLimitOverride,
    BudgetMonth,
    Category,
    Goal,
    GoalReserveMovement,
    Loan,
    LoanScheduleItem,
    PlanItem,
    PlanMatch,
    PlanOverride,
    Transaction,
    Transfer,
)
from .loans import PaymentRow, monthly_dates, project_loan
from .salary_projection import projected_salary_payments
from .tenant import settings_for_user

MONTHLY_ESTIMATE_WINDOW = 3


def month_key(value: date) -> str:
    return value.strftime("%Y-%m")


def add_months(value: str, count: int) -> str:
    year, month = map(int, value.split("-"))
    total = year * 12 + month - 1 + count
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def monthly_category_average(
    spend_by_month: dict[tuple[int, str], int],
    category_id: int,
    target_month: str,
    current_month: str,
    accounting_start_month: str,
    window: int = MONTHLY_ESTIMATE_WINDOW,
) -> tuple[int | None, int]:
    """Average completed calendar months before the target, including zero months."""
    anchor = min(target_month, current_month)
    months = [
        month
        for offset in range(window, 0, -1)
        if (month := add_months(anchor, -offset)) >= accounting_start_month
    ]
    if not months:
        return None, 0
    total = sum(max(0, spend_by_month.get((category_id, month), 0)) for month in months)
    average, remainder = divmod(total, len(months))
    return average + (2 * remainder >= len(months)), len(months)


def app_current_month(settings: AppSettings | None, as_of: date | None = None) -> str:
    if as_of is not None:
        return month_key(as_of)
    try:
        zone = ZoneInfo(settings.timezone if settings else "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    return month_key(datetime.now(zone).date())


def occurrence_date(item: PlanItem, month: str) -> date | None:
    base = item.start_date or item.date
    if not base:
        return None
    year, month_num = map(int, month.split("-"))
    day = min(base.day, calendar.monthrange(year, month_num)[1])
    return date(year, month_num, day)


def occurs_in_month(item: PlanItem, month: str) -> bool:
    if item.status == "cancelled":
        return False
    if item.recurrence == "none":
        return (month_key(item.date) if item.date else item.month) == month
    current = occurrence_date(item, month)
    base = item.start_date or item.date
    if not current or not base or current < base:
        return False
    if item.end_date and current > item.end_date:
        return False
    if item.recurrence == "yearly" and current.month != base.month:
        return False
    return True


def effective_plan_amount(
    item: PlanItem, month: str, overrides: dict[tuple[int, str], PlanOverride]
) -> int | None:
    if not occurs_in_month(item, month):
        return None
    override = overrides.get((item.id, month))
    if override:
        if override.cancelled:
            return None
        if override.amount_minor is not None:
            return override.amount_minor
    return item.amount_minor


def projected_plan_occurrences(
    item: PlanItem,
    calendar_month: str,
    overrides: dict[tuple[int, str], PlanOverride],
) -> list[tuple[str, int, date | None]]:
    """Return nominal occurrences whose effective date falls in a calendar month.

    Matching remains anchored to the nominal month, so moving an occurrence
    across a month boundary neither loses its identity nor creates a duplicate
    alongside the destination month's regular occurrence.
    """
    nominal_months = {calendar_month}
    nominal_months.update(
        nominal_month
        for (plan_item_id, nominal_month), override in overrides.items()
        if plan_item_id == item.id
        and override.moved_date is not None
        and month_key(override.moved_date) == calendar_month
    )
    result = []
    for nominal_month in sorted(nominal_months):
        amount = effective_plan_amount(item, nominal_month, overrides)
        if amount is None:
            continue
        override = overrides.get((item.id, nominal_month))
        effective_date = (
            override.moved_date
            if override and override.moved_date
            else occurrence_date(item, nominal_month)
        )
        effective_month = month_key(effective_date) if effective_date else nominal_month
        if effective_month != calendar_month:
            continue
        result.append((nominal_month, amount, effective_date))
    return result


@dataclass
class CategoryDetail:
    category_id: int
    actual_minor: int = 0
    expected_remaining_minor: int = 0
    limit_minor: int | None = None
    unallocated_minor: int = 0
    forecast_minor: int = 0
    exceeded_minor: int = 0
    estimated_monthly_minor: int | None = None
    estimated_from_months: int = 0
    estimated_added_minor: int = 0


@dataclass
class MonthResult:
    month: str
    c_start: int
    r_start: int
    f_start: int
    income: int = 0
    expense: int = 0
    actual_income: int = 0
    actual_expense: int = 0
    expected_income: int = 0
    expected_expense: int = 0
    estimated_expense_minor: int = 0
    goal_allocations: int = 0
    goal_releases: int = 0
    goal_expenses: int = 0
    goal_refunds: int = 0
    adjustments: int = 0
    transfer_delta_minor: int = 0
    c_end: int = 0
    r_end: int = 0
    f_end: int = 0
    incomplete: bool = False
    closed: bool = False
    category_details: list[dict] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)


def calculate_forecast(
    db: Session,
    from_month: str,
    months: int,
    include_possible: bool = False,
    *,
    as_of: date | None = None,
    currency: str | None = None,
) -> dict:
    requested = [add_months(from_month, i) for i in range(months)]
    settings = settings_for_user(db)
    selected_currency = currency or (settings.currency if settings else "RUB")
    accounts = db.scalars(select(Account).where(Account.currency == selected_currency)).all()
    has_plans = db.scalar(select(func.count(PlanItem.id)).where(PlanItem.currency == selected_currency))
    if not accounts and not has_plans:
        return {"from_month": from_month, "currency": selected_currency, "months": [], "warnings": ["no_accounts"]}
    account_start_month = min(
        (month_key(account.initial_balance_date) for account in accounts),
        default=month_key(settings.accounting_start_date) if settings else from_month,
    )
    current_month = app_current_month(settings, as_of)
    reserve_start_month = (
        month_key(settings.accounting_start_date)
        if settings
        else account_start_month
    )
    history_start_month = max(
        reserve_start_month,
        account_start_month,
    )
    first_month = min(
        account_start_month,
        reserve_start_month,
        from_month,
    )
    through = requested[-1]
    timeline: list[str] = []
    current = first_month
    while current <= through:
        timeline.append(current)
        current = add_months(current, 1)

    transaction_month = (
        func.to_char(Transaction.date, "YYYY-MM")
        if db.bind.dialect.name == "postgresql"
        else func.strftime("%Y-%m", Transaction.date)
    ).label("month")
    transaction_rows = db.execute(
        select(
            transaction_month,
            Transaction.type,
            Transaction.category_id,
            Transaction.goal_id,
            Transaction.loan_id,
            func.sum(Transaction.amount_minor).label("amount_minor"),
            func.count(Transaction.id).label("transaction_count"),
        )
        .where(
            Transaction.date >= date.fromisoformat(f"{first_month}-01"),
            Transaction.date < date.fromisoformat(f"{add_months(through, 1)}-01"),
            Account.currency == selected_currency,
        )
        .join(Account, Account.id == Transaction.account_id)
        .group_by(
            transaction_month,
            Transaction.type,
            Transaction.category_id,
            Transaction.goal_id,
            Transaction.loan_id,
        )
    ).all()
    transactions_by_month: dict[str, list] = defaultdict(list)
    ordinary_spend_by_month: dict[tuple[int, str], int] = defaultdict(int)
    for transaction in transaction_rows:
        # PostgreSQL SUM(bigint) returns numeric/Decimal. Keep the forecast's
        # minor-unit fields as integers so the API emits JSON numbers.
        amount_minor = int(transaction.amount_minor)
        transactions_by_month[transaction.month].append((transaction, amount_minor))
        if (
            transaction.category_id is not None
            and transaction.goal_id is None
            and transaction.loan_id is None
            and transaction.type in ("expense", "refund")
        ):
            ordinary_spend_by_month[(transaction.category_id, transaction.month)] += (
                amount_minor
                if transaction.type == "expense"
                else -amount_minor
            )
    monthly_categories = {
        category.id: category
        for category in db.scalars(select(Category)).all()
        if category.kind == "expense" and category.monthly_estimate and not category.archived
    }
    plan_items = db.scalars(select(PlanItem).where(PlanItem.currency == selected_currency)).all()
    overrides = {(o.plan_item_id, o.month): o for o in db.scalars(select(PlanOverride)).all()}
    matches_by_occurrence: dict[tuple[int, str], list[PlanMatch]] = defaultdict(list)
    for match in db.scalars(select(PlanMatch)).all():
        matches_by_occurrence[(match.plan_item_id, match.occurrence_month)].append(match)
    is_base_currency = selected_currency == (settings.currency if settings else "RUB")
    limits = db.scalars(select(BudgetLimit)).all() if is_base_currency else []
    limit_overrides = {
        (o.budget_limit_id, o.month): o.amount_minor
        for o in db.scalars(select(BudgetLimitOverride)).all()
    }
    movements_by_month: dict[str, list[GoalReserveMovement]] = defaultdict(list)
    for movement in (db.scalars(select(GoalReserveMovement)).all() if is_base_currency else []):
        movements_by_month[month_key(movement.date)].append(movement)
    goals = db.scalars(select(Goal)).all() if is_base_currency else []
    closed = {
        m.month for m in db.scalars(select(BudgetMonth).where(BudgetMonth.status == "closed")).all()
    }
    salary_by_month: dict[str, list[dict]] = defaultdict(list)
    if settings and settings.salary_enabled and is_base_currency:
        for payout in projected_salary_payments(db, through):
            salary_by_month[month_key(payout["date"])].append(payout)

    initial_r = sum(g.initial_reserved_minor for g in goals)
    c, r = 0, 0
    introduced_accounts: set[int] = set()
    loan_items_by_month: dict[str, list[LoanScheduleItem]] = defaultdict(list)
    manual_loan_months: set[tuple[int, str]] = set()
    for loan_item in (db.scalars(select(LoanScheduleItem)).all() if is_base_currency else []):
        due_month = month_key(loan_item.due_date)
        loan_items_by_month[due_month].append(loan_item)
        if loan_item.status != "cancelled":
            manual_loan_months.add((loan_item.loan_id, due_month))
    auto_loan_rows_by_month: dict[str, list[tuple[int, PaymentRow]]] = defaultdict(list)
    auto_loan_ids: set[int] = set()
    archived_loan_ids: set[int] = set()
    for loan in (db.scalars(select(Loan)).all() if is_base_currency else []):
        if loan.archived:
            archived_loan_ids.add(loan.id)
            continue
        if loan.schedule_mode != "auto":
            continue
        auto_loan_ids.add(loan.id)
        if (
            not loan.principal_minor
            or loan.principal_as_of is None
            or loan.annual_rate_bps is None
            or loan.first_payment_date is None
            or loan.end_date is None
        ):
            continue
        due_dates = monthly_dates(loan.first_payment_date, loan.end_date, loan.principal_as_of)
        projection = project_loan(
            loan.principal_minor,
            loan.annual_rate_bps,
            loan.interest_method,
            loan.principal_as_of,
            due_dates,
            regular_payment_minor=loan.annuity_payment_minor,
        )
        for row in projection.rows:
            auto_loan_rows_by_month[month_key(row.due_date)].append((loan.id, row))
    results: list[MonthResult] = []
    account_ids = {account.id for account in accounts}
    transfer_delta_by_month: dict[str, int] = defaultdict(int)
    for transfer in db.scalars(
        select(Transfer).where(
            Transfer.date >= date.fromisoformat(f"{first_month}-01"),
            Transfer.date < date.fromisoformat(f"{add_months(through, 1)}-01"),
        )
    ).all():
        month = month_key(transfer.date)
        if transfer.from_account_id in account_ids:
            transfer_delta_by_month[month] -= transfer.amount_minor
        if transfer.to_account_id in account_ids:
            transfer_delta_by_month[month] += transfer.to_amount_minor

    for month in timeline:
        if month == reserve_start_month:
            r += initial_r
        for account in accounts:
            if (
                account.id not in introduced_accounts
                and month_key(account.initial_balance_date) == month
            ):
                c += account.initial_balance_minor
                introduced_accounts.add(account.id)
        result = MonthResult(
            month=month, c_start=c, r_start=r, f_start=c - r, closed=month in closed
        )
        result.transfer_delta_minor = transfer_delta_by_month.get(month, 0)
        if result.transfer_delta_minor:
            result.details.append({
                "source": "transfers",
                "kind": "transfer",
                "amount_minor": result.transfer_delta_minor,
            })
        category_actual: dict[int, int] = defaultdict(int)
        category_ordinary_actual: dict[int, int] = defaultdict(int)
        category_expected: dict[int, int] = defaultdict(int)

        for tx, amount_minor in transactions_by_month.get(month, []):
            if tx.type == "income":
                result.income += amount_minor
                result.actual_income += amount_minor
                result.details.append(
                    {
                        "source": "transactions",
                        "kind": "income",
                        "amount_minor": amount_minor,
                        "count": tx.transaction_count,
                    }
                )
            elif tx.type == "expense":
                result.expense += amount_minor
                result.actual_expense += amount_minor
                if tx.goal_id is None and tx.category_id:
                    category_actual[tx.category_id] += amount_minor
                    if tx.loan_id is None:
                        category_ordinary_actual[tx.category_id] += amount_minor
            elif tx.type == "refund":
                result.expense -= amount_minor
                result.actual_expense -= amount_minor
                if tx.goal_id is None and tx.category_id:
                    category_actual[tx.category_id] -= amount_minor
                    if tx.loan_id is None:
                        category_ordinary_actual[tx.category_id] -= amount_minor
            elif tx.type == "adjustment":
                result.adjustments += amount_minor

        for movement in movements_by_month.get(month, []):
            if movement.kind == "allocation":
                result.goal_allocations += movement.amount_minor
            elif movement.kind == "release":
                result.goal_releases += movement.amount_minor
            elif movement.kind == "expense":
                result.goal_expenses += movement.amount_minor
            elif movement.kind == "refund":
                result.goal_refunds += movement.amount_minor

        if month not in closed:
            for payout in salary_by_month.get(month, []):
                remaining = payout["remaining_minor"]
                if not remaining:
                    continue
                result.income += remaining
                result.expected_income += remaining
                if not payout["calendar_confirmed"] or not payout["tax_policy_confirmed"] or payout["account_id"] is None:
                    result.incomplete = True
                result.details.append({
                    "source": "salary_projection",
                    "kind": "income",
                    "salary_rule_id": payout["salary_rule_id"],
                    "employer": payout["employer"],
                    "earning_month": payout["earning_month"],
                    "component": payout["component"],
                    "date": payout["date"].isoformat(),
                    "gross_minor": payout["gross_minor"],
                    "tax_minor": payout["tax_minor"],
                    "net_minor": payout["net_minor"],
                    "amount_minor": remaining,
                    "calendar_confirmed": payout["calendar_confirmed"],
                    "tax_policy_confirmed": payout["tax_policy_confirmed"],
                })
            for loan_id, row in auto_loan_rows_by_month.get(month, []):
                result.expense += row.payment_minor
                result.expected_expense += row.payment_minor
                result.details.append(
                    {
                        "source": "loan_projection",
                        "loan_id": loan_id,
                        "kind": "expense",
                        "amount_minor": row.payment_minor,
                        "interest_minor": row.interest_minor,
                        "principal_minor": row.principal_minor,
                    }
                )
            for item in loan_items_by_month.get(month, []):
                if item.status in ("paid", "cancelled"):
                    continue
                remaining = max(0, item.amount_minor - item.paid_minor)
                result.expense += remaining
                result.expected_expense += remaining
                result.details.append(
                    {
                        "source": "loan_schedule",
                        "id": item.id,
                        "kind": "expense",
                        "amount_minor": remaining,
                    }
                )
            for item in plan_items:
                if item.loan_id is not None and (
                    item.loan_id in auto_loan_ids
                    or item.loan_id in archived_loan_ids
                    or (item.loan_id, month) in manual_loan_months
                ):
                    continue
                if item.certainty == "possible" and not include_possible:
                    continue
                for nominal_month, amount, effective_date in projected_plan_occurrences(
                    item, month, overrides
                ):
                    item_matches = matches_by_occurrence[(item.id, nominal_month)]
                    completed = (
                        any(match.completed for match in item_matches) or item.status == "fulfilled"
                    )
                    matched = sum(match.amount_minor for match in item_matches)
                    remaining = 0 if completed else max(0, amount - matched)
                    if not remaining:
                        continue
                    if item.kind == "income":
                        result.income += remaining
                        result.expected_income += remaining
                    elif item.funding_source == "goal":
                        result.expense += remaining
                        result.expected_expense += remaining
                        result.goal_expenses += remaining
                    else:
                        if item.category_id:
                            category_expected[item.category_id] += remaining
                        else:
                            result.expense += remaining
                            result.expected_expense += remaining
                    if effective_date is None:
                        result.incomplete = True
                    if item.account_id is None:
                        result.incomplete = True
                    result.details.append(
                        {
                            "source": "plan_item",
                            "id": item.id,
                            "occurrence_month": nominal_month,
                            "kind": item.kind,
                            "amount_minor": remaining,
                        }
                    )

            category_ids = set(category_actual) | set(category_expected) | set(monthly_categories)
            for limit in limits:
                if limit.start_month <= month and (not limit.end_month or month <= limit.end_month):
                    category_ids.add(limit.category_id)
            for category_id in sorted(category_ids):
                actual = category_actual[category_id]
                expected = category_expected[category_id]
                applicable = [
                    x
                    for x in limits
                    if x.category_id == category_id
                    and x.start_month <= month
                    and (not x.end_month or month <= x.end_month)
                ]
                effective_limit = None
                if applicable:
                    chosen = max(applicable, key=lambda x: x.start_month)
                    effective_limit = limit_overrides.get((chosen.id, month), chosen.amount_minor)
                budget_gap = (
                    max(0, (effective_limit or 0) - actual - expected)
                    if effective_limit is not None
                    else 0
                )
                estimated, sample_months = (
                    monthly_category_average(
                        ordinary_spend_by_month,
                        category_id,
                        month,
                        current_month,
                        history_start_month,
                    )
                    if category_id in monthly_categories
                    else (None, 0)
                )
                estimated_gap = (
                    max(0, estimated - category_ordinary_actual[category_id] - expected)
                    if estimated is not None
                    else 0
                )
                # The estimate fills only spending not already covered by facts,
                # plans, or the explicit category limit.
                unallocated = max(budget_gap, estimated_gap)
                estimated_added = max(0, estimated_gap - budget_gap)
                forecast = actual + expected + unallocated
                result.expense += expected + unallocated
                result.expected_expense += expected + unallocated
                result.estimated_expense_minor += estimated_added
                if estimated_added:
                    result.incomplete = True
                    result.details.append(
                        {
                            "source": "monthly_category_estimate",
                            "category_id": category_id,
                            "kind": "expense",
                            "amount_minor": estimated_added,
                            "monthly_average_minor": estimated,
                            "sample_months": sample_months,
                        }
                    )
                result.category_details.append(
                    CategoryDetail(
                        category_id=category_id,
                        actual_minor=actual,
                        expected_remaining_minor=expected,
                        limit_minor=effective_limit,
                        unallocated_minor=unallocated,
                        forecast_minor=forecast,
                        exceeded_minor=max(0, forecast - effective_limit)
                        if effective_limit is not None
                        else 0,
                        estimated_monthly_minor=estimated,
                        estimated_from_months=sample_months,
                        estimated_added_minor=estimated_added,
                    ).__dict__
                )

        result.c_end = (
            result.c_start + result.income - result.expense
            + result.adjustments + result.transfer_delta_minor
        )
        result.r_end = (
            result.r_start
            + result.goal_allocations
            - result.goal_releases
            - result.goal_expenses
            + result.goal_refunds
        )
        result.f_end = result.c_end - result.r_end
        c, r = result.c_end, result.r_end
        if month in requested:
            results.append(result)

    warnings: list[str] = []
    if any(x.c_end < 0 for x in results):
        warnings.append("negative_cash")
    if any(x.r_end < 0 for x in results):
        warnings.append("negative_reserve")
    return {"from_month": from_month, "currency": selected_currency, "months": [x.__dict__ for x in results], "warnings": warnings}


def goal_reserved(db: Session, goal: Goal, through: date | None = None) -> int:
    movements = db.scalars(
        select(GoalReserveMovement).where(GoalReserveMovement.goal_id == goal.id)
    ).all()
    result = goal.initial_reserved_minor
    for movement in movements:
        if through and movement.date > through:
            continue
        result += (
            movement.amount_minor
            if movement.kind in ("allocation", "refund")
            else -movement.amount_minor
        )
    return result


def goal_remaining_need(db: Session, goal: Goal) -> int:
    spent = sum(
        m.amount_minor if m.kind == "expense" else -m.amount_minor
        for m in db.scalars(
            select(GoalReserveMovement).where(GoalReserveMovement.goal_id == goal.id)
        ).all()
        if m.kind in ("expense", "refund")
    )
    return max(0, goal.target_amount_minor - spent - goal_reserved(db, goal))


def split_evenly(amount_minor: int, count: int) -> list[int]:
    if count <= 0:
        return []
    quotient, remainder = divmod(amount_minor, count)
    return [quotient + (1 if i < remainder else 0) for i in range(count)]
