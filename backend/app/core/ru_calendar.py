"""Federal five-day production calendar for salary date estimates.

The 2025–2027 transfer sets come from the Russian Government's annual
resolutions. Years outside that range use federal holidays and weekends only
and are marked provisional in projections. Regional holidays are not included.
"""

from __future__ import annotations

from datetime import date, timedelta


OFF_DAYS = {
    2025: {date(2025, 5, 2), date(2025, 5, 8), date(2025, 6, 13), date(2025, 11, 3), date(2025, 12, 31)},
    2026: {date(2026, 1, 9), date(2026, 12, 31)},
    2027: {date(2027, 2, 22), date(2027, 11, 5), date(2027, 12, 31)},
}
WORKING_WEEKENDS = {
    2025: {date(2025, 11, 1)},
    2027: {date(2027, 2, 20)},
}
TRANSFERRED_INSTEAD_OF_NEXT_DAY = {
    2025: {date(2025, 2, 23), date(2025, 3, 8)},
}
CONFIRMED_YEARS = frozenset(OFF_DAYS)


def federal_holidays(year: int) -> set[date]:
    return {
        *(date(year, 1, day) for day in range(1, 9)),
        date(year, 2, 23),
        date(year, 3, 8),
        date(year, 5, 1),
        date(year, 5, 9),
        date(year, 6, 12),
        date(year, 11, 4),
    }


def observed_federal_holidays(year: int) -> set[date]:
    fixed = federal_holidays(year)
    observed: set[date] = set()
    for holiday in sorted(day for day in fixed if day.month != 1):
        if holiday.weekday() < 5 or holiday in TRANSFERRED_INSTEAD_OF_NEXT_DAY.get(year, set()):
            continue
        candidate = holiday + timedelta(days=1)
        while candidate.weekday() >= 5 or candidate in fixed or candidate in observed:
            candidate += timedelta(days=1)
        observed.add(candidate)
    return observed


def is_workday(day: date) -> bool:
    if day in WORKING_WEEKENDS.get(day.year, set()):
        return True
    if day.weekday() >= 5:
        return False
    return (
        day not in federal_holidays(day.year)
        and day not in OFF_DAYS.get(day.year, set())
        and day not in observed_federal_holidays(day.year)
    )


def previous_workday(day: date) -> tuple[date, bool]:
    """Return payout date and whether all traversed years have approved transfers."""
    current = day
    confirmed = current.year in CONFIRMED_YEARS
    for _ in range(40):
        if is_workday(current):
            return current, confirmed
        current -= timedelta(days=1)
        confirmed = confirmed and current.year in CONFIRMED_YEARS
    raise ValueError("No workday found near the salary payout date")
