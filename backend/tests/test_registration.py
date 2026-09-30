from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.main import app
from app.models import AppSettings, User
from app.security import clear_login_rate, verify_password


PASSWORD = 'a strong registration password'


def test_registration_creates_regular_user_and_starts_isolated_session(client, account):
    clear_login_rate('registration:testclient')
    result = client.post('/api/v1/auth/register', json={
        'username': 'alice', 'password': PASSWORD, 'is_admin': True, 'user_id': 1,
    }, headers={'Origin': 'http://testserver'})
    assert result.status_code == 201, result.text
    assert result.json()['user']['username'] == 'alice'
    assert result.json()['user']['is_admin'] is False
    assert result.cookies.get('budget_session')
    assert result.cookies.get('csrf_token') == result.json()['csrf_token']
    assert 'httponly' in result.headers['set-cookie'].lower()
    assert client.get('/api/v1/auth/me').json()['username'] == 'alice'
    assert client.get('/api/v1/accounts').json()['items'] == []
    assert client.get('/api/v1/users').status_code == 403
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == 'alice'))
        assert user and user.active and not user.is_admin
        assert verify_password(user.password_hash, PASSWORD)
        assert user.password_hash != PASSWORD


def test_registration_rejects_duplicate_invalid_input_and_cross_site(client):
    clear_login_rate('registration:testclient')
    body = {'username': 'alice', 'password': PASSWORD}
    assert client.post('/api/v1/auth/register', json=body).status_code == 201
    assert client.post('/api/v1/auth/register', json=body).status_code == 409
    assert client.post('/api/v1/auth/register', json={
        'username': 'Alice', 'password': PASSWORD,
    }).status_code == 422
    assert client.post('/api/v1/auth/register', json={
        'username': 'bob', 'password': 'short',
    }).status_code == 422
    assert client.post('/api/v1/auth/register', json={
        'username': 'charlie', 'password': PASSWORD,
    }, headers={'Origin': 'https://attacker.example'}).status_code == 403
    assert client.post('/api/v1/auth/register', json={
        'username': 'david', 'password': PASSWORD,
    }, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    with SessionLocal() as db:
        assert [user.username for user in db.scalars(select(User).order_by(User.id))] == [
            'owner', 'alice',
        ]


def test_registration_rolls_back_user_if_session_creation_fails(client, monkeypatch):
    from app.infrastructure.register_user import SqlAlchemyRegistration

    clear_login_rate('registration:testclient')
    def fail_session(_self, _user_id):
        raise RuntimeError('session storage failed')

    monkeypatch.setattr(SqlAlchemyRegistration, 'create_session', fail_session)
    with TestClient(app, raise_server_exceptions=False) as failing_client:
        result = failing_client.post('/api/v1/auth/register', json={
            'username': 'alice', 'password': PASSWORD,
        })
        assert result.status_code == 500
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.username == 'alice')) is None


def test_registration_waits_for_owner_setup(client):
    clear_login_rate('registration:testclient')
    with SessionLocal() as db:
        db.execute(delete(AppSettings))
        db.execute(delete(User))
        db.commit()
    response = client.post('/api/v1/auth/register', json={
        'username': 'alice', 'password': PASSWORD,
    })
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.username == 'alice')) is None


def test_local_owner_setup_can_recover_an_installation_with_only_regular_users(db, monkeypatch):
    from app import cli

    db.execute(delete(AppSettings))
    db.execute(delete(User))
    db.add(User(username='alice', password_hash='previous-hash', is_admin=False))
    db.commit()
    monkeypatch.setattr(cli, 'password_twice', lambda: PASSWORD)
    cli.init_admin('owner')
    assert db.scalar(select(User).where(User.username == 'owner')).is_admin is True
