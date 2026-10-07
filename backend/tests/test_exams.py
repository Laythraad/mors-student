"""Exam sessions: bank validation, generation, timed simulation, analysis, readiness."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient


def _generate_and_start(client: TestClient, headers: dict[str, str]) -> dict:
    subjects = client.get("/api/exams", headers=headers).json()["subjects"]
    subject_id = subjects[0]["id"] if subjects else None
    generated = client.post(
        "/api/exams/generate",
        json={"subject_id": subject_id, "count": 8, "duration_minutes": 15, "kind": "mock"},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    quiz = generated.json()
    assert 0 < len(quiz["questions"]) <= 8
    assert quiz["time_limit_seconds"] == 900
    assert quiz["blueprint"]["dropped"] >= 0

    started = client.post(
        "/api/exams/start", json={"quiz_id": quiz["id"], "mode": "mock"}, headers=headers
    )
    assert started.status_code == 200, started.text
    session = started.json()
    assert session["exam_attempt_id"] and session["attempt_id"]
    assert session["status"] == "in_progress"
    assert 0 < session["time_left_seconds"] <= 900
    assert len(session["questions"]) == len(quiz["questions"])
    assert session["answered"] == {}
    return session


def test_exams_require_auth(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/exams").status_code == 401
    assert client.post("/api/exams/generate", json={}).status_code == 401


def test_overview_shape(client: TestClient, demo_headers: dict[str, str]) -> None:
    data = client.get("/api/exams", headers=demo_headers).json()
    for key in ("subjects", "upcoming", "recent", "mistakes_count", "readiness_overall", "bank"):
        assert key in data, key
    assert data["bank"]["total"] >= 0
    readiness = data["readiness_overall"]
    assert len(readiness["factors"]) == 6
    assert readiness["band"] in {"no_data", "weak", "not_ready", "ready_with_work", "ready"}
    if data["subjects"]:
        assert data["subjects"][0]["readiness"]["subject_id"] == data["subjects"][0]["id"]


def test_generate_start_and_answer(client: TestClient, demo_headers: dict[str, str]) -> None:
    session = _generate_and_start(client, demo_headers)
    question = session["questions"][0]

    marked = client.post(
        f"/api/exams/attempts/{session['exam_attempt_id']}/mark",
        json={"question_id": question["id"]},
        headers=demo_headers,
    )
    assert marked.status_code == 200 and marked.json()["is_marked"] is True
    unmarked = client.post(
        f"/api/exams/attempts/{session['exam_attempt_id']}/mark",
        json={"question_id": question["id"]},
        headers=demo_headers,
    )
    assert unmarked.json()["is_marked"] is False

    answer = client.post(
        f"/api/exams/attempts/{session['exam_attempt_id']}/answer",
        json={"question_id": question["id"], "answer": question["options"][0]["id"]},
        headers=demo_headers,
    )
    assert answer.status_code == 200, answer.text
    payload = answer.json()
    assert payload["ok"] is True and "correct" not in payload  # hidden until submission
    assert payload["answered_count"] == 1

    reloaded = client.get(
        f"/api/exams/attempts/{session['exam_attempt_id']}", headers=demo_headers
    ).json()
    assert reloaded["answered_count"] == 1
    assert question["id"] in reloaded["answered"]


def test_submit_produces_analysis_and_mistakes(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    before = client.get("/api/exams/mistakes", headers=demo_headers).json()["total"]
    session = _generate_and_start(client, demo_headers)
    first, second = session["questions"][0], session["questions"][1]

    # wrong answer on purpose (a random option id), second one stays skipped
    wrong_option = next(
        o for o in first["options"] if not o.get("correct")
    ) if any(o.get("correct") for o in first["options"]) else first["options"][-1]
    client.post(
        f"/api/exams/attempts/{session['exam_attempt_id']}/answer",
        json={"question_id": first["id"], "answer": wrong_option["id"]},
        headers=demo_headers,
    )
    client.post(
        f"/api/exams/attempts/{session['exam_attempt_id']}/answer",
        json={"question_id": second["id"], "answer": "لا يوجد"},
        headers=demo_headers,
    )

    report = client.post(
        f"/api/exams/attempts/{session['exam_attempt_id']}/submit", headers=demo_headers
    )
    assert report.status_code == 200, report.text
    analysis = report.json()
    assert analysis["status"] == "submitted"
    assert 0 <= analysis["accuracy"] <= 100
    assert analysis["time_seconds"] >= 0
    assert set(analysis["by_difficulty"]) >= {"1", "2", "3"}
    assert sum(bucket["total"] for bucket in analysis["by_difficulty"].values()) == len(
        session["questions"]
    )
    assert analysis["mistakes"] and analysis["mistakes"][0]["prompt"]
    assert "factors" in analysis["readiness"]

    after = client.get("/api/exams/mistakes", headers=demo_headers).json()
    assert after["total"] >= before + 1
    mistake = after["items"][0]
    resolved = client.post(f"/api/exams/mistakes/{mistake['id']}/resolve", headers=demo_headers)
    assert resolved.json()["is_active"] is False

    # submitting twice returns the stored analysis
    again = client.post(
        f"/api/exams/attempts/{session['exam_attempt_id']}/submit", headers=demo_headers
    )
    assert again.json()["exam_attempt_id"] == analysis["exam_attempt_id"]

    # a submitted session rejects new answers
    rejected = client.post(
        f"/api/exams/attempts/{session['exam_attempt_id']}/answer",
        json={"question_id": first["id"], "answer": "x"},
        headers=demo_headers,
    )
    assert rejected.status_code == 422


def test_expired_timer_finalises_server_side(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    from app.db import ExamAttempt, SessionLocal, utcnow

    session = _generate_and_start(client, demo_headers)
    db = SessionLocal()
    try:
        row = db.get(ExamAttempt, session["exam_attempt_id"])
        row.started_at = utcnow() - timedelta(seconds=900 + 5)
        db.commit()
    finally:
        db.close()

    payload = client.get(
        f"/api/exams/attempts/{session['exam_attempt_id']}", headers=demo_headers
    ).json()
    assert payload["status"] in {"submitted", "expired"}
    assert payload["overtime"] is True
    assert payload["report"]["accuracy"] >= 0
    assert payload["time_left_seconds"] == 0

    rejected = client.post(
        f"/api/exams/attempts/{session['exam_attempt_id']}/answer",
        json={"question_id": session["questions"][0]["id"], "answer": "x"},
        headers=demo_headers,
    )
    assert rejected.status_code == 422


def test_readiness_endpoint(client: TestClient, demo_headers: dict[str, str]) -> None:
    subjects = client.get("/api/exams", headers=demo_headers).json()["subjects"]
    data = client.get("/api/exams/readiness", headers=demo_headers).json()
    assert data["subject_id"] is None and len(data["factors"]) == 6
    assert isinstance(data["next_steps"], list)
    if subjects:
        scoped = client.get(
            "/api/exams/readiness",
            params={"subject_id": subjects[0]["id"]},
            headers=demo_headers,
        ).json()
        assert scoped["subject_id"] == subjects[0]["id"]


def test_bank_requires_manager_role(
    client: TestClient, demo_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    assert client.get("/api/exams/bank", headers=demo_headers).status_code == 403
    assert (
        client.post("/api/exams/bank", json={"prompt": "x"}, headers=demo_headers).status_code
        == 403
    )

    created = client.post(
        "/api/exams/bank",
        json={
            "prompt": "ما ناتج جمع ٧ و ٥ في الحساب العددي؟",
            "options": ["12", "11", "13", "10"],
            "answer_index": 0,
            "explanation": "٧ + ٥ = ١٢.",
            "difficulty": 1,
            "topic": "الجمع",
            "subject_id": None,
            "source_kind": "ai",
        },
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "validated" and body["dedup_hash"]

    duplicate = client.post(
        "/api/exams/bank",
        json={
            "prompt": "ما ناتج جمع ٧ و ٥ في الحساب العددي؟",
            "options": ["12", "11"],
            "answer_index": 0,
        },
        headers=admin_headers,
    )
    assert duplicate.status_code == 422

    invalid = client.post(
        "/api/exams/bank",
        json={"prompt": "قصير", "options": ["أ"], "answer_index": 5},
        headers=admin_headers,
    )
    assert invalid.status_code == 422

    validated = client.post(f"/api/exams/bank/{body['id']}/validate", headers=admin_headers)
    assert validated.status_code == 200 and validated.json()["valid"] is True

    listed = client.get("/api/exams/bank", params={"q": "الحساب العددي"}, headers=admin_headers).json()
    assert listed["total"] >= 1 and listed["stats"]["total"] >= 1
    assert all("correct" not in item for item in listed["items"])
