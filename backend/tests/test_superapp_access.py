from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm.exc import StaleDataError

from app.db import SessionLocal
from app.main import app
from app.models import AppAvailability, AuditLog, UserAppAccess


def register(username: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/v1/auth/register", json={
        "username": username, "password": "a secure separate test password",
    })
    assert response.status_code == 201, response.text
    return client


def state(client, app_id="budget"):
    response = client.get("/api/v1/superapp/apps")
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["apps"] if item["id"] == app_id)


def test_catalogue_defaults_and_authorization(client, auth):
    with TestClient(app) as guest:
        assert state(guest)["available"] is True
        assert guest.get("/api/v1/superapp/admin/apps").status_code == 401
        guest.cookies.set("budget_session", "expired-cookie")
        assert state(guest)["enabled"] is True

    with register("reader") as reader:
        assert reader.get("/api/v1/superapp/admin/apps").status_code == 403
        assert reader.get("/api/v1/superapp/admin/users/1/apps").status_code == 403
        assert reader.patch("/api/v1/superapp/admin/apps/budget", json={
            "enabled": False, "version": 0,
        }).status_code == 403
    assert client.patch("/api/v1/superapp/admin/apps/budget", json={
        "enabled": False, "version": 0,
    }).status_code == 403
    assert client.patch("/api/v1/superapp/admin/apps/unknown", headers=auth, json={
        "enabled": False, "version": 0,
    }).status_code == 404
    assert client.patch("/api/v1/superapp/admin/apps/budget", headers=auth, json={
        "enabled": "false", "version": 0,
    }).status_code == 422


def test_global_close_blocks_budget_api_but_keeps_auth_and_admin(client, auth, db):
    assert client.get("/api/v1/accounts").status_code == 200
    response = client.patch("/api/v1/superapp/admin/apps/budget", headers=auth, json={
        "enabled": False, "version": 0,
    })
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 1
    assert state(client)["available"] is False
    # An owner also follows availability rules; a direct URL cannot bypass them.
    for route in ("accounts", "forecast", "currencies", "exports/project"):
        assert client.get(f"/api/v1/{route}").status_code == 403, route
    assert client.post("/api/v1/accounts", headers=auth, json={
        "name": "blocked", "type": "bank", "initial_balance_minor": 0,
        "initial_balance_date": "2026-01-01",
    }).status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get("/api/v1/superapp/admin/apps").status_code == 200
    assert client.get("/api/v1/superapp/apps/photo/identity").status_code == 200
    assert client.patch("/api/v1/superapp/admin/apps/budget", headers=auth, json={
        "enabled": True, "version": 0,
    }).status_code == 409
    assert client.patch("/api/v1/superapp/admin/apps/budget", headers=auth, json={
        "enabled": True, "version": 1,
    }).status_code == 200
    assert client.get("/api/v1/accounts").status_code == 200
    assert db.get(AppAvailability, "budget").version == 2
    changes = db.query(AuditLog).filter_by(entity_type="application_access").all()
    assert len(changes) == 2
    assert all(change.user_id == 1 for change in changes)


def test_user_exceptions_isolate_users_and_reset_to_global(client, auth, db):
    with register("first") as first, register("second") as second:
        first_id = first.get("/api/v1/auth/me").json()["id"]
        second_id = second.get("/api/v1/auth/me").json()["id"]
        path = f"/api/v1/superapp/admin/users/{first_id}/apps/budget"
        result = client.patch(path, headers=auth, json={"enabled": False, "version": 0})
        assert result.status_code == 200, result.text
        assert result.json()["override"] is False
        assert first.get("/api/v1/accounts").status_code == 403
        assert second.get("/api/v1/accounts").status_code == 200
        assert state(first)["available"] is False
        assert state(second)["available"] is True
        assert first.get(f"/api/v1/superapp/admin/users/{second_id}/apps").status_code == 403
        assert client.patch(path, headers=auth, json={
            "enabled": None, "version": 0,
        }).status_code == 409
        assert client.patch(path, headers=auth, json={
            "enabled": None, "version": 1,
        }).status_code == 200
        assert first.get("/api/v1/accounts").status_code == 200
        assert db.get(UserAppAccess, (first_id, "budget")).enabled is None
        assert client.patch("/api/v1/superapp/admin/apps/budget", headers=auth, json={
            "enabled": False, "version": 0,
        }).status_code == 200
        assert first.get("/api/v1/accounts").status_code == 403
        assert client.patch(path, headers=auth, json={
            "enabled": True, "version": 2,
        }).status_code == 200
        assert first.get("/api/v1/accounts").status_code == 200
        assert second.get("/api/v1/accounts").status_code == 403
        assert second.get("/api/v1/auth/me").status_code == 200
        assert client.get("/api/v1/superapp/admin/users/99999/apps").status_code == 404


def test_photo_identity_enforces_permission_independent_of_budget(client, auth):
    with register("photo_reader") as reader:
        user_id = reader.get("/api/v1/auth/me").json()["id"]
        assert reader.get("/api/v1/superapp/apps/photo/identity").json()["id"] == user_id
        assert client.patch("/api/v1/superapp/admin/apps/photo", headers=auth, json={
            "enabled": False, "version": 0,
        }).status_code == 200
        assert reader.get("/api/v1/superapp/apps/photo/identity").status_code == 403
        assert reader.get("/api/v1/accounts").status_code == 200
        assert reader.get("/api/v1/auth/me").status_code == 200
        assert client.patch(f"/api/v1/superapp/admin/users/{user_id}/apps/photo",
                            headers=auth, json={"enabled": True, "version": 0}).status_code == 200
        assert reader.get("/api/v1/superapp/apps/photo/identity").status_code == 200


@pytest.mark.parametrize("model, key, values", [
    (AppAvailability, "budget", {"id": "budget", "enabled": True}),
    (UserAppAccess, (1, "photo"), {"user_id": 1, "app_id": "photo", "enabled": True}),
])
def test_concurrent_access_update_rejects_stale_writer(db, model, key, values):
    db.add(model(**values, version=1))
    db.commit()
    with SessionLocal() as first, SessionLocal() as second:
        first_row, second_row = first.get(model, key), second.get(model, key)
        first_row.enabled, first_row.version = False, 2
        first.commit()
        second_row.enabled, second_row.version = True, 2
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
