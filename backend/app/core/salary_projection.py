"""Salary projections shared by the API and cash forecast."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, SalaryMatch, SalaryRule
from .ru_payroll import SalaryRule as PayrollRule, add_months, salary_payouts


def projected_salary_payments(db: Session, through_month: str) -> list[dict]:
    matched: dict[tuple[int, str, str], int] = defaultdict(int)
    match_items: dict[tuple[int, str, str], list[dict]] = defaultdict(list)
    for item in db.scalars(select(SalaryMatch)).all():
        key = item.salary_rule_id, item.earning_month, item.component
        matched[key] += item.amount_minor
        match_items[key].append({"id": item.id, "transaction_id": item.transaction_id, "amount_minor": item.amount_minor})
    result: list[dict] = []
    for rule in db.scalars(select(SalaryRule).where(SalaryRule.archived.is_(False))).all():
        account = db.get(Account, rule.account_id) if rule.account_id else None
        for payment in salary_payouts(
            PayrollRule(
                gross_minor=rule.gross_minor,
                advance_share_bps=rule.advance_share_bps,
                advance_day=rule.advance_day,
                salary_day=rule.salary_day,
                start_month=rule.start_month,
                end_month=rule.end_month,
                initial_tax_base_minor=rule.initial_tax_base_minor,
                initial_tax_year=rule.initial_tax_year,
            ),
            add_months(through_month, 1),
        ):
            if payment.date.strftime("%Y-%m") > through_month or (
                account and payment.date < account.initial_balance_date
            ):
                continue
            paid = matched[rule.id, payment.earning_month, payment.component]
            result.append(
                {
                    **asdict(payment),
                    "salary_rule_id": rule.id,
                    "employer": rule.name,
                    "account_id": rule.account_id,
                    "category_id": rule.category_id,
                    "matched_minor": paid,
                    "matches": match_items[rule.id, payment.earning_month, payment.component],
                    "remaining_minor": max(0, payment.net_minor - paid),
                }
            )
    result.sort(key=lambda value: (value["date"], value["salary_rule_id"], value["component"]))
    return result
