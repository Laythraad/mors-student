"""Shared pytest fixtures.

Environment is configured *before* the application is imported so that
`app.config.settings` picks up an isolated database and the mock AI provider.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_DB = Path(tempfile.gettempdir()) / "mors_pytest.db"
for _suffix in ("", "-wal", "-shm"):
    _path = _DB.with_name(_DB.name + _suffix)
    if _path.exists():
        _path.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_DB.as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["DEMO_DATA"] = "true"
os.environ["AI_PROVIDER"] = "mock"
# the suite generates many quizzes/exams in a single minute — production limits
# would otherwise 429 the later tests
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("AI_RATE_LIMIT_PER_MINUTE", "100000")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

DEMO_EMAIL = "demo@mors.ai"
DEMO_PASSWORD = "DemoPass123!"
ADMIN_EMAIL = "admin@mors.ai"


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
    test_client.cookies.clear()


@pytest.fixture(scope="session")
def demo_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"identifier": DEMO_EMAIL, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.text
    token = response.json()["tokens"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"identifier": ADMIN_EMAIL, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.text
    token = response.json()["tokens"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def student(client: TestClient) -> dict[str, str]:
    """A freshly registered student (onboarding not finished)."""
    suffix = str(abs(hash("pytest-student")) % 10**8)
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "طالب اختبار",
            "email": f"pytest{suffix}@mors.ai",
            "password": "Pytest1234!",
        },
    )
    assert response.status_code == 200, response.text
    token = response.json()["tokens"]["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "email": f"pytest{suffix}@mors.ai",
        "profile_id": response.json()["welcome"]["profile_id"],
    }


@pytest.fixture(scope="session")
def first_lesson(client: TestClient) -> str:
    """The first lesson of the first seeded subject."""
    response = client.get("/api/curriculum/subjects")
    subjects = response.json()["subjects"]
    assert subjects, "seeded curriculum missing"
    tree = client.get(f"/api/curriculum/subjects/{subjects[0]['id']}/tree").json()
    for chapter in tree.get("chapters", []):
        for unit in chapter.get("units", []):
            if unit.get("lessons"):
                return unit["lessons"][0]["id"]
    raise AssertionError("no lessons in seeded subject")


__all__ = ["client", "demo_headers", "admin_headers", "student", "first_lesson"]
