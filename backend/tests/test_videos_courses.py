"""الفيديو والكورسات: تقدم المشاهدة، متابعة، بوابة اختبار الفيديو، بلاغات المحتوى."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import Quiz as QuizModel, SessionLocal


def _question_answers(quiz_id: str, *, correct: bool) -> list[tuple[str, str]]:
    db = SessionLocal()
    try:
        row = db.get(QuizModel, quiz_id)
        assert row is not None, "quiz missing"
        out: list[tuple[str, str]] = []
        for question in row.questions:
            right = [o for o in question.options if o.is_correct]
            if correct:
                answer = right[0].id if right else (question.answer_key or "")
            else:
                wrong = [o for o in question.options if not o.is_correct]
                if wrong:
                    answer = wrong[0].id
                elif question.type in ("fill_blank", "short_answer", "essay"):
                    answer = "إجابة خاطئة"
                else:
                    answer = question.answer_key or "wrong"
            out.append((question.id, answer))
        return out
    finally:
        db.close()


def _videos(client: TestClient, headers: dict[str, str]) -> list[dict]:
    data = client.get("/api/media/videos", headers=headers)
    assert data.status_code == 200, data.text
    videos = data.json()["videos"]
    assert videos, "seeded videos missing"
    return videos


def _finish_attempt(
    client: TestClient, headers: dict[str, str], quiz_id: str, *, correct: bool
) -> float:
    started = client.post(f"/api/quiz/{quiz_id}/start", headers=headers)
    assert started.status_code == 200, started.text
    attempt_id = started.json()["attempt_id"]
    for question_id, answer in _question_answers(quiz_id, correct=correct):
        answered = client.post(
            f"/api/quiz/attempts/{attempt_id}/answer",
            headers=headers,
            json={"question_id": question_id, "answer": answer, "time_seconds": 15},
        )
        assert answered.status_code == 200, answered.text
    finished = client.post(f"/api/quiz/attempts/{attempt_id}/finish", headers=headers)
    assert finished.status_code == 200, finished.text
    return float(finished.json()["accuracy"])


def test_media_requires_auth(client: TestClient) -> None:
    assert client.get("/api/media/videos").status_code == 401
    assert client.get("/api/media/continue").status_code == 401
    assert client.get("/api/media/courses").status_code == 401
    assert client.post("/api/media/videos/x/report", json={"kind": "other"}).status_code == 401


def test_teachers_enriched(client: TestClient, demo_headers: dict[str, str]) -> None:
    data = client.get("/api/media/teachers", headers=demo_headers)
    assert data.status_code == 200, data.text
    teachers = data.json()["teachers"]
    assert teachers, "seeded teachers missing"
    teacher = teachers[0]
    for key in (
        "subjects",
        "stages",
        "level",
        "verified",
        "duration_minutes",
        "lessons_count",
        "is_demo",
        "channel_url",
        "link_status",
        "verified_at",
        "search_url",
    ):
        assert key in teacher, key
    for t in teachers:
        assert t["link_status"] in ("official", "search", "none"), t["link_status"]
        # Only "official" entries may carry a channel link, and a link is
        # never attached to a demo row.
        if t["link_status"] != "official":
            assert not t["channel_url"], t["name"]
        if t["is_demo"]:
            assert t["link_status"] == "none", t["name"]
        assert "youtube.com/results?search_query=" in t["search_url"]


def test_teacher_search_suggestion_via_cms(
    client: TestClient, demo_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    """A not-yet-verified teacher is listed only as a search suggestion (skill:
    اقتراح بحث فقط) — never with a guessed channel link."""
    payload = {
        "name": "teacher to search",
        "slug": "search-suggestion-fixture",
        "headline": "search only",
        "subjects": ["PHY"],
        "stages": ["grade12"],
        "level": "",
        "link_status": "search",
        "channel_url": "",
        "verified": False,
        "is_demo": False,
        "verified_by": "tester",
    }
    draft = client.post(
        "/api/admin/drafts",
        headers=admin_headers,
        json={"entity": "teacher", "payload": payload, "title": payload["name"]},
    )
    assert draft.status_code == 200, draft.text
    draft_id = draft.json()["id"]
    client.post(f"/api/admin/drafts/{draft_id}/process", headers=admin_headers)
    approved = client.post(
        f"/api/admin/drafts/{draft_id}/review",
        headers=admin_headers,
        json={"approve": True, "note": "search suggestion"},
    )
    assert approved.status_code == 200, approved.text

    teachers = client.get("/api/media/teachers", headers=demo_headers).json()["teachers"]
    entry = next(t for t in teachers if t["id"] == approved.json()["entity_id"])
    assert entry["link_status"] == "search"
    assert entry["channel_url"] == ""
    assert entry["verified"] is False
    assert entry["is_demo"] is False
    assert "search_query=teacher" in entry["search_url"]


def test_courses_carry_progress(client: TestClient, demo_headers: dict[str, str]) -> None:
    data = client.get("/api/media/courses", headers=demo_headers)
    assert data.status_code == 200, data.text
    courses = data.json()["courses"]
    assert courses, "seeded courses missing"
    for course in courses:
        for key in ("id", "title", "video_count", "progress_percent", "teacher", "subject"):
            assert key in course, key
        assert 0.0 <= float(course["progress_percent"]) <= 100.0


def test_course_progress_modules_and_lessons(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    courses = client.get("/api/media/courses", headers=demo_headers).json()["courses"]
    with_videos = next(c for c in courses if c["video_count"] > 0)
    data = client.get(f"/api/media/courses/{with_videos['id']}", headers=demo_headers)
    assert data.status_code == 200, data.text
    payload = data.json()
    for key in ("modules", "lessons", "videos", "progress_percent", "video_total", "watched"):
        assert key in payload, key
    assert payload["videos"]
    assert 0.0 <= float(payload["progress_percent"]) <= 100.0
    for module in payload["modules"]:
        assert module["title"] and module["total"] >= 1
        assert 0.0 <= float(module["percent"]) <= 100.0
    for lesson in payload["lessons"]:
        assert lesson["status_label"] and lesson["status"] in {
            "new",
            "started",
            "watched",
            "quiz_failed",
            "completed",
        }


def test_video_detail_and_neighbours(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    video = _videos(client, demo_headers)[0]
    data = client.get(f"/api/media/videos/{video['id']}", headers=demo_headers)
    assert data.status_code == 200, data.text
    payload = data.json()
    for key in ("status", "status_label", "progress", "course", "lesson", "prev", "next"):
        assert key in payload, key
    assert payload["status"] in {"new", "started", "watched", "quiz_failed", "completed"}
    assert "transcript" in payload

    missing = client.get("/api/media/videos/does-not-exist", headers=demo_headers)
    assert missing.status_code == 404


def test_watch_progress_and_continue(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    video = _videos(client, demo_headers)[0]
    saved = client.post(
        f"/api/media/videos/{video['id']}/progress",
        headers=demo_headers,
        json={"position": 45, "watched_seconds": 45, "key_idea": "الفكرة الأساسية"},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["status"] in {"started", "watched"}
    assert body["progress"]["last_position"] >= 45

    detail = client.get(f"/api/media/videos/{video['id']}", headers=demo_headers).json()
    assert detail["progress"]["watched_seconds"] >= 45

    cont = client.get("/api/media/continue", headers=demo_headers)
    assert cont.status_code == 200, cont.text
    payload = cont.json()
    assert "video" in payload
    if payload["video"]:
        assert payload["video"]["link"].startswith("/videos/")
        assert "resume_from" in payload["video"]


def test_video_quiz_pass_completes_lesson(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    video = _videos(client, demo_headers)[1] if len(_videos(client, demo_headers)) > 1 else _videos(client, demo_headers)[0]
    started = client.post(f"/api/media/videos/{video['id']}/quiz", headers=demo_headers)
    assert started.status_code == 200, started.text
    quiz_id = started.json()["quiz_id"]
    assert started.json()["question_count"] >= 1

    accuracy = _finish_attempt(client, demo_headers, quiz_id, correct=True)
    assert accuracy >= 60, accuracy

    detail = client.get(f"/api/media/videos/{video['id']}", headers=demo_headers).json()
    assert detail["status"] == "completed", detail["status"]
    assert detail["progress"]["completed"] is True
    assert detail["progress"]["quiz_score"] is not None
    assert float(detail["progress"]["quiz_score"]) >= 60


def test_video_quiz_fail_stays_open(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    videos = _videos(client, demo_headers)
    target = next((v for v in videos if v["status"] != "completed"), videos[0])
    started = client.post(f"/api/media/videos/{target['id']}/quiz", headers=demo_headers)
    assert started.status_code == 200, started.text
    quiz_id = started.json()["quiz_id"]

    accuracy = _finish_attempt(client, demo_headers, quiz_id, correct=False)
    assert accuracy < 60, accuracy

    detail = client.get(f"/api/media/videos/{target['id']}", headers=demo_headers).json()
    assert detail["status"] == "quiz_failed", detail["status"]
    assert detail["progress"]["completed"] is False


def test_content_report_reaches_admin(
    client: TestClient, demo_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    video = _videos(client, demo_headers)[0]

    # students cannot read the review queue
    forbidden = client.get("/api/admin/content-reports", headers=demo_headers)
    assert forbidden.status_code == 403

    reported = client.post(
        f"/api/media/videos/{video['id']}/report",
        headers=demo_headers,
        json={"kind": "not_working", "detail": "الرابط يفتح صفحة محذوفة"},
    )
    assert reported.status_code == 200, reported.text
    report_id = reported.json()["report_id"]

    queue = client.get("/api/admin/content-reports", headers=admin_headers)
    assert queue.status_code == 200, queue.text
    reports = queue.json()["reports"]
    mine = next(r for r in reports if r["id"] == report_id)
    assert mine["kind"] == "not_working"
    assert mine["status"] == "open"

    resolved = client.post(
        f"/api/admin/content-reports/{report_id}/resolve", headers=admin_headers
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"

    open_again = client.get(
        "/api/admin/content-reports", headers=admin_headers, params={"status": "open"}
    )
    assert all(r["id"] != report_id for r in open_again.json()["reports"])


def test_invalid_report_kind_rejected(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    video = _videos(client, demo_headers)[0]
    bad = client.post(
        f"/api/media/videos/{video['id']}/report",
        headers=demo_headers,
        json={"kind": "hacked"},
    )
    assert bad.status_code == 422
