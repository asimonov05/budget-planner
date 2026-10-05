from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.models import Category, Tag, Transaction


def test_suggestions_rank_same_description_and_skip_other_operation_types(client, auth, account, db):
    category = Category(name="Кафе", kind="expense")
    tag = Tag(name="Работа")
    db.add_all([category, tag])
    db.flush()
    db.add_all([
        Transaction(type="expense", amount_minor=250_00, date=date(2026, 9, 10),
                    account_id=account.id, category_id=category.id, description="Кофе", tags=[tag]),
        Transaction(type="expense", amount_minor=310_00, date=date(2026, 9, 20),
                    account_id=account.id, category_id=category.id, description="Кофе", tags=[tag]),
        Transaction(type="expense", amount_minor=500_00, date=date(2026, 9, 21),
                    account_id=account.id, category_id=category.id, description="Кофейня"),
        Transaction(type="income", amount_minor=900_00, date=date(2026, 9, 22),
                    account_id=account.id, description="Кофе"),
    ])
    db.commit()

    response = client.get('/api/v1/transactions/suggestions', params={
        'query': 'Коф', 'type': 'expense', 'account_id': account.id,
    })
    assert response.status_code == 200, response.text
    items = response.json()['items']
    assert [item['description'] for item in items] == ['Кофе', 'Кофейня']
    assert items[0]['amount_minor'] == 310_00
    assert items[0]['category_id'] == category.id
    assert items[0]['account_id'] == account.id
    assert items[0]['account_name'] == account.name
    assert items[0]['category_name'] == 'Кафе'
    assert items[0]['tag_ids'] == [tag.id]
    assert items[0]['date'] == '2026-09-20'


def test_suggestion_query_treats_sql_wildcards_as_text(client, auth, account, db):
    db.add(Transaction(type="expense", amount_minor=100, date=date(2026, 9, 20),
                       account_id=account.id, description="10% скидка"))
    db.add(Transaction(type="expense", amount_minor=200, date=date(2026, 9, 21),
                       account_id=account.id, description="Покупка"))
    db.commit()
    response = client.get('/api/v1/transactions/suggestions', params={
        'query': '10%', 'type': 'expense',
    })
    assert response.status_code == 200, response.text
    assert [item['description'] for item in response.json()['items']] == ['10% скидка']


def test_suggestions_require_session(client):
    assert client.get('/api/v1/transactions/suggestions', params={
        'query': 'Коф', 'type': 'expense',
    }).status_code == 401


def test_suggestions_are_scoped_to_the_current_user(client, auth, account, db):
    db.add(Transaction(type="expense", amount_minor=120_00, date=date(2026, 9, 20),
                       account_id=account.id, description="Кофе владельца"))
    db.commit()
    created = client.post('/api/v1/users', headers=auth, json={
        'username': 'alice', 'password': 'alice strong passphrase',
    })
    assert created.status_code == 201, created.text

    with TestClient(app) as alice:
        login = alice.post('/api/v1/auth/login', json={
            'username': 'alice', 'password': 'alice strong passphrase',
        })
        assert login.status_code == 200, login.text
        headers = {'X-CSRF-Token': login.json()['csrf_token']}
        own_account = alice.post('/api/v1/accounts', headers=headers, json={
            'name': 'Карта Алисы', 'type': 'bank',
            'initial_balance_minor': 0, 'initial_balance_date': '2026-01-01',
        })
        assert own_account.status_code == 201, own_account.text
        own_expense = alice.post('/api/v1/transactions', headers=headers, json={
            'type': 'expense', 'amount_minor': 300_00, 'date': '2026-09-21',
            'account_id': own_account.json()['id'], 'description': 'Кофе Алисы',
        })
        assert own_expense.status_code == 201, own_expense.text
        suggestions = alice.get('/api/v1/transactions/suggestions', params={
            'query': 'Кофе', 'type': 'expense',
        })
        assert [item['description'] for item in suggestions.json()['items']] == ['Кофе Алисы']

    suggestions = client.get('/api/v1/transactions/suggestions', params={
        'query': 'Кофе', 'type': 'expense',
    })
    assert [item['description'] for item in suggestions.json()['items']] == ['Кофе владельца']
