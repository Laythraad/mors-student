"""المرشد الطلابي: report problems with solutions, weekly review, real actions."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_advisor_requires_auth(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/advisor").status_code == 401
    assert client.post("/api/advisor/steps/add_review/apply").status_code == 401


def test_overview_shape(client: TestClient, demo_headers: dict[str, str]) -> None:
    data = client.get("/api/advisor", headers=demo_headers)
    assert data.status_code == 200, data.text
    payload = data.json()
    for key in ("context", "report", "weekly", "steps", "priorities", "plan_health", "headline"):
        assert key in payload, key
    assert isinstance(payload["headline"], str) and payload["headline"]
    assert "subjects" in payload["context"] and "stuck_at" in payload["context"]
    assert len(payload["steps"]) >= 5


def test_report_finds_problems_with_solutions(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    report = client.get("/api/advisor/report", headers=demo_headers)
    assert report.status_code == 200, report.text
    data = report.json()
    for key in (
        "strong_subjects",
        "weak_subjects",
        "weak_topics",
        "repeated_mistakes",
        "study_habits",
        "time_management",
        "review_problems",
        "problems",
        "subjects",
    ):
        assert key in data, key
    for problem in data["problems"]:
        assert problem["title"] and problem["solution"], problem
        assert problem["action_key"], problem
        assert problem["severity"] in {"high", "medium", "low"}, problem
        assert isinstance(problem["evidence"], list), problem


def test_weekly_review_shape(client: TestClient, demo_headers: dict[str, str]) -> None:
    weekly = client.get("/api/advisor/weekly", headers=demo_headers)
    assert weekly.status_code == 200, weekly.text
    data = weekly.json()
    for key in (
        "study_hours",
        "completed_lessons",
        "quiz_average",
        "mastery_changes",
        "weak_topics",
        "missed_sessions",
        "improvement",
        "next_week_plan",
    ):
        assert key in data, key
    assert data["improvement"] in {"up", "down", "flat"}
    assert isinstance(data["next_week_plan"], list) and data["next_week_plan"]
    for item in data["next_week_plan"]:
        assert item["title"] and item["minutes"] > 0


def test_steps_and_priorities(client: TestClient, demo_headers: dict[str, str]) -> None:
    data = client.get("/api/advisor/steps", headers=demo_headers)
    assert data.status_code == 200, data.text
    payload = data.json()
    keys = {step["key"] for step in payload["steps"]}
    assert {"add_review", "add_quiz", "add_session", "ease_difficulty", "adjust_plan"} <= keys
    for step in payload["steps"]:
        assert step["title"] and step["detail"]
        assert "requires_approval" in step and "available" in step

    priorities = payload["priorities"]
    assert "subjects" in priorities and "message" in priorities
    if priorities["subjects"]:
        total = sum(row["share"] for row in priorities["subjects"])
        assert total == 100, priorities["subjects"]
        for row in priorities["subjects"]:
            assert row["label"] and row["rank"] >= 1


def test_apply_add_review_and_session(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    review = client.post("/api/advisor/steps/add_review/apply", headers=demo_headers)
    assert review.status_code == 200, review.text
    result = review.json()
    assert result["ok"] is True and result["data"]["review_id"]

    session = client.post("/api/advisor/steps/add_session/apply", headers=demo_headers)
    assert session.status_code == 200, session.text
    assert session.json()["data"]["event_id"]


def test_apply_add_quiz_and_mock(client: TestClient, demo_headers: dict[str, str]) -> None:
    quiz = client.post("/api/advisor/steps/add_quiz/apply", headers=demo_headers)
    assert quiz.status_code == 200, quiz.text
    assert quiz.json()["link"].startswith("/quiz/")

    mock = client.post("/api/advisor/steps/start_mock/apply", headers=demo_headers)
    assert mock.status_code == 200, mock.text
    assert mock.json()["link"].startswith("/exam/")


def test_apply_adjust_plan_and_unknown_key(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    plan = client.post("/api/advisor/steps/adjust_plan/apply", headers=demo_headers)
    assert plan.status_code == 200, plan.text
    assert plan.json()["ok"] is True and plan.json()["link"] == "/plan"

    unknown = client.post("/api/advisor/steps/nope/apply", headers=demo_headers)
    assert unknown.status_code == 404, unknown.text
