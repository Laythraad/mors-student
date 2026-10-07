"""Chat, Mors personality, progress, library, media, exports and admin."""

from __future__ import annotations

from fastapi.testclient import TestClient

BANNED = ("تستاهل", "غبي", "خبل", "كسلان", "ما تفهم")


def test_chat_tutor_and_refusal(
    client: TestClient, demo_headers: dict[str, str], first_lesson: str
) -> None:
    ok = client.post(
        "/api/chat/messages",
        headers=demo_headers,
        json={"message": "اشرح لي المتتاليات الحسابية", "mode": "tutor", "lesson_id": first_lesson},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["reply"]
    conversation_id = body["conversation_id"]

    off = client.post(
        "/api/chat/messages",
        headers=demo_headers,
        json={"message": "شنو رأيك بحرب العراق؟", "mode": "tutor"},
    )
    assert off.status_code == 200
    assert off.json()["refused"] is True
    assert off.json()["confidence"] <= 0.5

    transcript = client.get(
        f"/api/chat/conversations/{conversation_id}", headers=demo_headers
    ).json()
    assert transcript["messages"]

    listed = client.get("/api/chat/conversations", headers=demo_headers).json()["conversations"]
    assert listed

    chit = client.post(
        "/api/chat/messages", headers=demo_headers, json={"message": "هلا شلونك"}
    )
    assert chit.status_code == 200


def test_mors_feed_and_tone(client: TestClient, demo_headers: dict[str, str]) -> None:
    state = client.get("/api/inbox/mors/state", headers=demo_headers).json()
    assert state["expression"] and state["sprite"].startswith("/mors/")

    messages = client.get("/api/inbox/mors/messages", headers=demo_headers).json()["messages"]
    for message in messages:
        assert not any(word in message["text"] for word in BANNED), message["text"]
        assert "{" not in message["text"] and "}" not in message["text"]
        assert not message["text"].startswith("Scenario"), message["text"]

    policy = client.get("/api/inbox/delivery-policy", headers=demo_headers).json()
    assert "focus_mode" in policy and "quiet" in policy

    history = client.get("/api/inbox/mors/history", headers=demo_headers).json()["messages"]
    assert history

    notifications = client.get("/api/inbox/notifications", headers=demo_headers).json()
    assert "unread" in notifications

    if notifications["notifications"]:
        first = notifications["notifications"][0]["id"]
        read = client.post(
            "/api/inbox/notifications/read", headers=demo_headers, json={"ids": [first]}
        )
        assert read.status_code == 200


def test_progress_dashboard_and_coach(client: TestClient, demo_headers: dict[str, str]) -> None:
    home = client.get("/api/progress/home", headers=demo_headers).json()
    for key in ("greeting", "mors", "streak", "today", "next", "reviews", "subjects"):
        assert key in home, key

    report = client.get("/api/progress/report", headers=demo_headers).json()
    assert "totals" in report and "streak" in report

    week = client.get("/api/progress/week", headers=demo_headers).json()
    assert {"sessions", "minutes", "quizzes"} <= set(week)

    streak = client.get("/api/progress/streak", headers=demo_headers).json()
    assert streak["current"] >= 0 and streak["longest"] >= streak["current"]

    achievements = client.get("/api/progress/achievements", headers=demo_headers).json()["achievements"]
    assert len(achievements) >= 10
    assert all(a["threshold"] > 0 for a in achievements)

    weak = client.get("/api/progress/weak", headers=demo_headers).json()["topics"]
    if weak:
        resolved = client.post(
            "/api/progress/weak/resolve", headers=demo_headers, json={"topic": weak[0]["topic"]}
        )
        assert resolved.status_code == 200

    brief = client.get("/api/progress/coach/daily", headers=demo_headers).json()
    assert brief["headline"] and brief["lines"]

    actions = client.get("/api/progress/coach/actions", headers=demo_headers).json()["actions"]
    assert isinstance(actions, list)

    mastery = client.get("/api/progress/mastery", headers=demo_headers).json()["mastery"]
    assert isinstance(mastery, list)


def test_library_notes_summaries_cards_papers(
    client: TestClient, demo_headers: dict[str, str], first_lesson: str
) -> None:
    note = client.post(
        "/api/library/notes",
        headers=demo_headers,
        json={"title": "ملاحظة الاختبار", "body": "الفرق المشترك ثابت.", "lesson_id": first_lesson},
    )
    assert note.status_code == 200
    note_id = note.json()["id"]

    found = client.get("/api/library/notes", headers=demo_headers, params={"q": "الاختبار"}).json()
    assert found["notes"]

    pinned = client.patch(
        f"/api/library/notes/{note_id}", headers=demo_headers, json={"pinned": True}
    )
    assert pinned.json()["pinned"] is True

    summary = client.post(
        "/api/library/summaries",
        headers=demo_headers,
        json={"lesson_id": first_lesson, "kind": "quick", "use_ai": False},
    )
    assert summary.status_code == 200
    assert summary.json()["body"]

    cards = client.post(
        "/api/library/flashcards/generate",
        headers=demo_headers,
        json={"lesson_id": first_lesson, "count": 5, "use_ai": False},
    ).json()["cards"]
    assert len(cards) == 5

    reviewed = client.post(
        f"/api/library/flashcards/{cards[0]['id']}/review",
        headers=demo_headers,
        json={"quality": 5},
    ).json()
    assert reviewed["reps"] >= 1

    due = client.get("/api/library/flashcards/due", headers=demo_headers).json()["cards"]
    assert due

    paper = client.post(
        "/api/library/papers",
        headers=demo_headers,
        json={"title": "ورقة اختبار", "kind": "worksheet", "lesson_id": first_lesson},
    ).json()
    detail = client.get(f"/api/library/papers/{paper['id']}", headers=demo_headers).json()
    assert detail["pages"]

    page_id = detail["pages"][0]["id"]
    saved = client.put(
        f"/api/library/pages/{page_id}/blocks",
        headers=demo_headers,
        json={"blocks": [{"type": "heading", "content": {"text": "عنوان"}}]},
    )
    assert saved.status_code == 200
    assert saved.json()["pages"][0]["blocks"]

    generated = client.post(
        "/api/library/papers/generate",
        headers=demo_headers,
        json={"lesson_id": first_lesson, "kind": "worksheet", "use_ai": False},
    )
    assert generated.status_code == 200

    listed = client.get("/api/library/papers", headers=demo_headers).json()["papers"]
    assert len(listed) >= 2

    deleted = client.delete(f"/api/library/papers/{paper['id']}", headers=demo_headers)
    assert deleted.status_code == 200


def test_media_upload_search_videos(client: TestClient, demo_headers: dict[str, str]) -> None:
    subjects = client.get("/api/curriculum/subjects").json()["subjects"]
    upload = client.post(
        "/api/media/uploads",
        headers=demo_headers,
        files={
            "file": (
                "notes.txt",
                "المتتالية الحسابية والفرق المشترك".encode("utf-8"),
                "text/plain",
            )
        },
        data={"subject_id": subjects[0]["id"], "kind": "notes"},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["status"] == "indexed"

    uploads = client.get("/api/media/uploads", headers=demo_headers).json()["uploads"]
    assert uploads

    search = client.get("/api/media/search", headers=demo_headers, params={"q": "المتتالية"}).json()
    assert search["groups"]["lessons"]

    teachers = client.get("/api/media/teachers", headers=demo_headers).json()["teachers"]
    assert teachers
    courses = client.get("/api/media/courses", headers=demo_headers).json()["courses"]
    assert courses

    videos = client.get("/api/media/videos", headers=demo_headers).json()["videos"]
    assert videos
    progress = client.post(
        f"/api/media/videos/{videos[0]['id']}/progress",
        headers=demo_headers,
        json={"position": 60, "watched_seconds": 60, "key_idea": "مثال"},
    )
    assert progress.status_code == 200

    too_big = client.post(
        "/api/media/uploads",
        headers=demo_headers,
        files={"file": ("huge.txt", b"x" * 10, "text/plain")},
        data={"kind": "notes"},
    )
    assert too_big.status_code == 200


def test_exports(client: TestClient, demo_headers: dict[str, str]) -> None:
    payload = client.get("/api/progress/export/json", headers=demo_headers).json()
    assert {"student", "dashboard", "progress", "plans"} <= set(payload)

    ics = client.get("/api/progress/export/ics", headers=demo_headers)
    assert ics.status_code == 200
    assert "BEGIN:VCALENDAR" in ics.text and "END:VCALENDAR" in ics.text

    pdf = client.get("/api/progress/export/pdf", headers=demo_headers)
    assert pdf.status_code == 200
    assert pdf.content[:5] == b"%PDF-"


def test_admin_endpoints(client: TestClient, admin_headers: dict[str, str]) -> None:
    prompts = client.get("/api/admin/prompts", headers=admin_headers).json()["prompts"]
    assert prompts and all(p["template"] for p in prompts)

    key = prompts[0]["key"]
    original = prompts[0]["template"]
    updated = client.put(
        f"/api/admin/prompts/{key}",
        headers=admin_headers,
        json={"template": original + "\n# اختبار"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] >= 2

    reset = client.delete(f"/api/admin/prompts/{key}", headers=admin_headers)
    assert reset.status_code == 200

    stats = client.get("/api/admin/stats", headers=admin_headers).json()
    assert stats["lessons"] > 0 and stats["users"] >= 2

    usage = client.get("/api/admin/usage", headers=admin_headers).json()
    assert usage["provider"] == "mock"

    events = client.get("/api/admin/events", headers=admin_headers).json()["events"]
    assert events

    users = client.get("/api/admin/users", headers=admin_headers).json()["users"]
    assert any(u["email"] == "demo@mors.ai" for u in users)

    put = client.put(
        "/api/admin/settings/language", headers=admin_headers, json={"value": "ar"}
    )
    assert put.json()["value"] == "ar"
    got = client.get("/api/admin/settings/language", headers=admin_headers).json()
    assert got["value"] == "ar"
