from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DIR = Path(tempfile.mkdtemp(prefix="budget-tests-"))
os.environ["DATABASE_PATH"] = str(TEST_DIR / "test.sqlite3")
os.environ["BACKUP_DIR"] = str(TEST_DIR / "backups")
os.environ["REQUIRE_SAFE_SQLITE"] = "0"

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Account, AppSettings, User  # noqa: E402
from app.security import hash_password  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(AppSettings(id=1, accounting_start_date=date(2026, 1, 1)))
        db.add(User(username="owner", password_hash=hash_password("correct horse battery staple")))
        db.commit()
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


@pytest.fixture
def auth(client):
    response = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "correct horse battery staple"}
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture
def account(db):
    value = Account(
        name="Основной",
        type="bank",
        initial_balance_minor=200_000_00,
        initial_balance_date=date(2026, 1, 1),
    )
    db.add(value)
    db.commit()
    db.refresh(value)
    return value
