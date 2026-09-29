from __future__ import annotations

from datetime import date

from app.core.ru_calendar import is_workday, previous_workday
from app.core.ru_payroll import SalaryRule, ndfl_tax_minor, salary_payouts


def test_confirmed_production_calendar_moves_paydays_backwards():
    assert not is_workday(date(2026, 1, 9))
    assert not is_workday(date(2026, 3, 9))
    assert not is_workday(date(2026, 12, 31))
    assert is_workday(date(2027, 2, 20))
    assert not is_workday(date(2027, 2, 22))
    assert previous_workday(date(2026, 2, 23)) == (date(2026, 2, 20), True)
    assert previous_workday(date(2027, 1, 10)) == (date(2026, 12, 30), True)
    assert previous_workday(date(2028, 1, 10))[1] is False


def test_resident_ndfl_uses_2026_progressive_brackets_and_whole_rubles():
    assert ndfl_tax_minor(2_400_000_00) == 312_000_00
    assert ndfl_tax_minor(5_000_000_00) == 702_000_00
    assert ndfl_tax_minor(20_000_000_00) == 3_402_000_00
    assert ndfl_tax_minor(50_000_000_00) == 9_402_000_00
    assert ndfl_tax_minor(50_000_100_00) == 9_402_022_00
    assert ndfl_tax_minor(4_00) == 100


def test_gross_salary_becomes_two_net_payouts_with_tax_on_each():
    rule = SalaryRule(
        gross_minor=100_000_00,
        advance_share_bps=4_000,
        advance_day=25,
        salary_day=10,
        start_month="2026-02",
    )
    advance, salary = salary_payouts(rule, "2026-02")
    assert (advance.component, advance.date, advance.gross_minor, advance.tax_minor, advance.net_minor) == (
        "advance", date(2026, 2, 25), 40_000_00, 5_200_00, 34_800_00,
    )
    assert (salary.component, salary.date, salary.gross_minor, salary.tax_minor, salary.net_minor) == (
        "salary", date(2026, 3, 10), 60_000_00, 7_800_00, 52_200_00,
    )


def test_progressive_tax_and_december_payout_use_actual_payment_year():
    rule = SalaryRule(
        gross_minor=300_000_00,
        advance_share_bps=4_000,
        advance_day=25,
        salary_day=10,
        start_month="2026-01",
    )
    payouts = salary_payouts(rule, "2026-12")
    assert len(payouts) == 24
    assert sum(payout.gross_minor for payout in payouts) == 3_600_000_00
    assert sum(payout.tax_minor for payout in payouts) == 492_000_00
    december_salary = next(
        payout for payout in payouts
        if payout.earning_month == "2026-12" and payout.component == "salary"
    )
    assert december_salary.nominal_date == date(2027, 1, 10)
    assert december_salary.date == date(2026, 12, 30)
    assert december_salary.tax_year == 2026
    assert december_salary.calendar_confirmed is True


def test_prior_year_tax_base_can_be_supplied_when_starting_midyear():
    rule = SalaryRule(
        gross_minor=100_000_00,
        advance_share_bps=4_000,
        advance_day=25,
        salary_day=10,
        start_month="2026-09",
        initial_tax_base_minor=2_400_000_00,
        initial_tax_year=2026,
    )
    advance, salary = salary_payouts(rule, "2026-09")
    assert advance.tax_minor == 6_000_00
    assert salary.tax_minor == 9_000_00
