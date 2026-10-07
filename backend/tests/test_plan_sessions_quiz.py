"""Planner, study sessions and quiz attempts."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient


def test_plan_generate_and_what_now(client: TestClient, demo_headers: dict[str, str]) -> None:
    plan = client.post("/api/plan/generate", headers=demo_headers, json={"days": 7})
    assert plan.status_code == 200
    payload = plan.json()["plan"]
    assert payload["days"] and 1 <= len(payload["days"]) <= 7

    tasks = [t for day in payload["days"] for t in day.get("tasks", [])]
    assert tasks, "a 7-day plan must contain tasks"
    assert all(t["duration_minutes"] > 0 for t in tasks)

    current = client.get("/api/plan/current", headers=demo_headers).json()
    assert current["plan"] is not None

    what_now = client.get("/api/plan/what-now", headers=demo_headers).json()
    assert "available" in what_now

    listed = client.get("/api/plan/tasks", headers=demo_headers).json()["tasks"]
    assert listed

    calendar = client.get("/api/plan/calendar", headers=demo_headers).json()["events"]
    assert calendar


def test_task_lifecycle(client: TestClient, demo_headers: dict[str, str]) -> None:
    tasks = client.get("/api/plan/tasks", headers=demo_headers).json()["tasks"]
    task = next(t for t in tasks if t["status"] == "pending")
    today = date.today() + timedelta(days=1)

    moved = client.post(
        f"/api/plan/tasks/{task['id']}/move",
        headers=demo_headers,
        json={"date": today.isoformat()},
    )
    assert moved.status_code == 200

    done = client.post(f"/api/plan/tasks/{task['id']}/complete", headers=demo_headers)
    assert done.status_code == 200
    assert done.json()["task"]["status"] == "completed"

    missing = client.post("/api/plan/tasks/unknown/complete", headers=demo_headers)
    assert missing.status_code == 404


def test_exam_countdown_plan(client: TestClient, demo_headers: dict[str, str]) -> None:
    subjects = client.get("/api/curriculum/subjects").json()["subjects"]
    exam_date = (date.today() + timedelta(days=6)).isoformat()
    created = client.post(
        "/api/plan/exams",
        headers=demo_headers,
        json={"title": "امتحان الفيزياء", "exam_date": exam_date, "subject_id": subjects[0]["id"]},
    )
    assert created.status_code == 200
    exam_id = created.json()["exam_id"]

    exams = client.get("/api/plan/exams", headers=demo_headers).json()["exams"]
    assert any(e["id"] == exam_id and e["days_left"] == 6 for e in exams)

    countdown = client.post(f"/api/plan/exam-countdown/{exam_id}", headers=demo_headers)
    assert countdown.status_code == 200
    assert countdown.json()["plan"]["days"]

    past = client.post(
        "/api/plan/exams",
        headers=demo_headers,
        json={"title": "امتحان قديم", "exam_date": "2020-01-01"},
    )
    assert past.status_code == 422


def test_study_session_lifecycle(client: TestClient, demo_headers: dict[str, str], first_lesson: str) -> None:
    started = client.post(
        "/api/study/start",
        headers=demo_headers,
        json={"lesson_id": first_lesson, "goal": "فهم الفرق المشترك"},
    )
    assert started.status_code == 200
    session = started.json()["session"]
    assert session["status"] == "active"
    session_id = session["id"]

    beat = client.post(
        f"/api/study/{session_id}/heartbeat",
        headers=demo_headers,
        json={"elapsed_seconds": 60 * 20},
    )
    assert beat.status_code == 200

    active = client.get("/api/study/active", headers=demo_headers).json()
    assert active["session"]["id"] == session_id
    # §2.2 / scheduling-engine: the client reports, the server decides — a
    # heartbeat claiming 20 minutes one second in must be clamped to real time.
    assert active["session"]["elapsed_seconds"] < 60, active["session"]

    ended = client.post(
        f"/api/study/{session_id}/end",
        headers=demo_headers,
        json={"status": "completed", "feedback": "medium", "understanding": 0.8, "mistakes": 1},
    )
    assert ended.status_code == 200
    body = ended.json()
    assert body["ok"] and body["minutes"] == 0, body
    assert body["mors"]["expression"], "session end must produce a Mors reaction"

    again = client.post(f"/api/study/{session_id}/end", headers=demo_headers, json={})
    assert again.status_code == 404

    suggested = client.get("/api/study/suggested-duration", headers=demo_headers).json()
    assert suggested["recommended_minutes"] > 0

    brk = client.post("/api/study/break", headers=demo_headers)
    assert brk.status_code == 200
    assert brk.json()["mors"]["expression"]


def test_quiz_flow_scores_100(
    client: TestClient, demo_headers: dict[str, str], first_lesson: str
) -> None:
    from app.db import Quiz as QuizModel, SessionLocal

    generated = client.post(
        "/api/quiz/generate",
        headers=demo_headers,
        json={"lesson_id": first_lesson, "count": 5, "difficulty": 3},
    )
    assert generated.status_code == 200
    quiz = generated.json()
    assert quiz["question_count"] == 5
    assert all("answer_key" not in q for q in quiz["questions"])
    assert all("correct" not in o for o in quiz["questions"][0]["options"])

    started = client.post(f"/api/quiz/{quiz['id']}/start", headers=demo_headers)
    attempt_id = started.json()["attempt_id"]

    db = SessionLocal()
    try:
        row = db.get(QuizModel, quiz["id"])
        answers = []
        for question in row.questions:
            correct = [o for o in question.options if o.is_correct]
            answers.append((question.id, correct[0].id if correct else question.answer_key))
    finally:
        db.close()

    for question_id, answer in answers:
        submitted = client.post(
            f"/api/quiz/attempts/{attempt_id}/answer",
            headers=demo_headers,
            json={"question_id": question_id, "answer": answer, "time_seconds": 15},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["correct"] is True

    finished = client.post(f"/api/quiz/attempts/{attempt_id}/finish", headers=demo_headers)
    assert finished.status_code == 200
    report = finished.json()
    assert report["accuracy"] == 100.0
    assert report["correct"] == 5
    assert report["score"] == report["max_score"]

    stored = client.get(f"/api/quiz/attempts/{attempt_id}/report", headers=demo_headers)
    assert stored.status_code == 200
    assert stored.json()["accuracy"] == 100.0

    history = client.get("/api/quiz", headers=demo_headers).json()["quizzes"]
    entry = next(q for q in history if q["id"] == quiz["id"])
    assert entry["last_accuracy"] == 100.0

    wrong = client.post(
        f"/api/quiz/attempts/{attempt_id}/answer",
        headers=demo_headers,
        json={"question_id": answers[0][0], "answer": "not-an-option"},
    )
    assert wrong.status_code == 200
    assert wrong.json()["correct"] is False


def test_diagnostic_quiz(client: TestClient, demo_headers: dict[str, str]) -> None:
    response = client.post("/api/onboarding/diagnostic", headers=demo_headers, json={"count": 6})
    assert response.status_code == 200
    assert response.json()["question_count"] == 6


def test_recovery_redistributes_the_backlog(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    """§2.4: a missed stretch must move the remaining work, not just log it."""
    from app.db import SessionLocal, StudentProfile, Task, User

    plan = client.post("/api/plan/generate", headers=demo_headers, json={"days": 5})
    assert plan.status_code == 200, plan.text

    today = date.today()
    db = SessionLocal()
    try:
        profile = (
            db.query(StudentProfile)
            .join(User, User.id == StudentProfile.user_id)
            .filter(User.email == "demo@mors.ai")
            .first()
        )
        assert profile is not None, "demo profile missing"
        stale = (
            db.query(Task)
            .filter(
                Task.student_id == profile.id,
                Task.status.in_(["pending", "in_progress"]),
                Task.type != "rest",
            )
            .limit(6)
            .all()
        )
        assert len(stale) >= 4, f"expected a backlog to shift, got {len(stale)}"
        stale_ids = [t.id for t in stale]
        for task in stale:
            task.scheduled_date = today - timedelta(days=3)
        db.commit()
    finally:
        db.close()

    before = {
        t["id"]: t.get("date")
        for t in client.get("/api/plan/tasks", headers=demo_headers).json()["tasks"]
    }
    assert all(
        before.get(task_id) and date.fromisoformat(before[task_id]) < today
        for task_id in stale_ids
    ), before

    recovery = client.post("/api/plan/recovery", headers=demo_headers)
    assert recovery.status_code == 200, recovery.text
    body = recovery.json()
    assert body["kept"] >= len(stale_ids), body
    assert body["spread_days"] >= 2, body
    assert body["plan"] is not None

    after = client.get("/api/plan/tasks", headers=demo_headers).json()["tasks"]
    moved = [t for t in after if t["id"] in stale_ids]
    assert len(moved) == len(stale_ids), (len(moved), len(stale_ids))
    dates = {date.fromisoformat(t["date"]) for t in moved if t.get("date")}
    assert all(day >= today for day in dates), f"backlog still in the past: {dates}"
    assert len(dates) >= 2, f"work must spread across days, not pile up: {dates}"
    assert all(t["status"] == "pending" for t in moved), moved
