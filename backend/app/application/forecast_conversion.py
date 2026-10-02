"""Indicative display conversion for already calculated single-currency forecasts."""

from __future__ import annotations

from decimal import Decimal

from .currency import convert_minor


MONEY_FIELDS = (
    "c_start", "r_start", "income", "expense", "actual_income",
    "actual_expense", "expected_income", "expected_expense",
    "estimated_expense_minor", "goal_allocations", "goal_releases",
    "goal_expenses", "goal_refunds", "adjustments", "transfer_delta_minor",
    "c_end", "r_end",
)
CATEGORY_MONEY_FIELDS = (
    "actual_minor", "expected_remaining_minor", "limit_minor",
    "unallocated_minor", "forecast_minor", "exceeded_minor",
    "estimated_monthly_minor", "estimated_added_minor",
)


def combine_forecasts(
    forecasts: dict[str, dict], base_currency: str, rates: dict[str, Decimal]
) -> list[dict]:
    """Show each currency at one reference-rate snapshot, without changing ledgers."""
    grouped: dict[str, dict] = {}
    for currency, forecast in forecasts.items():
        rate = rates[currency]
        for original in forecast["months"]:
            month = original["month"]
            aggregate = grouped.setdefault(month, {
                "month": month, "closed": bool(original["closed"]),
                "incomplete": False, "details": [], "category_details": [],
                **{field: 0 for field in MONEY_FIELDS},
            })
            aggregate["incomplete"] |= bool(original["incomplete"])
            for field in MONEY_FIELDS:
                aggregate[field] += convert_minor(original[field], currency, base_currency, rate)
            categories = aggregate.setdefault("_categories", {})
            for item in original.get("category_details", []):
                key = item["category_id"]
                values = categories.setdefault(key, {"category_id": key, "estimated_from_months": 0})
                values["estimated_from_months"] = max(values["estimated_from_months"], item.get("estimated_from_months", 0))
                for field in CATEGORY_MONEY_FIELDS:
                    amount = item.get(field)
                    if amount is not None:
                        values[field] = values.get(field, 0) + convert_minor(amount, currency, base_currency, rate)
    result = []
    for month in sorted(grouped):
        item = grouped[month]
        item["f_start"] = item["c_start"] - item["r_start"]
        item["f_end"] = item["c_end"] - item["r_end"]
        item["category_details"] = list(item.pop("_categories", {}).values())
        result.append(item)
    return result
