"""Estimated annuity schedules in integer minor currency units.

Interest uses actual calendar days and the actual number of days in each year.
The compound option capitalizes daily; the simple option charges interest only
on outstanding principal. A lender's contractual schedule remains authoritative.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

MAX_SAFE_MINOR = 9_007_199_254_740_991


@dataclass(frozen=True)
class PaymentRow:
    due_date: date
    payment_minor: int
    interest_minor: int
    principal_minor: int
    remaining_principal_minor: int
    early_principal_minor: int = 0


@dataclass(frozen=True)
class LoanProjection:
    regular_payment_minor: int
    rows: list[PaymentRow]
    interest_minor: int
    principal_minor: int
    total_minor: int
    payoff_date: date | None


def _round_minor(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def interest_for_period(
    principal_minor: int,
    annual_rate_bps: int,
    start_date: date,
    end_date: date,
    method: str,
) -> int:
    if principal_minor < 0 or annual_rate_bps < 0 or end_date < start_date:
        raise ValueError("Invalid loan interest period")
    if method not in ("simple", "compound"):
        raise ValueError("Unknown loan interest method")
    if principal_minor == 0 or annual_rate_bps == 0 or start_date == end_date:
        return 0
    principal = Decimal(principal_minor)
    accrued = Decimal(0)
    compounded = principal
    cursor = start_date
    while cursor < end_date:
        next_year = date(cursor.year + 1, 1, 1)
        segment_end = min(end_date, next_year)
        days = (segment_end - cursor).days
        days_in_year = 366 if calendar.isleap(cursor.year) else 365
        daily_rate = Decimal(annual_rate_bps) / Decimal(10_000 * days_in_year)
        if method == "simple":
            accrued += principal * daily_rate * days
        else:
            compounded *= (Decimal(1) + daily_rate) ** days
        cursor = segment_end
    return _round_minor(accrued if method == "simple" else compounded - principal)


def monthly_dates(first_due_date: date, end_date: date, after_date: date) -> list[date]:
    if end_date <= after_date or first_due_date > end_date:
        return []
    months = (end_date.year - first_due_date.year) * 12 + end_date.month - first_due_date.month + 1
    if months > 600:
        raise ValueError("Loan term exceeds 600 payments")
    anchor = first_due_date.day
    year, month = first_due_date.year, first_due_date.month
    result: list[date] = []
    while (year, month) <= (end_date.year, end_date.month):
        day = min(anchor, calendar.monthrange(year, month)[1])
        due = date(year, month, day)
        if after_date < due <= end_date:
            result.append(due)
        month += 1
        if month == 13:
            year, month = year + 1, 1
    if not result:
        return [end_date]
    if result[-1] != end_date:
        if (result[-1].year, result[-1].month) == (end_date.year, end_date.month):
            result[-1] = end_date
        else:
            result.append(end_date)
    return result


def _remaining_after(
    principal_minor: int,
    annual_rate_bps: int,
    method: str,
    as_of: date,
    due_dates: list[date],
    payment_minor: int,
) -> int:
    balance = principal_minor
    previous = as_of
    for due in due_dates:
        interest = interest_for_period(balance, annual_rate_bps, previous, due, method)
        balance = max(0, balance + interest - payment_minor)
        previous = due
    return balance


def annuity_payment(
    principal_minor: int,
    annual_rate_bps: int,
    method: str,
    as_of: date,
    due_dates: list[date],
) -> int:
    if principal_minor <= 0 or not due_dates:
        return 0
    low, high = 1, max(1, principal_minor)
    while _remaining_after(principal_minor, annual_rate_bps, method, as_of, due_dates, high):
        if high == MAX_SAFE_MINOR:
            raise ValueError("Calculated loan payment exceeds supported money range")
        high = min(high * 2, MAX_SAFE_MINOR)
    while low < high:
        middle = (low + high) // 2
        if _remaining_after(principal_minor, annual_rate_bps, method, as_of, due_dates, middle):
            low = middle + 1
        else:
            high = middle
    return low


def project_loan(
    principal_minor: int,
    annual_rate_bps: int,
    method: str,
    as_of: date,
    due_dates: list[date],
    *,
    regular_payment_minor: int | None = None,
    early_payment_date: date | None = None,
    early_principal_minor: int = 0,
    early_strategy: str | None = None,
) -> LoanProjection:
    if principal_minor < 0 or annual_rate_bps < 0:
        raise ValueError("Loan principal and rate must be nonnegative")
    if any(due <= as_of for due in due_dates) or due_dates != sorted(set(due_dates)):
        raise ValueError("Payment dates must be unique and after the balance date")
    if early_principal_minor < 0 or (early_principal_minor and early_payment_date not in due_dates):
        raise ValueError("Early payment must be on a scheduled payment date")
    if early_principal_minor and early_strategy not in ("reduce_term", "reduce_payment"):
        raise ValueError("Unknown early repayment strategy")
    payment = regular_payment_minor or annuity_payment(
        principal_minor, annual_rate_bps, method, as_of, due_dates
    )
    balance = principal_minor
    previous = as_of
    rows: list[PaymentRow] = []
    for index, due in enumerate(due_dates):
        if balance == 0:
            break
        interest = interest_for_period(balance, annual_rate_bps, previous, due, method)
        regular = min(payment, balance + interest)
        if index == len(due_dates) - 1:
            regular = balance + interest
        principal_paid = regular - interest
        if principal_paid < 0:
            raise ValueError("Regular payment does not cover accrued interest")
        balance -= principal_paid
        extra = 0
        if due == early_payment_date and early_principal_minor:
            extra = min(early_principal_minor, balance)
            balance -= extra
            if early_strategy == "reduce_payment" and balance:
                payment = annuity_payment(
                    balance, annual_rate_bps, method, due, due_dates[index + 1 :]
                )
        rows.append(
            PaymentRow(due, regular + extra, interest, principal_paid + extra, balance, extra)
        )
        previous = due
    total = sum(row.payment_minor for row in rows)
    if total > MAX_SAFE_MINOR:
        raise ValueError("Calculated loan total exceeds supported money range")
    return LoanProjection(
        regular_payment_minor=regular_payment_minor
        or annuity_payment(principal_minor, annual_rate_bps, method, as_of, due_dates),
        rows=rows,
        interest_minor=sum(row.interest_minor for row in rows),
        principal_minor=sum(row.principal_minor for row in rows),
        total_minor=total,
        payoff_date=rows[-1].due_date if rows and rows[-1].remaining_principal_minor == 0 else None,
    )
