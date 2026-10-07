"""Section 3 inspiration: quick check, daily quick quiz, question flags.

Each feature ships with a route-level proof: what the student sees, what the
admin receives, and what nobody else may touch.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _anonymous_cookie_jar(client: TestClient) -> Iterator[None]:
    """Leave the shared client jar exactly as anonymous as we found it.

    `register`/`login` answer with an `mors_access` cookie on the session-scoped
    client that every file shares — a leaked cookie would authenticate later
    "requires auth" assertions (they read the jar, not a header).
    """
    yield
    client.cookies.clear()


def _register(client, prefix: str) -> dict[str, str]:
    email = f"{prefix}{uuid.uuid4().hex[:8]}@mors.ai"
    body = client.post(
        "/api/auth/register",
        json={"full_name": "طالب اختبار", "email": email, "password": "Pytest1234!"},
    )
    assert body.status_code == 200, body.text
    return {"Authorization": f"Bearer {body.json()['tokens']['access_token']}"}


def test_quick_check_is_one_question_with_hidden_answers(client, demo_headers, first_lesson):
    quiz = client.post(
        "/api/quiz/generate",
        json={"lesson_id": first_lesson, "count": 1, "kind": "practice", "types": ["mcq"]},
        headers=demo_headers,
    )
    assert quiz.status_code == 200, quiz.text
    body = quiz.json()
    assert body["question_count"] == 1
    question = body["questions"][0]
    assert question["prompt"] and len(question["options"]) >= 2
    # answers stay server-side until the student commits to an option
    assert all("correct" not in option for option in question["options"])

    started = client.post(f"/api/quiz/{body['id']}/start", headers=demo_headers).json()
    answered = client.post(
        f"/api/quiz/attempts/{started['attempt_id']}/answer",
        json={"question_id": question["id"], "answer": question["options"][0]["id"]},
        headers=demo_headers,
    )
    assert answered.status_code == 200, answered.text
    result = answered.json()
    assert result["correct"] in (True, False)
    assert result["correct_option"]["text"]
    assert result["explanation"]


def test_quick_check_wrong_answer_names_the_right_option(client, demo_headers, first_lesson):
    quiz = client.post(
        "/api/quiz/generate",
        json={"lesson_id": first_lesson, "count": 1, "kind": "practice"},
        headers=demo_headers,
    ).json()
    question = quiz["questions"][0]
    started = client.post(f"/api/quiz/{quiz['id']}/start", headers=demo_headers).json()

    wrong_option = None
    for option in question["options"]:
        res = client.post(
            f"/api/quiz/attempts/{started['attempt_id']}/answer",
            json={"question_id": question["id"], "answer": option["id"]},
            headers=demo_headers,
        )
        assert res.status_code == 200, res.text
        if res.json()["correct"] is False:
            wrong_option = option
            break
    assert wrong_option is not None, "an MCQ must carry at least one wrong option"

    client.post(f"/api/quiz/attempts/{started['attempt_id']}/finish", headers=demo_headers)
    report = client.get(
        f"/api/quiz/attempts/{started['attempt_id']}/report", headers=demo_headers
    ).json()
    assert report["mistakes"], report
    mistake = report["mistakes"][0]
    assert mistake["question_id"] == question["id"]
    # readable wording, not an internal option id
    assert mistake["given"] == wrong_option["text"]


def test_daily_quiz_is_one_per_day_and_reports_completion(client, demo_headers):
    before = client.get("/api/quiz/daily", headers=demo_headers)
    assert before.status_code == 200, before.text
    assert before.json()["generated"] is False
    assert before.json()["completed"] is False

    created = client.post("/api/quiz/daily", headers=demo_headers)
    assert created.status_code == 200, created.text
    quiz = created.json()
    assert quiz["kind"] == "daily"
    assert quiz["question_count"] == 3
    assert len(quiz["questions"]) == 3

    reused = client.post("/api/quiz/daily", headers=demo_headers).json()
    assert reused["id"] == quiz["id"]
    assert reused["reused"] is True

    started = client.post(f"/api/quiz/{quiz['id']}/start", headers=demo_headers).json()
    for question in quiz["questions"]:
        client.post(
            f"/api/quiz/attempts/{started['attempt_id']}/answer",
            json={"question_id": question["id"], "answer": question["options"][0]["id"]},
            headers=demo_headers,
        )
    client.post(f"/api/quiz/attempts/{started['attempt_id']}/finish", headers=demo_headers)

    after = client.get("/api/quiz/daily", headers=demo_headers).json()
    assert after["completed"] is True
    assert after["accuracy"] is not None
    assert after["quiz_id"] == quiz["id"]


def test_question_flag_reaches_the_admin_inbox(client, demo_headers, admin_headers, first_lesson):
    quiz = client.post(
        "/api/quiz/generate",
        json={"lesson_id": first_lesson, "count": 1, "kind": "practice"},
        headers=demo_headers,
    ).json()
    question_id = quiz["questions"][0]["id"]

    flagged = client.post(
        f"/api/quiz/questions/{question_id}/flag",
        json={"kind": "unclear", "detail": "الصياغة مكررة"},
        headers=demo_headers,
    )
    assert flagged.status_code == 200, flagged.text
    flag_id = flagged.json()["flag_id"]

    # the inbox is admin-only — a student gets 403 on the same path
    assert client.get("/api/admin/question-flags", headers=demo_headers).status_code == 403

    listing = client.get("/api/admin/question-flags", headers=admin_headers).json()
    assert any(f["id"] == flag_id for f in listing["flags"]), listing
    row = next(f for f in listing["flags"] if f["id"] == flag_id)
    assert row["kind"] == "unclear"
    assert row["detail"] == "الصياغة مكررة"
    assert row["question"]["prompt"]

    resolved = client.post(f"/api/admin/question-flags/{flag_id}/resolve", headers=admin_headers)
    assert resolved.status_code == 200, resolved.text
    open_ids = [
        f["id"]
        for f in client.get(
            "/api/admin/question-flags", params={"status": "open"}, headers=admin_headers
        ).json()["flags"]
    ]
    assert flag_id not in open_ids


def test_flag_rejects_unknown_and_foreign_questions(client, demo_headers):
    missing = client.post(
        "/api/quiz/questions/nope/flag", json={"kind": "other"}, headers=demo_headers
    )
    assert missing.status_code == 404

    other = _register(client, "foreign")
    quiz = client.post(
        "/api/quiz/generate", json={"count": 1, "kind": "practice"}, headers=other
    ).json()
    foreign = client.post(
        f"/api/quiz/questions/{quiz['questions'][0]['id']}/flag",
        json={"kind": "other"},
        headers=demo_headers,
    )
    assert foreign.status_code == 404


def test_start_attempt_is_scoped_to_the_owner(client, demo_headers):
    quiz = client.post(
        "/api/quiz/generate", json={"count": 1, "kind": "practice"}, headers=demo_headers
    ).json()
    other = _register(client, "noscope")
    stolen = client.post(f"/api/quiz/{quiz['id']}/start", headers=other)
    assert stolen.status_code == 404


def test_invalid_flag_kind_is_rejected(client, demo_headers, first_lesson):
    quiz = client.post(
        "/api/quiz/generate",
        json={"lesson_id": first_lesson, "count": 1, "kind": "practice"},
        headers=demo_headers,
    ).json()
    bad = client.post(
        f"/api/quiz/questions/{quiz['questions'][0]['id']}/flag",
        json={"kind": "not_a_kind"},
        headers=demo_headers,
    )
    assert bad.status_code == 422
