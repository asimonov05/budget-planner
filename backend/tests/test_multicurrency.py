from datetime import date

from app.api.catalog import account_balance
from app.models import Account


def test_foreign_account_transfer_payment_and_forecast_stay_separate(client, auth, account, db):
    foreign = client.post('/api/v1/accounts', headers=auth, json={
        'name': 'Доллары', 'type': 'bank', 'currency': 'USD',
        'initial_balance_minor': 0, 'initial_balance_date': '2026-01-01',
    })
    assert foreign.status_code == 201, foreign.text
    usd_id = foreign.json()['id']
    assert foreign.json()['currency'] == 'USD'

    transfer = client.post('/api/v1/transfers', headers=auth, json={
        'from_account_id': account.id, 'to_account_id': usd_id,
        'amount_minor': 100_000, 'exchange_rate': '0.0125', 'date': '2026-02-01',
    })
    assert transfer.status_code == 201, transfer.text
    assert transfer.json()['amount_minor'] == 100_000
    assert transfer.json()['to_amount_minor'] == 1_250

    expense = client.post('/api/v1/transactions', headers=auth, json={
        'type': 'expense', 'amount_minor': 1_100, 'date': '2026-02-02',
        'account_id': usd_id, 'description': 'Покупка в евро',
        'merchant_currency': 'EUR', 'merchant_amount_minor': 1_000,
        'merchant_exchange_rate': '1.1',
    })
    assert expense.status_code == 201, expense.text
    assert expense.json()['merchant_currency'] == 'EUR'
    assert expense.json()['merchant_amount_minor'] == 1_000
    assert account_balance(db, db.get(Account, usd_id), date(2026, 2, 3)) == 150
    assert account_balance(db, account, date(2026, 2, 3)) == account.initial_balance_minor - 100_000

    usd = client.get('/api/v1/forecast', params={
        'from_month': '2026-02', 'months': 1, 'currency': 'USD',
    })
    rub = client.get('/api/v1/forecast', params={
        'from_month': '2026-02', 'months': 1, 'currency': 'RUB',
    })
    assert usd.status_code == rub.status_code == 200
    assert usd.json()['currency'] == 'USD'
    assert usd.json()['months'][0]['transfer_delta_minor'] == 1_250
    assert usd.json()['months'][0]['expense'] == 1_100
    assert usd.json()['months'][0]['c_end'] == 150
    assert rub.json()['months'][0]['transfer_delta_minor'] == -100_000
    assert rub.json()['months'][0]['expense'] == 0


def test_foreign_planned_payment_only_changes_its_currency_forecast(client, auth):
    account = client.post('/api/v1/accounts', headers=auth, json={
        'name': 'Доллары', 'type': 'bank', 'currency': 'USD',
        'initial_balance_minor': 10_000, 'initial_balance_date': '2026-01-01',
    }).json()
    planned = client.post('/api/v1/plan-items', headers=auth, json={
        'kind': 'expense', 'title': 'Подписка', 'amount_minor': 500,
        'date': '2026-02-01', 'account_id': account['id'],
    })
    assert planned.status_code == 201, planned.text
    assert planned.json()['currency'] == 'USD'
    usd = client.get('/api/v1/forecast', params={'from_month': '2026-02', 'months': 1, 'currency': 'USD'}).json()
    rub = client.get('/api/v1/forecast', params={'from_month': '2026-02', 'months': 1, 'currency': 'RUB'}).json()
    assert usd['months'][0]['expense'] == 500
    assert rub['months'] == []  # No RUB accounts in this budget.


def test_foreign_plan_without_account_has_its_own_forecast(client, auth):
    planned = client.post('/api/v1/plan-items', headers=auth, json={
        'kind': 'expense', 'title': 'Поездка', 'amount_minor': 12_000,
        'currency': 'EUR', 'date': '2026-02-01',
    })
    assert planned.status_code == 201, planned.text
    forecast = client.get('/api/v1/forecast', params={
        'from_month': '2026-02', 'months': 1, 'currency': 'EUR',
    })
    assert forecast.status_code == 200, forecast.text
    assert forecast.json()['months'][0]['expense'] == 12_000
