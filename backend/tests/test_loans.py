from __future__ import annotations

from datetime import date

import pytest

from app.core.loans import (
    MAX_SAFE_MINOR,
    annuity_payment,
    interest_for_period,
    monthly_dates,
    project_loan,
)


def test_interest_methods_and_zero_rate_annuity():
    start, first_due = date(2026, 1, 1), date(2026, 2, 1)
    assert interest_for_period(1_000_000, 1_200, start, first_due, "simple") == 10_192
    assert interest_for_period(1_000_000, 1_200, start, first_due, "compound") == 10_242
    assert (
        interest_for_period(133_590, 10_000, date(2024, 12, 31), date(2025, 1, 2), "simple") == 731
    )

    dates = monthly_dates(first_due, date(2027, 1, 1), start)
    projection = project_loan(120_000, 0, "simple", start, dates)
    assert len(projection.rows) == 12
    assert all(row.payment_minor == 10_000 for row in projection.rows)
    assert projection.interest_minor == 0
    assert projection.principal_minor == 120_000
    assert projection.rows[-1].remaining_principal_minor == 0


def test_early_repayment_can_reduce_term_or_payment():
    start = date(2026, 1, 1)
    dates = monthly_dates(date(2026, 2, 1), date(2027, 1, 1), start)
    baseline = project_loan(1_000_000, 1_200, "simple", start, dates)
    short_term = project_loan(
        1_000_000,
        1_200,
        "simple",
        start,
        dates,
        early_payment_date=dates[2],
        early_principal_minor=200_000,
        early_strategy="reduce_term",
    )
    lower_payment = project_loan(
        1_000_000,
        1_200,
        "simple",
        start,
        dates,
        early_payment_date=dates[2],
        early_principal_minor=200_000,
        early_strategy="reduce_payment",
    )

    assert baseline.regular_payment_minor == 88_826
    assert short_term.payoff_date == date(2026, 11, 1)
    assert lower_payment.payoff_date == date(2027, 1, 1)
    assert short_term.rows[3].payment_minor == baseline.rows[3].payment_minor
    assert lower_payment.rows[3].payment_minor < baseline.rows[3].payment_minor
    assert short_term.interest_minor < lower_payment.interest_minor < baseline.interest_minor
    assert short_term.principal_minor == lower_payment.principal_minor == baseline.principal_minor


def test_final_maturity_date_does_not_remove_prior_installment():
    dates = monthly_dates(date(2026, 2, 15), date(2027, 1, 10), date(2026, 1, 1))
    assert dates[-2:] == [date(2026, 12, 15), date(2027, 1, 10)]
    assert monthly_dates(date(2026, 1, 31), date(2026, 2, 15), date(2026, 1, 31)) == [
        date(2026, 2, 15)
    ]


def test_annuity_rejects_money_outside_the_supported_range():
    with pytest.raises(ValueError, match="supported money range"):
        annuity_payment(
            MAX_SAFE_MINOR,
            1_200,
            "simple",
            date(2026, 1, 1),
            [date(2026, 2, 1)],
        )
