from __future__ import annotations

import csv
import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import AuditLog
from sqlalchemy import select


def login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post('/api/v1/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return {'X-CSRF-Token': response.json()['csrf_token']}


def test_shared_database_scopes_accounts_categories_export_and_reset(client, auth, account):
    owner_category = client.post('/api/v1/categories', json={'name': 'Продукты', 'kind': 'expense'}, headers=auth)
    assert owner_category.status_code == 201
    created = client.post('/api/v1/users', json={'username': 'alice', 'password': 'alice strong passphrase'}, headers=auth)
    assert created.status_code == 201, created.text

    with TestClient(app) as alice_client:
        alice = login(alice_client, 'alice', 'alice strong passphrase')
        second_alice_client = TestClient(app)
        login(second_alice_client, 'alice', 'alice strong passphrase')
        assert alice_client.get('/api/v1/accounts').json()['items'] == []
        assert alice_client.get('/api/v1/categories').json()['items'] == []
        assert alice_client.patch(
            f'/api/v1/accounts/{account.id}',
            json={'name': 'Чужой счёт', 'version': account.version}, headers=alice,
        ).status_code == 404
        assert alice_client.get('/api/v1/users').status_code == 403
        own = alice_client.post('/api/v1/accounts', json={
            'name': 'Счёт Алисы', 'type': 'bank', 'initial_balance_minor': 12_000,
            'initial_balance_date': '2026-01-01',
        }, headers=alice)
        assert own.status_code == 201, own.text
        assert own.json()['id'] != account.id
        own_category = alice_client.post('/api/v1/categories', json={'name': 'Продукты', 'kind': 'expense'}, headers=alice)
        assert own_category.status_code == 201, own_category.text
        archive = alice_client.get('/api/v1/exports/project')
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as source:
            rows = list(csv.DictReader(io.StringIO(source.read('accounts.csv').decode())))
        assert [row['name'] for row in rows] == ['Счёт Алисы']
        assert 'user_id' not in rows[0]
        assert alice_client.post('/api/v1/budget/reset', json={
            'password': 'wrong', 'confirmation': 'RESET',
        }, headers=alice).status_code == 403
        assert alice_client.post('/api/v1/budget/reset', json={
            'password': 'alice strong passphrase', 'confirmation': 'wrong',
        }, headers=alice).status_code == 422
        assert alice_client.get('/api/v1/accounts').json()['total'] == 1
        reset = alice_client.post('/api/v1/budget/reset', json={
            'password': 'alice strong passphrase', 'confirmation': 'RESET',
        }, headers=alice)
        assert reset.status_code == 200, reset.text
        with SessionLocal() as db:
            assert db.scalar(select(AuditLog).where(AuditLog.user_id == created.json()['id'], AuditLog.action == 'reset')) is not None
        assert second_alice_client.get('/api/v1/auth/me').status_code == 401
        assert alice_client.get('/api/v1/auth/me').status_code == 200
        second_alice_client.close()
        assert alice_client.get('/api/v1/accounts').json()['items'] == []
        assert client.get('/api/v1/accounts').json()['items'][0]['id'] == account.id
        imported = alice_client.post('/api/v1/imports/project', files={
            'file': ('project.zip', archive.content, 'application/zip'),
        }, headers=alice)
        assert imported.status_code == 200, imported.text
        assert alice_client.get('/api/v1/accounts').json()['total'] == 1
        assert client.get('/api/v1/accounts').json()['total'] == 1


def test_reset_rolls_back_if_deletion_fails(client, auth, account, monkeypatch):
    from app.infrastructure import reset_budget as reset_storage
    from app.models import Account, User

    monkeypatch.setattr(reset_storage, 'deletion_order', lambda: [Account, User])
    with TestClient(app, raise_server_exceptions=False) as failing_client:
        login_headers = login(failing_client, 'owner', 'correct horse battery staple')
        result = failing_client.post('/api/v1/budget/reset', json={
            'password': 'correct horse battery staple', 'confirmation': 'RESET',
        }, headers=login_headers)
        assert result.status_code == 500
    assert client.get('/api/v1/accounts').json()['total'] == 1
