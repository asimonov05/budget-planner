from datetime import date

from app.api.catalog import account_balance
from app.models import Account, Transaction, Transfer


def test_current_account_balance_ignores_future_operations(db, account):
    savings = Account(
        name="Накопительный",
        type="savings",
        initial_balance_minor=5_000_00,
        initial_balance_date=date(2026, 1, 1),
    )
    future = Account(
        name="Будущий счёт",
        type="bank",
        initial_balance_minor=9_000_00,
        initial_balance_date=date(2027, 1, 1),
    )
    db.add_all([savings, future])
    db.flush()
    db.add_all([
        Transaction(type="income", amount_minor=2_000_00, date=date(2026, 2, 1), account_id=account.id),
        Transaction(type="expense", amount_minor=3_000_00, date=date(2026, 12, 1), account_id=account.id),
        Transfer(from_account_id=account.id, to_account_id=savings.id, amount_minor=1_000_00, date=date(2026, 2, 1)),
        Transfer(from_account_id=savings.id, to_account_id=account.id, amount_minor=4_000_00, date=date(2026, 12, 1)),
    ])
    db.commit()

    assert account_balance(db, account, date(2026, 9, 29)) == account.initial_balance_minor + 1_000_00
    assert account_balance(db, savings, date(2026, 9, 29)) == savings.initial_balance_minor + 1_000_00
    assert account_balance(db, future, date(2026, 9, 29)) == 0
    assert account_balance(db, account, date(2026, 12, 1)) == account.initial_balance_minor + 2_000_00
