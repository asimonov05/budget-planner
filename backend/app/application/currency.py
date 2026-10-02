"""Currency value objects and exact conversions in minor units."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


# ISO 4217 codes quoted daily by the Bank of Russia, plus the base currency RUB.
SUPPORTED_CURRENCIES = (
    "AED", "AMD", "AUD", "AZN", "BDT", "BHD", "BOB", "BRL", "BYN", "CAD",
    "CHF", "CNY", "CUP", "CZK", "DKK", "DZD", "EGP", "ETB", "EUR", "GBP",
    "GEL", "HKD", "HUF", "IDR", "INR", "IRR", "JPY", "KGS", "KRW", "KZT",
    "MDL", "MMK", "MNT", "NGN", "NOK", "NZD", "OMR", "PLN", "QAR", "RON",
    "RSD", "RUB", "SAR", "SEK", "SGD", "THB", "TJS", "TMT", "TRY", "UAH",
    "USD", "UZS", "VND", "ZAR",
)
POPULAR_CURRENCIES = ("RUB", "USD", "EUR", "CNY", "GBP", "CHF", "JPY", "AED", "KZT", "BYN")
ZERO_DECIMAL_CURRENCIES = frozenset({"JPY", "KRW", "VND"})
THREE_DECIMAL_CURRENCIES = frozenset({"BHD", "OMR"})
MAX_SAFE_MINOR = 9_007_199_254_740_991
RATE_SCALE = Decimal("0.000000000001")


def minor_digits(currency: str) -> int:
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {currency}")
    if currency in ZERO_DECIMAL_CURRENCIES:
        return 0
    if currency in THREE_DECIMAL_CURRENCIES:
        return 3
    return 2


def positive_rate(value: str | Decimal) -> Decimal:
    try:
        rate = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Invalid exchange rate") from exc
    if not rate.is_finite() or rate <= 0 or rate > Decimal("1000000000000"):
        raise ValueError("Exchange rate must be positive and finite")
    rounded = rate.quantize(RATE_SCALE, rounding=ROUND_HALF_UP)
    if rounded <= 0:
        raise ValueError("Exchange rate is smaller than supported precision")
    return rounded


def convert_minor(amount_minor: int, source: str, target: str, rate: str | Decimal) -> int:
    """Convert using target major units per one source major unit."""
    parsed = positive_rate(rate)
    source_scale = Decimal(10) ** minor_digits(source)
    target_scale = Decimal(10) ** minor_digits(target)
    converted = (
        Decimal(amount_minor) * parsed * target_scale / source_scale
    ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if abs(converted) > MAX_SAFE_MINOR:
        raise ValueError("Converted amount exceeds the supported range")
    return int(converted)


def cross_rate(rub_per_source: Decimal, rub_per_target: Decimal) -> Decimal:
    """Derive target per source from official RUB reference rates."""
    return positive_rate(rub_per_source / rub_per_target)


def effective_rate(
    source_minor: int, source_currency: str, target_minor: int, target_currency: str
) -> Decimal:
    """Derive the actual target-per-source rate from two recorded amounts."""
    if source_minor <= 0 or target_minor <= 0:
        raise ValueError("Exchange amounts must be positive")
    source_major = Decimal(source_minor) / (Decimal(10) ** minor_digits(source_currency))
    target_major = Decimal(target_minor) / (Decimal(10) ** minor_digits(target_currency))
    return positive_rate(target_major / source_major)


def parse_display_rates(raw: str, base_currency: str) -> dict[str, Decimal]:
    """Read manually saved target-per-source rates; never infer one from a quote."""
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid saved display rates") from exc
    if not isinstance(data, dict) or len(data) > len(SUPPORTED_CURRENCIES):
        raise ValueError("Invalid saved display rates")
    rates = {base_currency: Decimal(1)}
    for source, entry in data.items():
        if (
            source not in SUPPORTED_CURRENCIES or source == base_currency
            or not isinstance(entry, dict)
            or not isinstance(entry.get("rate"), str)
            or not isinstance(entry.get("updated_on"), str)
        ):
            raise ValueError("Invalid saved display rate entry")
        date.fromisoformat(entry["updated_on"])
        rates[source] = positive_rate(entry["rate"])
    return rates
