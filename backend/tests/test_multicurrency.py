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


def test_cross_currency_movements_require_explicitly_chosen_rate(client, auth, account):
    foreign = client.post('/api/v1/accounts', headers=auth, json={
        'name': 'Доллары', 'type': 'bank', 'currency': 'USD',
        'initial_balance_minor': 0, 'initial_balance_date': '2026-01-01',
    }).json()
    transfer = client.post('/api/v1/transfers', headers=auth, json={
        'from_account_id': account.id, 'to_account_id': foreign['id'],
        'amount_minor': 10_000, 'date': '2026-02-01',
    })
    assert transfer.status_code == 422
    purchase = client.post('/api/v1/transactions', headers=auth, json={
        'type': 'expense', 'amount_minor': 8_000, 'date': '2026-02-01',
        'account_id': account.id, 'merchant_currency': 'USD',
        'merchant_amount_minor': 100, 'description': 'Покупка',
    })
    assert purchase.status_code == 422


def test_display_mode_and_converted_totals_use_manually_saved_rate(
    client, auth, account,
):
    settings = client.get('/api/v1/settings').json()
    changed = client.patch('/api/v1/settings', headers=auth, json={
        'currency_display_mode': 'converted', 'version': settings['version'],
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()['currency_display_mode'] == 'converted'

    usd = client.post('/api/v1/accounts', headers=auth, json={
        'name': 'USD', 'type': 'bank', 'currency': 'USD',
        'initial_balance_minor': 10_000, 'initial_balance_date': '2026-01-01',
    })
    assert usd.status_code == 201, usd.text
    plan = client.post('/api/v1/plan-items', headers=auth, json={
        'kind': 'expense', 'title': 'Подписка', 'amount_minor': 500,
        'account_id': usd.json()['id'], 'date': '2026-02-01',
    })
    assert plan.status_code == 201, plan.text
    rate_list = client.get('/api/v1/currencies/display-rates').json()
    assert rate_list['items'][0]['required'] is True
    assert rate_list['items'][0]['rate'] is None
    saved = client.put('/api/v1/currencies/display-rates/USD', headers=auth, json={
        'rate': '80', 'version': rate_list['version'],
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()['rate'] == '80.000000000000'
    separate = client.get('/api/v1/forecast', params={
        'from_month': '2026-02', 'months': 1, 'currency': 'USD',
    }).json()
    converted = client.get('/api/v1/forecast/converted', params={
        'from_month': '2026-02', 'months': 1,
    })
    assert converted.status_code == 200, converted.text
    body = converted.json()
    assert body['currency'] == 'RUB'
    assert body['rates']['USD'] == '80.000000000000'
    assert body['months'][0]['expense'] == 40_000
    assert body['months'][0]['c_end'] == account.initial_balance_minor + 760_000
    assert separate['months'][0]['c_end'] == 9_500

    total = client.get('/api/v1/accounts/converted-total')
    assert total.status_code == 200, total.text
    assert total.json()['total_minor'] == account.initial_balance_minor + 800_000
    assert total.json()['rate_source'] == 'manual'


def test_converted_totals_require_manually_saved_rate(client, auth):
    client.post('/api/v1/accounts', headers=auth, json={
        'name': 'USD', 'type': 'bank', 'currency': 'USD',
        'initial_balance_minor': 10_000, 'initial_balance_date': '2026-01-01',
    })

    assert client.get('/api/v1/accounts/converted-total').status_code == 409
    assert client.get('/api/v1/forecast/converted', params={
        'from_month': '2026-02', 'months': 1,
    }).status_code == 409
    assert client.get('/api/v1/forecast', params={
        'from_month': '2026-02', 'months': 1, 'currency': 'USD',
    }).status_code == 200
