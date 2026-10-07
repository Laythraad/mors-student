"""§2.4 reminders: create / edit / delete / snooze, due notifications, privacy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _iso(delta: timedelta) -> str:
    moment = datetime.now(timezone.utc) + delta
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _register(client, prefix: str) -> dict[str, str]:
    import uuid

    body = client.post(
        "/api/auth/register",
        json={
            "full_name": "طالب آخر",
            "email": f"{prefix}{uuid.uuid4().hex[:8]}@mors.ai",
            "password": "Pytest1234!",
        },
    )
    assert body.status_code == 200, body.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {body.json()['tokens']['access_token']}"}


def test_reminder_crud_and_status_cycle(client, demo_headers):
    created = client.post(
        "/api/reminders",
        json={
            "title": "راجع الفيزياء",
            "due_at": _iso(timedelta(minutes=20)),
            "note": "الفصل الثالث",
        },
        headers=demo_headers,
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["status"] == "pending"
    assert row["due_at"].endswith("Z"), row["due_at"]
    assert row["note"] == "الفصل الثالث"

    listed = client.get("/api/reminders", headers=demo_headers).json()["reminders"]
    assert any(r["id"] == row["id"] for r in listed), listed

    # the plan calendar shows it without any extra work
    calendar = client.get("/api/plan/calendar", headers=demo_headers).json()["events"]
    assert any(e["id"] == row["id"] for e in calendar), calendar

    patched = client.patch(
        f"/api/reminders/{row['id']}",
        json={"title": "مراجعة الفيزياء — الفصل الثالث", "note": "أعمال السنة"},
        headers=demo_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"].startswith("مراجعة")
    assert patched.json()["status"] == "pending"

    finished = client.patch(
        f"/api/reminders/{row['id']}", json={"done": True}, headers=demo_headers
    )
    assert finished.status_code == 200
    assert finished.json()["status"] == "done"

    assert client.delete(f"/api/reminders/{row['id']}", headers=demo_headers).status_code == 200
    gone = client.get("/api/reminders", headers=demo_headers).json()["reminders"]
    assert all(r["id"] != row["id"] for r in gone)
    assert client.delete(f"/api/reminders/{row['id']}", headers=demo_headers).status_code == 404


def test_due_reminder_notifies_once_and_snoozes_forward(client, demo_headers):
    created = client.post(
        "/api/reminders",
        json={"title": "حل تمارين رياضيات", "due_at": _iso(timedelta(minutes=-5))},
        headers=demo_headers,
    )
    assert created.status_code == 200, created.text
    reminder_id = created.json()["id"]
    assert created.json()["status"] == "due"

    def inbox_titles() -> list[str]:
        notes = client.get("/api/inbox/notifications", headers=demo_headers).json()[
            "notifications"
        ]
        return [n["title"] for n in notes]

    client.get("/api/reminders", headers=demo_headers)
    assert len([t for t in inbox_titles() if "حل تمارين رياضيات" in t]) == 1

    # asking again must not spam the inbox
    client.get("/api/reminders", headers=demo_headers)
    client.get("/api/reminders", headers=demo_headers)
    assert len([t for t in inbox_titles() if "حل تمارين رياضيات" in t]) == 1

    snoozed = client.post(
        f"/api/reminders/{reminder_id}/snooze", json={"minutes": 45}, headers=demo_headers
    )
    assert snoozed.status_code == 200, snoozed.text
    body = snoozed.json()
    assert body["status"] == "snoozed"
    assert body["snooze_count"] == 1
    assert body["due_at"] != created.json()["due_at"]

    only = [
        r
        for r in client.get("/api/reminders", headers=demo_headers).json()["reminders"]
        if r["id"] == reminder_id
    ]
    assert only and only[0]["status"] == "snoozed", only

    # bad durations are refused at the door
    for minutes in (0, -3, 999999):
        bad = client.post(
            f"/api/reminders/{reminder_id}/snooze",
            json={"minutes": minutes},
            headers=demo_headers,
        )
        assert bad.status_code == 422, (minutes, bad.status_code, bad.text)


def test_reminders_are_private_and_planner_entries_are_read_only(client, demo_headers):
    created = client.post(
        "/api/reminders",
        json={"title": "تذكير خاص", "due_at": _iso(timedelta(hours=3))},
        headers=demo_headers,
    ).json()

    other = _register(client, "intruder")
    assert (
        client.patch(
            f"/api/reminders/{created['id']}", json={"title": "x"}, headers=other
        ).status_code
        == 404
    )
    assert client.delete(f"/api/reminders/{created['id']}", headers=other).status_code == 404
    assert (
        client.post(
            f"/api/reminders/{created['id']}/snooze", json={"minutes": 5}, headers=other
        ).status_code
        == 404
    )

    # planner-generated calendar rows are shown on /plan but never editable here
    client.post("/api/plan/generate", json={"days": 3}, headers=demo_headers)
    linked = [
        e
        for e in client.get("/api/plan/calendar", headers=demo_headers).json()["events"]
        if e.get("task_id") or e.get("exam_id")
    ]
    assert linked, "plan generation should place task events on the calendar"
    assert (
        client.patch(
            f"/api/reminders/{linked[0]['id']}", json={"title": "hack"}, headers=demo_headers
        ).status_code
        == 404
    )


def test_reminder_input_is_validated(client, demo_headers):
    empty = client.post(
        "/api/reminders", json={"title": "   ", "due_at": _iso(timedelta(hours=1))},
        headers=demo_headers,
    )
    assert empty.status_code == 422, empty.text

    missing_due = client.post(
        "/api/reminders", json={"title": "بدون وقت", "due_at": ""}, headers=demo_headers
    )
    assert missing_due.status_code == 422, missing_due.text

    bad_due = client.post(
        "/api/reminders",
        json={"title": "وقت غلط", "due_at": "not-a-date"},
        headers=demo_headers,
    )
    assert bad_due.status_code == 422, bad_due.text


def test_status_filter_returns_only_that_state(client, demo_headers):
    pending = client.post(
        "/api/reminders",
        json={"title": "تذكير قادم", "due_at": _iso(timedelta(days=1))},
        headers=demo_headers,
    ).json()
    due = client.post(
        "/api/reminders",
        json={"title": "تذكير فائت", "due_at": _iso(timedelta(hours=-1))},
        headers=demo_headers,
    ).json()
    client.get("/api/reminders", headers=demo_headers)

    only_due = client.get(
        "/api/reminders", params={"status": "due"}, headers=demo_headers
    ).json()["reminders"]
    assert [r["id"] for r in only_due] == [due["id"]], only_due

    only_pending = client.get(
        "/api/reminders", params={"status": "pending"}, headers=demo_headers
    ).json()["reminders"]
    assert pending["id"] in [r["id"] for r in only_pending]
    assert due["id"] not in [r["id"] for r in only_pending]
