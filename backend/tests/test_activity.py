from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.models import Account, Transaction, Transfer, User
from app.security import hash_password


def test_activity_requires_auth(client):
    assert client.get("/api/v1/activity").status_code == 401


def test_activity_paginates_transactions_and_transfers_with_full_day_totals(client, auth, db):
    assert client.get("/api/v1/activity").status_code == 200
    rub = Account(name="Карта", currency="RUB", initial_balance_minor=0, initial_balance_date=date(2026, 1, 1))
    usd = Account(name="Доллары", currency="USD", initial_balance_minor=0, initial_balance_date=date(2026, 1, 1))
    db.add_all([rub, usd])
    db.flush()
    today = date(2026, 10, 2)
    base = datetime(2026, 10, 2, 10, tzinfo=timezone.utc)
    entries = [
        Transaction(type="income", amount_minor=10_000, date=today, account_id=rub.id, description="Зарплата", created_at=base + timedelta(minutes=6)),
        Transaction(type="expense", amount_minor=3_000, date=today, account_id=rub.id, description="Кофе", created_at=base + timedelta(minutes=5)),
        Transaction(type="refund", amount_minor=500, date=today, account_id=rub.id, description="Возврат Кофе", created_at=base + timedelta(minutes=4)),
        Transaction(type="expense", amount_minor=60_000, merchant_currency="USD", merchant_amount_minor=700, merchant_exchange_rate=Decimal("85.714285714286"), date=today, account_id=rub.id, description="Покупка в USD", created_at=base + timedelta(minutes=3)),
        Transfer(from_account_id=rub.id, to_account_id=usd.id, amount_minor=5_000, to_amount_minor=50, exchange_rate=Decimal("0.01"), date=today, created_at=base + timedelta(minutes=2)),
        Transaction(type="adjustment", amount_minor=-1_000, date=today, account_id=rub.id, description="Корректировка", comment="Исправление", created_at=base + timedelta(minutes=1)),
        Transaction(type="expense", amount_minor=2_000, date=date(2026, 10, 1), account_id=rub.id, description="Вчера", created_at=base),
    ]
    db.add_all(entries)
    db.commit()

    first = client.get("/api/v1/activity?limit=2&offset=0").json()
    assert first["total"] == 7
    assert len(first["days"]) == 1
    day = first["days"][0]
    assert day["date"] == "2026-10-02"
    assert day["total_items"] == 6
    assert [item["transaction"]["description"] for item in day["items"]] == ["Зарплата", "Кофе"]
    assert {item["currency"]: item for item in day["totals"]} == {
        "RUB": {"currency": "RUB", "income_minor": 10_000, "expense_minor": 2_500},
        "USD": {"currency": "USD", "income_minor": 0, "expense_minor": 700},
    }
    pages = [first, *(client.get(f"/api/v1/activity?limit=2&offset={offset}").json() for offset in (2, 4, 6))]
    keys = [
        (item["kind"], item[item["kind"]]["id"])
        for page in pages for group in page["days"] for item in group["items"]
    ]
    assert len(keys) == len(set(keys)) == 7
    assert any(item["kind"] == "transfer" for group in pages[2]["days"] for item in group["items"])
    assert pages[3]["days"][0]["date"] == "2026-10-01"
    assert client.get("/api/v1/activity?limit=101").status_code == 422

    by_account = client.get("/api/v1/activity?search=Доллары").json()
    assert by_account["total"] == 1
    assert by_account["days"][0]["items"][0]["kind"] == "transfer"
    assert by_account["days"][0]["totals"] == []
    by_description = client.get("/api/v1/activity?search=Кофе").json()
    assert by_description["total"] == 2  # expense and refund
    assert by_description["days"][0]["totals"] == [{"currency": "RUB", "income_minor": 0, "expense_minor": 2_500}]
    assert client.get("/api/v1/activity?search=%25").json()["total"] == 0


def test_activity_is_scoped_to_authenticated_user(client, auth, db):
    assert client.get("/api/v1/activity").status_code == 200
    owner_account = Account(name="Владельца", currency="RUB", initial_balance_minor=0, initial_balance_date=date(2026, 1, 1))
    db.add(owner_account)
    db.flush()
    db.add(Transaction(type="income", amount_minor=1_000, date=date(2026, 10, 2), account_id=owner_account.id, description="Частный доход"))
    db.commit()
    alice = User(username="alice", password_hash=hash_password("correct horse battery staple"), active=True)
    db.add(alice)
    db.flush()
    db.info["user_id"] = alice.id
    alice_account = Account(name="Алисы", currency="RUB", initial_balance_minor=0, initial_balance_date=date(2026, 1, 1))
    alice_savings = Account(name="Копилка Алисы", currency="RUB", initial_balance_minor=0, initial_balance_date=date(2026, 1, 1))
    db.add_all([alice_account, alice_savings])
    db.flush()
    db.add_all([
        Transaction(type="expense", amount_minor=200, date=date(2026, 10, 2), account_id=alice_account.id, description="Частный расход"),
        Transfer(from_account_id=alice_account.id, to_account_id=alice_savings.id, amount_minor=100, to_amount_minor=100, exchange_rate=Decimal(1), date=date(2026, 10, 2)),
    ])
    db.commit()

    owner_items = client.get("/api/v1/activity").json()
    assert owner_items["total"] == 1
    assert owner_items["days"][0]["items"][0]["transaction"]["description"] == "Частный доход"
    with TestClient(app) as alice_client:
        login = alice_client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct horse battery staple"})
        assert login.status_code == 200
        alice_items = alice_client.get("/api/v1/activity").json()
        assert alice_items["total"] == 2
        assert {item["kind"] for item in alice_items["days"][0]["items"]} == {"transaction", "transfer"}
        assert next(item["transaction"]["description"] for item in alice_items["days"][0]["items"] if item["kind"] == "transaction") == "Частный расход"
