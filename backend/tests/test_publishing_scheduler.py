"""مسار نشر المحتوى (§81/§83) والمجدول الخلفي (§126/§132)."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.db import Lesson, RateLimitCounter, SchedulerRun, SessionLocal, StudySession, utcnow
from app.services import scheduler as scheduler_service


def _first_subject(client: TestClient, headers: dict[str, str]) -> str:
    response = client.get("/api/curriculum/subjects", headers=headers)
    assert response.status_code == 200, response.text
    subjects = response.json()["subjects"]
    assert subjects, "المنهج التجريبي ناقص"
    return subjects[0]["id"]


def test_drafts_are_admin_only(client: TestClient, demo_headers: dict[str, str]) -> None:
    assert client.get("/api/admin/drafts").status_code in (401, 403)
    assert client.get("/api/admin/drafts", headers=demo_headers).status_code == 403
    assert client.get("/api/admin/scheduler", headers=demo_headers).status_code == 403
    assert (
        client.post(
            "/api/admin/drafts",
            headers=demo_headers,
            json={"entity": "lesson", "payload": {}},
        ).status_code
        == 403
    )


def test_unknown_entity_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/admin/drafts",
        headers=admin_headers,
        json={"entity": "banana", "payload": {}},
    )
    assert response.status_code == 422, response.text


def test_lesson_draft_full_pipeline(
    client: TestClient, admin_headers: dict[str, str], demo_headers: dict[str, str]
) -> None:
    subject_id = _first_subject(client, demo_headers)
    title = "درس النشر التجريبي — P6"

    created = client.post(
        "/api/admin/drafts",
        headers=admin_headers,
        json={"entity": "lesson", "payload": {"subject_id": subject_id, "title": title}},
    )
    assert created.status_code == 200, created.text
    draft_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    processed = client.post(f"/api/admin/drafts/{draft_id}/process", headers=admin_headers)
    assert processed.status_code == 200, processed.text
    body = processed.json()
    assert body["status"] == "validated", body
    assert body["issues"] == []
    assert body["ai_notes"], "خطوة المعالجة بالذكاء الاصطناعي فارغة"

    reviewed = client.post(
        f"/api/admin/drafts/{draft_id}/review",
        headers=admin_headers,
        json={"approve": True, "note": "مطابق للمنهج."},
    )
    assert reviewed.status_code == 200, reviewed.text
    published = reviewed.json()
    assert published["status"] == "published"
    assert published["entity_id"]

    db = SessionLocal()
    try:
        lesson = db.get(Lesson, published["entity_id"])
        assert lesson is not None and lesson.title == title
        assert lesson.subject_id == subject_id
    finally:
        db.close()

    again = client.post(
        f"/api/admin/drafts/{draft_id}/review",
        headers=admin_headers,
        json={"approve": True},
    )
    assert again.status_code == 422, again.text

    removed = client.delete(f"/api/admin/drafts/{draft_id}", headers=admin_headers)
    assert removed.status_code == 422, removed.text

    listed = client.get("/api/admin/drafts", params={"status": "published"}, headers=admin_headers)
    assert listed.status_code == 200
    assert any(d["id"] == draft_id for d in listed.json()["drafts"])


def test_validation_failure_then_fix(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/admin/drafts",
        headers=admin_headers,
        json={"entity": "lesson", "payload": {"title": "درس بلا مادة"}},
    )
    draft_id = created.json()["id"]

    processed = client.post(f"/api/admin/drafts/{draft_id}/process", headers=admin_headers)
    assert processed.status_code == 200
    body = processed.json()
    assert body["status"] == "rejected"
    assert any("subject_id" in issue for issue in body["issues"])

    early = client.post(
        f"/api/admin/drafts/{draft_id}/review",
        headers=admin_headers,
        json={"approve": True},
    )
    assert early.status_code == 422, early.text

    patched = client.patch(
        f"/api/admin/drafts/{draft_id}",
        headers=admin_headers,
        json={"payload": {"title": "درس بلا مادة", "subject_id": "does-not-exist"}},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "draft"

    reprocessed = client.post(f"/api/admin/drafts/{draft_id}/process", headers=admin_headers)
    assert reprocessed.status_code == 200
    body = reprocessed.json()
    assert body["status"] == "rejected"
    assert any("المادة" in issue for issue in body["issues"])


def test_scheduled_publish_flows_through_job(
    client: TestClient, admin_headers: dict[str, str], demo_headers: dict[str, str]
) -> None:
    subject_id = _first_subject(client, demo_headers)
    title = "درس مجدول — P6"
    created = client.post(
        "/api/admin/drafts",
        headers=admin_headers,
        json={"entity": "lesson", "payload": {"subject_id": subject_id, "title": title}},
    )
    draft_id = created.json()["id"]
    client.post(f"/api/admin/drafts/{draft_id}/process", headers=admin_headers)

    future = (utcnow() + timedelta(hours=2)).isoformat()
    reviewed = client.post(
        f"/api/admin/drafts/{draft_id}/review",
        headers=admin_headers,
        json={"approve": True, "publish_at": future},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "scheduled"
    assert reviewed.json()["entity_id"] is None

    early = client.post(
        "/api/admin/scheduler/publish_due_content/run", headers=admin_headers
    )
    assert early.status_code == 200, early.text
    assert title not in early.json()["detail"].get("published", [])

    db = SessionLocal()
    try:
        from app.db import ContentDraft

        draft = db.get(ContentDraft, draft_id)
        assert draft is not None
        draft.publish_at = utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    due = client.post("/api/admin/scheduler/publish_due_content/run", headers=admin_headers)
    assert due.status_code == 200, due.text
    assert title in due.json()["detail"].get("published", [])

    final = client.get("/api/admin/drafts", params={"q": title}, headers=admin_headers)
    rows = [d for d in final.json()["drafts"] if d["id"] == draft_id]
    assert rows and rows[0]["status"] == "published"
    assert rows[0]["entity_id"]


def test_scheduler_status_and_manual_runs(client: TestClient, admin_headers: dict[str, str]) -> None:
    status = client.get("/api/admin/scheduler", headers=admin_headers)
    assert status.status_code == 200, status.text
    body = status.json()
    names = {job["name"] for job in body["jobs"]}
    assert names == {"publish_due_content", "close_stale_sessions", "prune_rate_counters"}
    for job in body["jobs"]:
        assert job["description"] and job["interval_seconds"] >= 60

    missing = client.post("/api/admin/scheduler/no_such_job/run", headers=admin_headers)
    assert missing.status_code == 404

    run = client.post("/api/admin/scheduler/prune_rate_counters/run", headers=admin_headers)
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "ok"


def test_scheduler_jobs_run_at_service_level() -> None:
    db = SessionLocal()
    try:
        db.add(
            RateLimitCounter(
                bucket="pytest-prune", window_start=utcnow() - timedelta(days=3), count=5
            )
        )
        profile_id = None
        from app.db import StudentProfile

        profile = db.query(StudentProfile).first()
        profile_id = profile.id if profile else None
        stale = None
        if profile_id:
            stale = StudySession(
                student_id=profile_id,
                title="جلسة قديمة",
                status="active",
                started_at=utcnow() - timedelta(hours=20),
                updated_at=utcnow() - timedelta(hours=18),
            )
            db.add(stale)
        db.commit()

        prune = scheduler_service.run_job(db, "prune_rate_counters")
        assert prune["status"] == "ok", prune
        assert prune["detail"]["deleted"] >= 1

        close = scheduler_service.run_job(db, "close_stale_sessions")
        assert close["status"] == "ok", close
        if stale is not None:
            db.refresh(stale)
            assert stale.status == "interrupted"
            assert stale.meta.get("closed_by") == "scheduler"
            db.delete(stale)

        runs = db.query(SchedulerRun).filter(SchedulerRun.job == "prune_rate_counters").count()
        assert runs >= 1
        db.commit()
    finally:
        db.close()
