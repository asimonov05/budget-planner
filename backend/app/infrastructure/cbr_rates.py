"""Official Bank of Russia reference rates, cached only for performance."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from ..application.currency import SUPPORTED_CURRENCIES, cross_rate


CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
MAX_XML_BYTES = 256_000
CACHE_SECONDS = 30 * 60
_cache: dict[date, tuple[float, "DailyRates"]] = {}
_cache_lock = threading.Lock()


class RateUnavailable(Exception):
    pass


@dataclass(frozen=True)
class DailyRates:
    requested_date: date
    effective_date: date
    rub_per_currency: dict[str, Decimal]

    def quote(self, source: str, target: str) -> Decimal:
        if source not in SUPPORTED_CURRENCIES or target not in SUPPORTED_CURRENCIES:
            raise ValueError("Unsupported currency")
        try:
            return cross_rate(self.rub_per_currency[source], self.rub_per_currency[target])
        except KeyError as exc:
            raise RateUnavailable("The Bank of Russia does not quote this currency on that date") from exc


def parse_daily_xml(data: bytes, requested_date: date) -> DailyRates:
    try:
        root = ElementTree.fromstring(data)
        if root.tag != "ValCurs":
            raise ValueError("Unexpected exchange rate document")
        effective = datetime.strptime(root.attrib["Date"], "%d.%m.%Y").date()
        rates = {"RUB": Decimal(1)}
        for row in root.findall("Valute"):
            code = row.findtext("CharCode")
            if code not in SUPPORTED_CURRENCIES:
                continue
            unit_rate = row.findtext("VunitRate")
            if unit_rate:
                rate = Decimal(unit_rate.replace(",", "."))
            else:
                nominal = Decimal(row.findtext("Nominal") or "0")
                rate = Decimal((row.findtext("Value") or "").replace(",", ".")) / nominal
            if not rate.is_finite() or rate <= 0:
                raise ValueError("Invalid official rate")
            rates[code] = rate
        if len(rates) < 3:
            raise ValueError("The rate document is incomplete")
        return DailyRates(requested_date, effective, rates)
    except (ElementTree.ParseError, KeyError, ValueError, InvalidOperation, ZeroDivisionError) as exc:
        raise RateUnavailable("Could not read official exchange rates") from exc


def daily_rates(requested_date: date) -> DailyRates:
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    query_date = min(requested_date, today)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(query_date)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    url = f"{CBR_DAILY_URL}?{urlencode({'date_req': query_date.strftime('%d/%m/%Y')})}"
    try:
        with urlopen(Request(url, headers={"User-Agent": "BudgetPlanner/1.0"}), timeout=6) as response:
            data = response.read(MAX_XML_BYTES + 1)
        if len(data) > MAX_XML_BYTES:
            raise RateUnavailable("Official exchange rate document is too large")
        result = parse_daily_xml(data, query_date)
    except (URLError, TimeoutError, OSError) as exc:
        if cached:
            return cached[1]
        raise RateUnavailable("Official exchange rates are temporarily unavailable") from exc
    with _cache_lock:
        _cache[query_date] = (now, result)
        if len(_cache) > 64:
            oldest = min(_cache, key=lambda key: _cache[key][0])
            _cache.pop(oldest, None)
    return result
