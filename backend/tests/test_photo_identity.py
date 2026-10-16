"""Central identity checks used before authenticated Photo mutations."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


IDENTITY = "/api/v1/superapp/apps/photo/identity"
ORIGIN = {"Origin": "http://testserver"}


def test_photo_post_identity_requires_session(client):
    response = client.post(IDENTITY, headers={**ORIGIN, "X-CSRF-Token": "untrusted"})
    assert response.status_code == 401


def test_photo_post_identity_verifies_session_and_only_returns_identity(client, auth):
    # The upstream integration needs the session cookie and header, not the
    # browser's readable CSRF cookie or a client-provided user identifier.
    session = client.cookies.get("budget_session")
    client.cookies.clear()
    client.cookies.set("budget_session", session)
    response = client.post(IDENTITY, headers={**ORIGIN, **auth}, json={"id": 999})
    assert response.status_code == 200
    assert response.json() == {"id": 1, "username": "owner"}
    assert response.headers["cache-control"] == "no-store"
    assert client.get(IDENTITY).json() == response.json()


@pytest.mark.parametrize("token", [None, "invalid-csrf-token"])
def test_photo_post_identity_rejects_missing_or_invalid_csrf(client, auth, token):
    headers = dict(ORIGIN)
    if token is not None:
        headers["X-CSRF-Token"] = token
    response = client.post(IDENTITY, headers=headers)
    assert response.status_code == 403
    assert response.json()["message"] == "Invalid CSRF token"


def test_photo_post_identity_rejects_foreign_origin_even_with_forwarded_headers(client, auth):
    response = client.post(IDENTITY, headers={
        **auth,
        "Origin": "https://foreign.example",
        "X-Forwarded-Host": "foreign.example",
        "X-Forwarded-Proto": "https",
    })
    assert response.status_code == 403
    assert response.json()["message"] == "Origin not allowed"


def test_photo_post_identity_csrf_is_bound_to_current_users_session(client, auth):
    with TestClient(app) as reader:
        registration = reader.post("/api/v1/auth/register", json={
            "username": "photo_reader", "password": "a secure separate test password",
        })
        assert registration.status_code == 201
        reader_id = reader.get("/api/v1/auth/me").json()["id"]
        assert reader.post(IDENTITY, headers={**ORIGIN, **auth}).status_code == 403
        response = reader.post(IDENTITY, headers={
            **ORIGIN, "X-CSRF-Token": reader.cookies.get("csrf_token"),
        })
        assert response.status_code == 200
        assert response.json() == {"id": reader_id, "username": "photo_reader"}


def test_photo_post_identity_respects_global_and_personal_access(client, auth):
    assert client.patch("/api/v1/superapp/admin/apps/photo", headers=auth, json={
        "enabled": False, "version": 0,
    }).status_code == 200
    # The owner follows the same availability rule as ordinary users.
    assert client.post(IDENTITY, headers={**ORIGIN, **auth}).status_code == 403
    with TestClient(app) as reader:
        registration = reader.post("/api/v1/auth/register", json={
            "username": "photo_reader", "password": "a secure separate test password",
        })
        assert registration.status_code == 201
        reader_id = reader.get("/api/v1/auth/me").json()["id"]
        headers = {**ORIGIN, "X-CSRF-Token": reader.cookies.get("csrf_token")}
        assert reader.post(IDENTITY, headers=headers).status_code == 403
        assert client.patch(
            f"/api/v1/superapp/admin/users/{reader_id}/apps/photo",
            headers=auth, json={"enabled": True, "version": 0},
        ).status_code == 200
        assert reader.post(IDENTITY, headers=headers).status_code == 200
        assert client.post(IDENTITY, headers={**ORIGIN, **auth}).status_code == 403


def test_photo_post_identity_rejects_revoked_session(client, auth):
    session = client.cookies.get("budget_session")
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 200
    client.cookies.set("budget_session", session)
    assert client.post(IDENTITY, headers={**ORIGIN, **auth}).status_code == 401
