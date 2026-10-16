"""The photo sharing recipient boundary is exact, authenticated and minimal."""

from fastapi.testclient import TestClient

from app.main import app
from app.models import User


RESOLVE = "/api/v1/superapp/apps/photo/users/resolve"


def test_recipient_requires_session(client):
    assert client.get(RESOLVE, params={"username": "owner"}).status_code == 401


def test_ordinary_user_can_resolve_exact_login_without_private_fields(client):
    with TestClient(app) as reader:
        registered = reader.post("/api/v1/auth/register", json={
            "username": "photo_reader", "password": "a secure separate test password",
        })
        assert registered.status_code == 201
        response = reader.get(RESOLVE, params={"username": "owner"})
        assert response.status_code == 200
        assert response.json() == {"id": 1, "username": "owner"}
        assert response.headers["cache-control"] == "no-store"
        for username in ("own", "own%", "owner*", "missing_user"):
            assert reader.get(RESOLVE, params={"username": username}).status_code == 404
        assert reader.get(RESOLVE).status_code == 422


def test_inactive_and_missing_recipient_are_indistinguishable(client, auth, db):
    db.add(User(username="inactive_user", password_hash="not-used", active=False))
    db.commit()
    missing = client.get(RESOLVE, params={"username": "missing_user"})
    inactive = client.get(RESOLVE, params={"username": "inactive_user"})
    assert missing.status_code == inactive.status_code == 404
    assert missing.json()["message"] == inactive.json()["message"]


def test_recipient_resolution_respects_application_availability(client, auth):
    assert client.patch("/api/v1/superapp/admin/apps/photo", headers=auth, json={
        "enabled": False, "version": 0,
    }).status_code == 200
    assert client.get(RESOLVE, params={"username": "owner"}).status_code == 403


def test_recipient_resolution_rejects_revoked_session(client, auth):
    session = client.cookies.get("budget_session")
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 200
    client.cookies.set("budget_session", session)
    assert client.get(RESOLVE, params={"username": "owner"}).status_code == 401
