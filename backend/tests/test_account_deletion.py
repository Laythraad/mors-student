"""حذف الحساب والبيانات (§128 — الخصوصية)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.db import Note, SessionLocal, StudentProfile, User


def _register(client: TestClient, suffix: str) -> dict[str, str]:
    email = f"del{suffix}@mors.ai"
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "طالب حذف",
            "email": email,
            "password": "Delete1234!",
        },
    )
    assert response.status_code == 200, response.text
    token = response.json()["tokens"]["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "email": email,
        "profile_id": response.json()["welcome"]["profile_id"],
    }


def test_delete_wrong_password_keeps_account(
    client: TestClient,
) -> None:
    headers = _register(client, str(int(time.time() * 1000) % 10**8))

    wrong = client.request(
        "DELETE", "/api/auth/account", headers=headers, json={"password": "wrong-pass"}
    )
    assert wrong.status_code == 401, wrong.text

    still = client.get("/api/auth/me", headers=headers)
    assert still.status_code == 200, still.text


def test_delete_purges_account_and_data(client: TestClient) -> None:
    headers = _register(client, str((int(time.time() * 1000) + 7) % 10**8))
    email = headers["email"]

    note = client.post(
        "/api/library/notes",
        headers=headers,
        json={"title": "ملاحظة قبل الحذف", "body": "ستُحذف مع الحساب."},
    )
    assert note.status_code == 200, note.text

    profile_id = headers["profile_id"]
    db = SessionLocal()
    try:
        assert db.query(Note).filter(Note.student_id == profile_id).count() == 1
    finally:
        db.close()

    deleted = client.request(
        "DELETE", "/api/auth/account", headers=headers, json={"password": "Delete1234!"}
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert deleted.json()["rows"] >= 3  # user + profile + settings + note…

    login = client.post(
        "/api/auth/login", json={"identifier": email, "password": "Delete1234!"}
    )
    assert login.status_code == 401, login.text
    assert client.get("/api/auth/me", headers=headers).status_code == 401

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == email).count() == 0
        assert db.query(StudentProfile).filter(StudentProfile.id == profile_id).count() == 0
        assert db.query(Note).filter(Note.student_id == profile_id).count() == 0
    finally:
        db.close()


def test_sealed_platform_accounts_cannot_be_deleted(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    blocked = client.request(
        "DELETE", "/api/auth/account", headers=admin_headers, json={"password": "DemoPass123!"}
    )
    assert blocked.status_code == 422, blocked.text
    assert "لا يمكن" in blocked.json()["error"]["message"]
