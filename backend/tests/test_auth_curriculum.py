"""Auth, onboarding and curriculum endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_stages_branches_subjects(client: TestClient) -> None:
    stages = client.get("/api/curriculum/stages").json()["stages"]
    assert stages and any("الرابع" in s["name_ar"] for s in stages)

    grade12 = next(s for s in stages if "الرابع" in s["name_ar"])
    branches = client.get("/api/curriculum/branches", params={"stage_id": grade12["id"]}).json()["branches"]
    assert branches and any(b["code"] == "science" for b in branches)

    science = next(b for b in branches if b["code"] == "science")
    subjects = client.get("/api/curriculum/subjects", params={"branch_id": science["id"]}).json()["subjects"]
    assert len(subjects) >= 5
    assert all(s["name_ar"] and s["color"] for s in subjects)


def test_subject_tree_returns_lessons(client: TestClient) -> None:
    subjects = client.get("/api/curriculum/subjects").json()["subjects"]
    tree = client.get(f"/api/curriculum/subjects/{subjects[0]['id']}/tree").json()
    lessons = [l for c in tree["chapters"] for u in c["units"] for l in u["lessons"]]
    assert lessons and all(l["summary"] for l in lessons)


def test_lesson_and_search(client: TestClient) -> None:
    subjects = client.get("/api/curriculum/subjects").json()["subjects"]
    tree = client.get(f"/api/curriculum/subjects/{subjects[0]['id']}/tree").json()
    lesson_id = tree["chapters"][0]["units"][0]["lessons"][0]["id"]

    lesson = client.get(f"/api/curriculum/lessons/{lesson_id}").json()
    assert lesson["objectives"] and lesson["keywords"]

    results = client.get("/api/curriculum/search", params={"q": lesson["title"][:6]}).json()["results"]
    assert results

    missing = client.get("/api/curriculum/lessons/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_register_login_me(client: TestClient, student: dict[str, str]) -> None:
    me = client.get("/api/auth/me", headers=student)
    assert me.status_code == 200
    assert me.json()["user"]["email"] == student["email"]

    login = client.post(
        "/api/auth/login",
        json={"identifier": student["email"], "password": "Pytest1234!"},
    )
    assert login.status_code == 200
    assert login.json()["tokens"]["access_token"].count(".") == 2

    weak = client.post(
        "/api/auth/register",
        json={"full_name": "x", "email": "weak@mors.ai", "password": "abc"},
    )
    assert weak.status_code == 422


def test_profile_and_subjects(client: TestClient, student: dict[str, str]) -> None:
    stages = client.get("/api/curriculum/stages").json()["stages"]
    grade12 = next(s for s in stages if "الرابع" in s["name_ar"])
    branches = client.get("/api/curriculum/branches", params={"stage_id": grade12["id"]}).json()["branches"]
    science = next(b for b in branches if b["code"] == "science")
    subjects = client.get("/api/curriculum/subjects", params={"branch_id": science["id"]}).json()["subjects"]

    patch = client.patch(
        "/api/auth/profile",
        headers=student,
        json={"stage_id": grade12["id"], "branch_id": science["id"], "daily_study_minutes": 75},
    )
    assert patch.status_code == 200

    put = client.put(
        "/api/auth/subjects",
        headers=student,
        json={"subject_ids": [s["id"] for s in subjects[:3]]},
    )
    assert put.status_code == 200
    assert len(put.json()["subject_ids"]) == 3

    mine = client.get("/api/curriculum/mine", headers=student).json()["subjects"]
    assert len(mine) == 3

    steps = client.get("/api/onboarding/steps", headers=student).json()
    assert len(steps["steps"]) == 7
    assert 0 <= steps["progress"] <= 100

    recommend = client.get("/api/onboarding/recommend", headers=student).json()
    assert recommend["subjects"]


def test_auth_required_and_role_gate(client: TestClient, demo_headers: dict[str, str]) -> None:
    client.cookies.clear()
    assert client.get("/api/progress/home").status_code == 401

    forbidden = client.get("/api/admin/stats", headers=demo_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


def test_password_policy(client: TestClient) -> None:
    policy = client.get("/api/auth/password-ok").json()
    assert policy["min_length"] == 8
    assert policy["needs_digit"] and policy["needs_letter"]


def test_settings_roundtrip(client: TestClient, student: dict[str, str]) -> None:
    got = client.get("/api/auth/settings", headers=student)
    assert got.status_code == 200
    settings = got.json()["settings"]
    assert settings["theme"] == "light"
    assert settings["font_scale"] == 1.0
    assert settings["mors_size"] == "normal"
    assert settings["primary_color"] == "#2f8ff7"

    patched = client.patch(
        "/api/auth/settings",
        headers=student,
        json={
            "theme": "dark",
            "font_scale": 1.25,
            "reduce_motion": True,
            "mors_size": "large",
            "primary_color": "#7c5cff",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["settings"]["theme"] == "dark"

    again = client.get("/api/auth/settings", headers=student).json()["settings"]
    assert again["theme"] == "dark"
    assert again["font_scale"] == 1.25
    assert again["reduce_motion"] is True
    assert again["mors_size"] == "large"
    assert again["primary_color"] == "#7c5cff"

    rejected = client.patch(
        "/api/auth/settings", headers=student, json={"theme": "neon"}
    )
    assert rejected.status_code == 422
