"""Estimated Russian resident salary payouts and progressive NDFL withholding.

The calculation covers ordinary wages from one tax agent without deductions,
regional coefficients, benefits, bonuses, or other taxable income. Tax is
calculated cumulatively by actual payment date and rounded to whole rubles.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .ru_calendar import previous_workday


NDFL_BRACKETS = (
    (2_400_000_00, 13),
    (5_000_000_00, 15),
    (20_000_000_00, 18),
    (50_000_000_00, 20),
    (None, 22),
)


@dataclass(frozen=True)
class SalaryRule:
    gross_minor: int
    advance_share_bps: int
    advance_day: int
    salary_day: int
    start_month: str
    end_month: str | None = None
    initial_tax_base_minor: int = 0
    initial_tax_year: int | None = None


@dataclass(frozen=True)
class SalaryPayout:
    earning_month: str
    component: str
    nominal_date: date
    date: date
    gross_minor: int
    tax_minor: int
    net_minor: int
    tax_year: int
    calendar_confirmed: bool
    tax_policy_confirmed: bool


def add_months(month: str, offset: int) -> str:
    year, number = map(int, month.split("-"))
    total = year * 12 + number - 1 + offset
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def payout_day(month: str, day: int) -> date:
    year, number = map(int, month.split("-"))
    return date(year, number, min(day, calendar.monthrange(year, number)[1]))


def ndfl_tax_minor(annual_base_minor: int) -> int:
    """NDFL on ordinary resident income using the 2026 progressive scale."""
    if annual_base_minor < 0:
        raise ValueError("Tax base cannot be negative")
    remainder = annual_base_minor
    previous_limit = 0
    tax = Decimal(0)
    for limit, percent in NDFL_BRACKETS:
        taxable = remainder if limit is None else min(remainder, limit - previous_limit)
        tax += Decimal(taxable) * Decimal(percent) / Decimal(100)
        remainder -= taxable
        if not remainder:
            break
        if limit is not None:
            previous_limit = limit
    rubles = (tax / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rubles) * 100


def salary_payouts(rule: SalaryRule, through_month: str) -> list[SalaryPayout]:
    if rule.gross_minor <= 0 or not 0 < rule.advance_share_bps < 10_000:
        raise ValueError("Salary and both payout shares must be positive")
    if not 16 <= rule.advance_day <= 31 or not 1 <= rule.salary_day <= 15:
        raise ValueError("Salary payout days must follow the two-half-month schedule")
    if rule.initial_tax_base_minor < 0:
        raise ValueError("Initial tax base cannot be negative")
    if rule.end_month and rule.end_month < rule.start_month:
        raise ValueError("Salary end month precedes start month")
    if through_month < rule.start_month:
        return []

    planned: list[tuple[date, str, str, date, int, bool]] = []
    month = rule.start_month
    for _ in range(1_000):
        if month > through_month or (rule.end_month and month > rule.end_month):
            break
        advance_gross = (rule.gross_minor * rule.advance_share_bps + 5_000) // 10_000
        for component, nominal_month, day, gross in (
            ("advance", month, rule.advance_day, advance_gross),
            ("salary", add_months(month, 1), rule.salary_day, rule.gross_minor - advance_gross),
        ):
            nominal = payout_day(nominal_month, day)
            paid, confirmed = previous_workday(nominal)
            planned.append((paid, month, component, nominal, gross, confirmed))
        month = add_months(month, 1)
    else:
        raise ValueError("Salary projection exceeds 1000 months")

    planned.sort(key=lambda row: (row[0], row[1], row[2] != "salary"))
    bases_by_year: dict[int, int] = {}
    taxes_by_year: dict[int, int] = {}
    result: list[SalaryPayout] = []
    for paid, earning_month, component, nominal, gross, confirmed in planned:
        year = paid.year
        if year not in bases_by_year:
            initial = rule.initial_tax_base_minor if year == rule.initial_tax_year else 0
            bases_by_year[year] = initial
            taxes_by_year[year] = ndfl_tax_minor(initial)
        bases_by_year[year] += gross
        cumulative_tax = ndfl_tax_minor(bases_by_year[year])
        withheld = cumulative_tax - taxes_by_year[year]
        taxes_by_year[year] = cumulative_tax
        result.append(
            SalaryPayout(
                earning_month=earning_month,
                component=component,
                nominal_date=nominal,
                date=paid,
                gross_minor=gross,
                tax_minor=withheld,
                net_minor=gross - withheld,
                tax_year=year,
                calendar_confirmed=confirmed,
                tax_policy_confirmed=year <= 2026,
            )
        )
    return result
