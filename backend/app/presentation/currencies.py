"""Currency catalogue and indicative reference-rate HTTP endpoints."""

from __future__ import annotations

from datetime import date

from babel.numbers import get_currency_name
from fastapi import APIRouter, Depends, HTTPException, Query

from ..application.currency import POPULAR_CURRENCIES, SUPPORTED_CURRENCIES, minor_digits
from ..infrastructure.cbr_rates import RateUnavailable, daily_rates
from ..security import require_user


router = APIRouter(prefix="/currencies", tags=["currencies"])


@router.get("")
def list_currencies(_=Depends(require_user)) -> dict:
    ordered = (*POPULAR_CURRENCIES, *(c for c in SUPPORTED_CURRENCIES if c not in POPULAR_CURRENCIES))
    return {"items": [
        {
            "code": code,
            "name": get_currency_name(code, locale="ru"),
            "minor_digits": minor_digits(code),
            "popular": code in POPULAR_CURRENCIES,
        }
        for code in ordered
    ]}


@router.get("/quote")
def quote_currency(
    from_currency: str = Query(min_length=3, max_length=3),
    to_currency: str = Query(min_length=3, max_length=3),
    on_date: date = Query(default_factory=date.today),
    _=Depends(require_user),
) -> dict:
    if from_currency not in SUPPORTED_CURRENCIES or to_currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=422, detail="Unsupported currency")
    if from_currency == to_currency:
        return {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "rate": "1",
            "requested_date": on_date.isoformat(),
            "effective_date": on_date.isoformat(),
            "source": "identity",
            "indicative": False,
        }
    try:
        rates = daily_rates(on_date)
        rate = rates.quote(from_currency, to_currency)
    except RateUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "from_currency": from_currency,
        "to_currency": to_currency,
        "rate": format(rate, "f"),
        "requested_date": on_date.isoformat(),
        "effective_date": rates.effective_date.isoformat(),
        "source": "CBR",
        "indicative": True,
    }
