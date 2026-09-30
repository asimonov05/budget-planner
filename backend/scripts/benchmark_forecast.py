"""Reproducible local benchmark for the 100k-operation / 24-month target."""

from __future__ import annotations

import os
import statistics
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path


benchmark_dir = Path(tempfile.mkdtemp(prefix="budget-forecast-benchmark-"))
os.environ["DATABASE_PATH"] = str(benchmark_dir / "benchmark.sqlite3")
os.environ["REQUIRE_SAFE_SQLITE"] = "0"

from app.core.calculations import calculate_forecast  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Account, Transaction  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        account = Account(
            name="Benchmark",
            type="bank",
            initial_balance_minor=10_000_000_00,
            initial_balance_date=date(2025, 1, 1),
        )
        db.add(account)
        db.commit()
        db.refresh(account)

    start = date(2025, 1, 1)
    rows = [
        {
            "type": "expense",
            "amount_minor": 100,
            "date": start + timedelta(days=index % 730),
            "account_id": account.id,
            "description": "benchmark",
            "version": 1,
        }
        for index in range(100_000)
    ]
    with engine.begin() as connection:
        connection.execute(Transaction.__table__.insert(), rows)

    with SessionLocal() as db:
        calculate_forecast(db, "2025-01", 24)
        durations = []
        for _ in range(20):
            started = time.perf_counter()
            calculate_forecast(db, "2025-01", 24)
            durations.append(time.perf_counter() - started)

    print(
        {
            "transactions": 100_000,
            "months": 24,
            "runs": len(durations),
            "p50_seconds": round(statistics.median(durations), 4),
            "p95_seconds": round(percentile(durations, 0.95), 4),
            "database": str(benchmark_dir / "benchmark.sqlite3"),
        }
    )


if __name__ == "__main__":
    main()
