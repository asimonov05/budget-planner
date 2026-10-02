from fastapi.testclient import TestClient

from app.main import app


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _create_user(client: TestClient, headers: dict[str, str], username: str) -> int:
    response = client.post(
        "/api/v1/users", headers=headers,
        json={"username": username, "password": "correct horse battery staple"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_inbox_is_private_and_read_receipts_are_idempotent(client, auth):
    alice_id = _create_user(client, auth, "alice")
    assert client.post("/api/v1/notifications/send", json={"title": "Test", "body": "Hello"}).status_code == 403
    response = client.post(
        "/api/v1/notifications/send", headers=auth,
        json={"title": "For Alice", "body": "Only you", "recipient_user_id": alice_id},
    )
    assert response.status_code == 201
    assert response.json() == {"delivered": 1}
    assert client.get("/api/v1/notifications").json()["items"] == []

    with TestClient(app) as alice:
        alice_auth = _login(alice, "alice", "correct horse battery staple")
        inbox = alice.get("/api/v1/notifications").json()
        assert inbox["total"] == inbox["unread"] == 1
        item = inbox["items"][0]
        assert item["title"] == "For Alice"
        assert item["body"] == "Only you"
        assert alice.get("/api/v1/notifications/unread-count").json() == {"count": 1}
        assert alice.post(f"/api/v1/notifications/{item['id']}/read").status_code == 403
        first = alice.post(f"/api/v1/notifications/{item['id']}/read", headers=alice_auth)
        second = alice.post(f"/api/v1/notifications/{item['id']}/read", headers=alice_auth)
        assert first.status_code == second.status_code == 200
        assert first.json()["read_at"] == second.json()["read_at"]
        assert alice.get("/api/v1/notifications/unread-count").json() == {"count": 0}
        assert alice.post("/api/v1/notifications/send", headers=alice_auth, json={
            "title": "No", "body": "Permission",
        }).status_code == 403

    assert client.post(f"/api/v1/notifications/{item['id']}/read", headers=auth).status_code == 404


def test_broadcast_targets_active_users_and_validates_message(client, auth):
    alice_id = _create_user(client, auth, "alice")
    bob_id = _create_user(client, auth, "bob")
    assert client.patch(f"/api/v1/users/{bob_id}", headers=auth, json={"active": False}).status_code == 200
    assert client.post("/api/v1/notifications/send", headers=auth, json={
        "title": "   ", "body": "body",
    }).status_code == 422
    assert client.post("/api/v1/notifications/send", headers=auth, json={
        "title": "Hello", "body": "body", "recipient_user_id": bob_id,
    }).status_code == 404
    response = client.post("/api/v1/notifications/send", headers=auth, json={
        "title": "Everyone", "body": "Latest news",
    })
    assert response.status_code == 201
    assert response.json() == {"delivered": 2}
    assert client.get("/api/v1/notifications").json()["unread"] == 1
    with TestClient(app) as alice:
        _login(alice, "alice", "correct horse battery staple")
        assert alice.get("/api/v1/notifications").json()["total"] == 1
    assert alice_id != bob_id


def test_release_notes_have_private_drafts_and_publish_once(client, auth):
    _create_user(client, auth, "alice")
    body = {"release_version": "1.4.0", "title": "Changes", "body": "New reports"}
    assert client.post("/api/v1/release-notes", json=body).status_code == 403
    created = client.post("/api/v1/release-notes", headers=auth, json=body)
    assert created.status_code == 201
    note_id = created.json()["id"]
    assert created.json()["status"] == "draft"
    assert client.get("/api/v1/release-notes").json() == []

    with TestClient(app) as alice:
        alice_auth = _login(alice, "alice", "correct horse battery staple")
        assert alice.get("/api/v1/release-notes").json() == []
        assert alice.get("/api/v1/release-notes/manage").status_code == 403
        assert alice.post(f"/api/v1/release-notes/{note_id}/publish", headers=alice_auth).status_code == 403

        edited = client.patch(
            f"/api/v1/release-notes/{note_id}", headers=auth,
            json={**body, "body": "New reports\nFaster search"},
        )
        assert edited.status_code == 200
        assert edited.json()["body"] == "New reports\nFaster search"
        published = client.post(f"/api/v1/release-notes/{note_id}/publish", headers=auth)
        assert published.status_code == 200
        assert published.json()["delivered"] == 2
        assert published.json()["release_note"]["status"] == "published"
        assert client.post(f"/api/v1/release-notes/{note_id}/publish", headers=auth).status_code == 409
        assert client.patch(f"/api/v1/release-notes/{note_id}", headers=auth, json=body).status_code == 409
        assert client.post("/api/v1/release-notes", headers=auth, json=body).status_code == 409

        public = alice.get("/api/v1/release-notes").json()
        assert len(public) == 1 and public[0]["body"] == "New reports\nFaster search"
        inbox = alice.get("/api/v1/notifications").json()
        assert inbox["total"] == 1
        assert inbox["items"][0]["kind"] == "release"
        assert inbox["items"][0]["release_note_id"] == note_id
