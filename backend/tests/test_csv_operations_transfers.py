from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.api.catalog import account_balance
from app.models import Account, BudgetMonth, ImportBatch, Transaction, Transfer


EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "imports"


def preview(client, auth, content: str, import_type: str):
    return client.post(
        "/api/v1/imports/preview",
        files={"file": (f"{import_type}.csv", content.encode("utf-8"), "text/csv")},
        data={"import_type": import_type, "delimiter": ";", "date_format": "iso"},
        headers=auth,
    )


def confirm(client, auth, batch_id: int, *, create_references: bool = False):
    return client.post(
        f"/api/v1/imports/{batch_id}/confirm",
        json={"create_references": create_references}, headers=auth,
    )


def test_transfer_csv_round_trip_updates_both_balances_and_currency_forecasts(client, auth, account, db):
    dollars = Account(name="Доллары", type="bank", currency="USD", initial_balance_minor=5_000,
                      initial_balance_date=date(2026, 1, 1))
    savings = Account(name="Резерв", type="savings", currency="RUB", initial_balance_minor=0,
                      initial_balance_date=date(2026, 1, 1))
    db.add_all([dollars, savings])
    db.commit()
    content = (
        "date;from_account;to_account;amount;from_currency;to_currency;exchange_rate;to_amount;comment\n"
        "2026-02-01;Основной;Доллары;8000,00;RUB;USD;0,0125;100,00;Конвертация\n"
        "2026-02-02;Основной;Резерв;500,00;RUB;RUB;;500,00;Перевод\n"
    )
    checked = preview(client, auth, content, "transfers")
    assert checked.status_code == 200, checked.text
    assert checked.json()["errors"] == []
    rows = checked.json()["rows"]
    assert [row["normalized"]["to_amount_minor"] for row in rows] == [10_000, 50_000]
    assert rows[0]["normalized"]["exchange_rate"] == "0.012500000000"
    created = confirm(client, auth, checked.json()["batch_id"])
    assert created.status_code == 200, created.text
    assert created.json()["created_count"] == 2
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Transfer)) == 2
    foreign = db.scalar(select(Transfer).where(Transfer.to_account_id == dollars.id))
    assert foreign.exchange_rate == Decimal("0.012500000000")
    assert account_balance(db, account, date(2026, 2, 3)) == account.initial_balance_minor - 850_000
    assert account_balance(db, dollars, date(2026, 2, 3)) == 15_000
    assert account_balance(db, savings, date(2026, 2, 3)) == 50_000
    rub = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 1, "currency": "RUB"}).json()
    usd = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 1, "currency": "USD"}).json()
    assert rub["months"][0]["transfer_delta_minor"] == -800_000
    assert usd["months"][0]["transfer_delta_minor"] == 10_000

    repeated = preview(client, auth, content, "transfers")
    assert repeated.json()["duplicate_batch"] is True
    again = confirm(client, auth, checked.json()["batch_id"])
    assert again.json() == {"batch_id": checked.json()["batch_id"], "created_count": 2, "idempotent": True}
    assert db.scalar(select(func.count()).select_from(Transfer)) == 2
    other_file = preview(client, auth, content.replace("Конвертация", "Конвертация из банка"), "transfers")
    assert other_file.status_code == 200
    assert other_file.json()["rows"][0]["normalized"]["duplicate_candidate"] is True


def test_transaction_csv_preserves_purchase_currency_and_avoids_stable_duplicate(client, auth, account, db):
    content = (
        "date;amount;type;account;currency;category;tags;description;comment;external_id;merchant_currency;merchant_amount;exchange_rate\n"
        "2026-02-03;950,00;expense;Основной;RUB;Путешествия;отпуск;Билет;;bank-fx-1;EUR;10,00;95\n"
        "2026-02-04;190,00;refund;Основной;RUB;Путешествия;отпуск;Возврат;;bank-fx-2;EUR;2,00;95\n"
    )
    checked = preview(client, auth, content, "transactions")
    assert checked.status_code == 200, checked.text
    assert checked.json()["errors"] == []
    assert checked.json()["rows"][0]["normalized"]["merchant_amount_minor"] == 1_000
    created = confirm(client, auth, checked.json()["batch_id"], create_references=True)
    assert created.status_code == 200, created.text
    assert created.json()["created_count"] == 2
    db.expire_all()
    records = db.scalars(select(Transaction).order_by(Transaction.date)).all()
    assert [(row.amount_minor, row.merchant_currency, row.merchant_amount_minor) for row in records] == [
        (95_000, "EUR", 1_000), (19_000, "EUR", 200),
    ]
    assert all(row.merchant_exchange_rate == Decimal("95") for row in records)
    assert account_balance(db, account, date(2026, 2, 5)) == account.initial_balance_minor - 76_000
    forecast = client.get("/api/v1/forecast", params={"from_month": "2026-02", "months": 1}).json()
    assert forecast["months"][0]["expense"] == 76_000
    assert {tag.name for tag in records[0].tags} == {"отпуск"}

    changed_content = content.replace("Билет;;bank-fx-1", "Билет;другой файл;bank-fx-1")
    different_batch = preview(client, auth, changed_content, "transactions")
    assert different_batch.status_code == 200
    skipped = confirm(client, auth, different_batch.json()["batch_id"], create_references=True)
    assert skipped.status_code == 200
    assert skipped.json()["created_count"] == 0
    assert db.scalar(select(func.count()).select_from(Transaction)) == 2


def test_transfer_preview_rejects_invalid_rows_and_keeps_errors_on_repeat(client, auth, account, db):
    dollars = Account(name="Доллары", type="bank", currency="USD", initial_balance_minor=0,
                      initial_balance_date=date(2026, 1, 1))
    db.add(dollars)
    db.commit()
    content = (
        "date;from_account;to_account;amount;exchange_rate;to_amount\n"
        "2026-02-01;Основной;Доллары;8000,00;;100,00\n"
        "2026-02-02;Основной;Доллары;8000,00;0,0125;99,00\n"
        "2026-02-03;Основной;Основной;100,00;1;100,00\n"
        "2026-02-04;Основной;Доллары;1,001;0,0125;0,01\n"
    )
    checked = preview(client, auth, content, "transfers")
    assert checked.status_code == 200
    assert checked.json()["status"] == "invalid"
    assert len(checked.json()["errors"]) == 4
    repeated = preview(client, auth, content, "transfers")
    assert repeated.json()["duplicate_batch"] is True
    assert len(repeated.json()["errors"]) == 4
    blocked = confirm(client, auth, checked.json()["batch_id"])
    assert blocked.status_code == 409
    assert db.scalar(select(func.count()).select_from(Transfer)) == 0


def test_transfer_confirm_rolls_back_when_month_closes_after_preview(client, auth, account, db):
    savings = Account(name="Резерв", type="savings", currency="RUB", initial_balance_minor=0,
                      initial_balance_date=date(2026, 1, 1))
    db.add(savings)
    db.commit()
    content = (
        "date;from_account;to_account;amount\n"
        "2026-02-01;Основной;Резерв;100,00\n"
        "2026-03-01;Основной;Резерв;200,00\n"
    )
    checked = preview(client, auth, content, "transfers")
    assert checked.status_code == 200 and len(checked.json()["rows"]) == 2
    db.add(BudgetMonth(month="2026-03", status="closed"))
    db.commit()
    blocked = confirm(client, auth, checked.json()["batch_id"])
    assert blocked.status_code == 409
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Transfer)) == 0
    assert db.get(ImportBatch, checked.json()["batch_id"]).status == "previewed"


def test_transaction_preview_rejects_missing_columns_and_fractional_minor_units(client, auth, account):
    empty = preview(client, auth, "date;amount;type;account\n", "transactions")
    assert empty.status_code == 422
    assert "no data rows" in empty.text
    missing = preview(client, auth, "date;amount;type\n2026-02-01;10;expense\n", "transactions")
    assert missing.status_code == 422
    assert "account/account_id" in missing.text
    invalid = preview(client, auth,
        "date;amount;type;account\n2026-02-01;1,001;expense;Основной\n", "transactions")
    assert invalid.status_code == 200
    assert "too many fractional digits" in invalid.json()["errors"][0]["message"]
    mismatched = preview(client, auth,
        "date;amount;type;account;merchant_currency;merchant_amount;exchange_rate\n"
        "2026-02-01;950,00;expense;Основной;EUR;10,00;90\n", "transactions")
    assert mismatched.status_code == 200
    assert "does not match account debit" in mismatched.json()["errors"][0]["message"]


def test_account_name_collision_requires_numeric_id(client, auth, account, db):
    db.add(Account(name=account.name, type="bank", currency="RUB", initial_balance_minor=0,
                   initial_balance_date=date(2026, 1, 1)))
    db.commit()
    ambiguous = preview(client, auth,
        "date;amount;type;account\n2026-02-01;10,00;expense;Основной\n", "transactions")
    assert ambiguous.status_code == 200
    assert "ambiguous" in ambiguous.json()["errors"][0]["message"]
    by_id = preview(client, auth,
        f"date;amount;type;account_id\n2026-02-01;10,00;expense;{account.id}\n", "transactions")
    assert by_id.status_code == 200
    assert by_id.json()["errors"] == []
    both = preview(client, auth,
        f"date;amount;type;account;account_id\n2026-02-01;10,00;expense;Основной;{account.id}\n",
        "transactions")
    assert "use either account or account_id" in both.json()["errors"][0]["message"]


def test_documented_csv_examples_preview_and_confirm(client, auth, db):
    db.add_all([
        Account(name="Основная карта", type="bank", currency="RUB", initial_balance_minor=1_000_000,
                initial_balance_date=date(2026, 1, 1)),
        Account(name="Накопительный", type="savings", currency="RUB", initial_balance_minor=0,
                initial_balance_date=date(2026, 1, 1)),
        Account(name="Доллары", type="bank", currency="USD", initial_balance_minor=0,
                initial_balance_date=date(2026, 1, 1)),
    ])
    db.commit()
    for filename, import_type in (("transfers.csv", "transfers"), ("transactions-fx.csv", "transactions")):
        content = (EXAMPLES / filename).read_text(encoding="utf-8")
        checked = preview(client, auth, content, import_type)
        assert checked.status_code == 200, checked.text
        assert checked.json()["errors"] == [], (filename, checked.json()["errors"])
        created = confirm(client, auth, checked.json()["batch_id"], create_references=True)
        assert created.status_code == 200, created.text
    assert db.scalar(select(func.count()).select_from(Transfer)) == 2
    assert db.scalar(select(func.count()).select_from(Transaction)) == 1
