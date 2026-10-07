"""tools/uat.py — spec §125 acceptance: the full student journey, twice.

Walks one complete journey per active stage:
  1. طالب الرابع العلمي (فرع علمي)
  2. طالب الرابع المهني (قسم تقني)

Covered, in order: account (stage/branch/subjects/schedule/school/sleep/goal)
→ diagnostic → first plan → book page + Mors chat with citations → voice →
study session with Mors' reaction → video + gate quiz → a wrong answer and
Mors' response → worksheet → note → image upload → exam (wrong answer,
mistakes, readiness) → analysis → advisor → plan.

Run from the project root:  python -X utf8 tools/uat.py
Uses the same database as the dev server (DEMO data must be seeded).
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8")

TEMP = Path(tempfile.gettempdir()) / "mors_uat.db"
for suffix in ("", "-wal", "-shm"):
    p = TEMP.with_name(TEMP.name + suffix)
    if p.exists():
        p.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP.as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["DEMO_DATA"] = "true"
os.environ["AI_PROVIDER"] = "mock"
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("AI_RATE_LIMIT_PER_MINUTE", "100000")

PASS = 0
FAIL = 0
TAG = ""

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def check(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    label = f"{TAG}.{name}"
    if ok:
        PASS += 1
        print(f"  ok   {label}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL += 1
        print(f" FAIL  {label}  {detail}")
    return bool(ok)


def _quiz_answers(quiz_id: str) -> list[tuple[str, str]]:
    """Correct answers, read server-side (students only ever see correct: False)."""
    from app.db import Quiz as QuizModel, SessionLocal

    db = SessionLocal()
    try:
        row = db.get(QuizModel, quiz_id)
        out: list[tuple[str, str]] = []
        for question in row.questions:
            correct = [o for o in question.options if o.is_correct]
            answer = correct[0].id if correct else (question.answer_key or "")
            out.append((question.id, answer))
        return out
    finally:
        db.close()


def _quiz_wrong_answers(quiz_id: str) -> list[tuple[str, str]]:
    """Deliberately wrong answers for every question of the quiz."""
    from app.db import Quiz as QuizModel, SessionLocal

    db = SessionLocal()
    try:
        row = db.get(QuizModel, quiz_id)
        out: list[tuple[str, str]] = []
        for question in row.questions:
            wrong = [o for o in question.options if not o.is_correct]
            if wrong:
                out.append((question.id, wrong[0].id))
            elif question.type in ("fill_blank", "short_answer", "essay"):
                out.append((question.id, "إجابة خاطئة"))
            else:
                out.append((question.id, "wrong"))
        return out
    finally:
        db.close()


def _wrong_answer_for(quiz_id: str, question_id: str) -> str:
    """A wrong option id for one exam question (falls back to junk text)."""
    from app.db import Quiz as QuizModel, SessionLocal

    db = SessionLocal()
    try:
        row = db.get(QuizModel, quiz_id)
        for question in row.questions:
            if question.id == question_id:
                wrong = [o for o in question.options if not o.is_correct]
                return wrong[0].id if wrong else "إجابة خاطئة"
        return "إجابة خاطئة"
    finally:
        db.close()


def _finish_quiz(quiz_id: str, headers: dict[str, str], client, *, correct: bool) -> float | None:
    """Start → answer (right or wrong on purpose) → finish; return accuracy."""
    started = client.post(f"/api/quiz/{quiz_id}/start", headers=headers)
    if started.status_code != 200:
        return None
    attempt_id = started.json()["attempt_id"]
    answers = _quiz_answers(quiz_id) if correct else _quiz_wrong_answers(quiz_id)
    for question_id, answer in answers:
        answered = client.post(
            f"/api/quiz/attempts/{attempt_id}/answer",
            headers=headers,
            json={"question_id": question_id, "answer": answer, "time_seconds": 15},
        )
        if answered.status_code != 200:
            return None
    finished = client.post(f"/api/quiz/attempts/{attempt_id}/finish", headers=headers)
    if finished.status_code != 200:
        return None
    return float(finished.json().get("accuracy", -1))


def _first_lesson(client, subject_id: str) -> str | None:
    r = client.get(f"/api/curriculum/subjects/{subject_id}/tree")
    if r.status_code != 200:
        return None
    for chapter in r.json().get("chapters", []):
        for unit in chapter.get("units", []):
            if unit.get("lessons"):
                return unit["lessons"][0]["id"]
    return None


def journey(client, tag: str, stage_code: str, branch_code: str) -> None:
    global TAG
    TAG = tag

    # ---------------------------------------------------------- curriculum shape
    r = client.get("/api/curriculum/stages")
    stages = r.json().get("stages", []) if r.status_code == 200 else []
    stage = next((s for s in stages if s.get("code") == stage_code), None)
    if not check("stage_visible", stage is not None, str([s.get("code") for s in stages])):
        return
    r = client.get("/api/curriculum/branches", params={"stage_id": stage["id"]})
    branches = r.json().get("branches", []) if r.status_code == 200 else []
    branch = next((b for b in branches if b.get("code") == branch_code), None)
    if not check("branch_visible", branch is not None, str([b.get("code") for b in branches])):
        return
    r = client.get("/api/curriculum/subjects", params={"branch_id": branch["id"]})
    subjects = r.json().get("subjects", []) if r.status_code == 200 else []
    if not check("subjects_visible", len(subjects) >= 4, f"{len(subjects)} subjects"):
        return
    subject = subjects[0]

    # -------------------------------------------------- account creation (§125)
    stamp = int(time.time() * 1000) % 10_000_000
    r = client.post(
        "/api/auth/register",
        json={
            "full_name": f"طالب رحلة {tag}",
            "email": f"uat_{tag}_{stamp}@mors.ai",
            "password": "UatPass123!",
        },
    )
    token = (r.json() or {}).get("tokens", {}).get("access_token") if r.status_code == 200 else ""
    if not check("register", r.status_code == 200 and token, r.text[:120]):
        return
    h = {"Authorization": f"Bearer {token}"}

    r = client.patch(
        "/api/auth/profile",
        headers=h,
        json={
            "stage_id": stage["id"],
            "branch_id": branch["id"],
            "daily_study_minutes": 60,
            "school_name": "مدرسة الرحلة التجريبية",
            "goals": "التفوق في اختبارات هذا الفصل",
        },
    )
    check("profile_stage_branch_school_goal", r.status_code == 200, r.text[:100])

    r = client.put(
        "/api/auth/subjects",
        headers=h,
        json={"subject_ids": [s["id"] for s in subjects[:3]]},
    )
    check("subjects_set", r.status_code == 200, r.text[:100])

    # -------------------------------------------------------------- onboarding
    r = client.get("/api/onboarding/steps", headers=h)
    check("steps_visible", r.status_code == 200 and r.json().get("steps"), r.text[:120])
    r = client.post("/api/onboarding/step/welcome", headers=h)
    check("step_welcome", r.status_code == 200, r.text[:80])
    r = client.put(
        "/api/onboarding/schedule",
        headers=h,
        json={
            "school_start": "08:00",
            "school_end": "14:00",
            "sleep_start": "23:00",
            "sleep_end": "06:30",
            "daily_study_minutes": 60,
            "study_days": [0, 1, 2, 3, 4, 5],
        },
    )
    check("schedule_school_sleep", r.status_code == 200, r.text[:100])

    r = client.post(
        "/api/onboarding/diagnostic",
        headers=h,
        json={"subject_ids": [subject["id"]], "count": 8},
    )
    diag = r.json() if r.status_code == 200 else {}
    if check("diagnostic_created", r.status_code == 200 and diag.get("id"), r.text[:160]):
        accuracy = _finish_quiz(str(diag["id"]), h, client, correct=True)
        check("diagnostic_taken", accuracy is not None, str(accuracy))

    r = client.post("/api/onboarding/first-plan", headers=h)
    body = r.json() if r.status_code == 200 else {}
    check("first_plan", r.status_code == 200 and (body.get("plan") or body.get("days")), r.text[:160])
    r = client.get("/api/onboarding/recommend", headers=h)
    check("recommend", r.status_code == 200 and r.json().get("subjects"), r.text[:140])
    r = client.post("/api/onboarding/step/plan", headers=h)
    check("step_plan", r.status_code == 200, r.text[:80])
    r = client.get("/api/onboarding/steps", headers=h)
    progress = (r.json() or {}).get("progress") if r.status_code == 200 else None
    check("onboarding_progress_100", progress == 100, str(progress))

    # ------------------------------------------------- book page + Mors chat
    r = client.get("/api/books", headers=h, params={"subject_id": subject["id"]})
    books = (r.json() or {}).get("books", []) if r.status_code == 200 else []
    if not books:
        r = client.get("/api/books", headers=h)
        books = (r.json() or {}).get("books", []) if r.status_code == 200 else []
    if not check("books_list", bool(books), f"{len(books)} books"):
        return
    book = books[0]

    r = client.get(f"/api/books/{book['id']}", headers=h)
    detail = r.json() if r.status_code == 200 else {}
    check(
        "book_detail",
        r.status_code == 200 and detail.get("toc") and detail.get("is_indexed"),
        f"pages={detail.get('page_count')}",
    )
    r = client.get(f"/api/books/{book['id']}/page", params={"n": 1}, headers=h)
    page1 = r.json() if r.status_code == 200 else {}
    check(
        "book_page1",
        r.status_code == 200
        and len(page1.get("text", "")) > 40
        and "صفحة 1" in page1.get("citation", ""),
        page1.get("citation", "")[:60],
    )
    r = client.put(
        f"/api/books/{book['id']}/progress",
        headers=h,
        json={"last_page": 3, "bookmark": {"page": 3, "label": "علامة"}},
    )
    check("book_progress", r.status_code == 200 and (r.json() or {}).get("last_page") == 3, r.text[:100])
    r = client.post(
        "/api/chat/messages",
        headers=h,
        json={"message": "اشرح لي هذا الجزء", "mode": "explain", "book_id": book["id"], "page_number": 1},
    )
    chat = r.json() if r.status_code == 200 else {}
    cites = chat.get("citations", [])
    check(
        "mors_chat_page_citation",
        r.status_code == 200 and any(c.get("page") == 1 for c in cites),
        str([c.get("citation") for c in cites][:1])[:100],
    )

    lesson_id = _first_lesson(client, subject["id"])
    if not check("subject_has_lesson", lesson_id is not None, str(lesson_id)):
        return

    # ------------------------------------- Mors: tutor chat, voice, expression
    r = client.post(
        "/api/chat/messages",
        headers=h,
        json={"message": "اشرح لي هذا الدرس", "mode": "tutor", "lesson_id": lesson_id},
    )
    check("mors_tutor_reply", r.status_code == 200 and (r.json() or {}).get("reply") is not None, r.text[:160])
    r = client.post(
        "/api/chat/messages",
        headers=h,
        json={"message": "ما هو الدعم العسكري الأمريكي في العراق؟", "mode": "tutor"},
    )
    body = r.json() if r.status_code == 200 else {}
    check("mors_refuses_off_topic", r.status_code == 200 and body.get("refused") is True, r.text[:160])
    r = client.post("/api/voice/speak", headers=h, json={"text": "أهلًا، أنا مورس.", "style": "happy"})
    spoken = r.json() if r.status_code == 200 else {}
    check("voice_speak", r.status_code == 200 and spoken.get("provider") == "browser", r.text[:160])
    r = client.get("/api/inbox/mors/state", headers=h)
    check("mors_state", r.status_code == 200, r.text[:120])

    # ------------------------------------------------------ study session + Mors
    r = client.post(
        "/api/study/start",
        headers=h,
        json={"lesson_id": lesson_id, "goal": "فهم الدرس", "focus_mode": False},
    )
    session = (r.json() or {}).get("session") if r.status_code == 200 else None
    if check("study_start", bool(session), r.text[:160]):
        session_id = session["id"]
        r = client.post(
            f"/api/study/{session_id}/heartbeat",
            headers=h,
            json={"elapsed_seconds": 60 * 25},
        )
        check("study_heartbeat", r.status_code == 200, r.text[:100])
        r = client.post(
            f"/api/study/{session_id}/end",
            headers=h,
            json={"status": "completed", "feedback": "medium", "understanding": 0.7, "mistakes": 2},
        )
        body = r.json() if r.status_code == 200 else {}
        check("study_end_mors_expression", bool((body.get("mors") or {}).get("expression")), str(body.get("mors"))[:100])
        r = client.post("/api/study/feedback", headers=h, json={"feedback": "hard"})
        check("study_feedback", r.status_code == 200, r.text[:120])

    # ------------------------------------------------------------- video + gate
    r = client.get("/api/media/videos", headers=h)
    videos = (r.json() or {}).get("videos", []) if r.status_code == 200 else []
    if check("videos_list", bool(videos), f"{len(videos)} videos"):
        vid = videos[0]["id"]
        r = client.post(
            f"/api/media/videos/{vid}/progress",
            headers=h,
            json={"position": 120, "watched_seconds": 120, "key_idea": "فكرة رئيسية"},
        )
        check("video_progress", r.status_code == 200, r.text[:160])
        r = client.get(f"/api/media/videos/{vid}", headers=h)
        vdetail = r.json() if r.status_code == 200 else {}
        check(
            "video_detail",
            r.status_code == 200 and all(k in vdetail for k in ("status", "progress", "prev", "next", "course")),
            r.text[:160],
        )
        target = next((v for v in videos if v.get("status") != "completed"), None)
        if target is None:
            check("video_gate_pass", True, "all videos already completed in this database")
        else:
            r = client.post(f"/api/media/videos/{target['id']}/quiz", headers=h)
            gate = r.json() if r.status_code == 200 else {}
            if check("video_quiz_start", r.status_code == 200 and gate.get("quiz_id"), r.text[:160]):
                accuracy = _finish_quiz(str(gate["quiz_id"]), h, client, correct=True)
                check("video_gate_pass", accuracy is not None and accuracy >= 60, str(accuracy))
                r = client.get(f"/api/media/videos/{target['id']}", headers=h)
                state = (r.json() or {}).get("status") if r.status_code == 200 else ""
                check("video_completed", state == "completed", str(state))

    # ------------------------------------------------ a wrong answer + Mors' reply
    r = client.post(
        "/api/quiz/generate",
        headers=h,
        json={"lesson_id": lesson_id, "count": 4, "difficulty": 3},
    )
    quiz = r.json() if r.status_code == 200 else {}
    if check("quiz_generate", r.status_code == 200 and quiz.get("question_count", 0) >= 1, r.text[:160]):
        accuracy = _finish_quiz(str(quiz["id"]), h, client, correct=False)
        check("quiz_wrong_answer_scored", accuracy is not None and accuracy < 100, str(accuracy))
        r = client.get("/api/quiz", headers=h)
        check("quiz_history", r.status_code == 200 and (r.json() or {}).get("quizzes"), r.text[:120])
        r = client.get("/api/inbox/mors/messages", headers=h)
        check("mors_messages_after_quiz", r.status_code == 200, r.text[:140])

    # ------------------------------------------------------------ worksheet + note
    r = client.post(
        "/api/library/papers",
        headers=h,
        json={"title": "ورقة عمل الرحلة", "kind": "worksheet", "lesson_id": lesson_id},
    )
    paper = r.json() if r.status_code == 200 else {}
    check("worksheet_created", r.status_code == 200 and paper.get("pages"), r.text[:160])
    r = client.post(
        "/api/library/notes",
        headers=h,
        json={"title": "ملاحظة الرحلة", "body": "ملخص الدرس المهم.", "lesson_id": lesson_id},
    )
    note_id = (r.json() or {}).get("id") if r.status_code == 200 else ""
    check("note_created", r.status_code == 200 and note_id, r.text[:160])
    r = client.get("/api/library/notes", headers=h, params={"q": "الرحلة"})
    check("note_search", r.status_code == 200 and (r.json() or {}).get("notes"), r.text[:160])

    # ------------------------------------------------------------- image upload
    r = client.post(
        "/api/media/uploads",
        headers=h,
        files={"file": ("uaat.png", PNG_1PX, "image/png")},
        data={"subject_id": subject["id"], "kind": "image"},
    )
    upload_id = (r.json() or {}).get("id") if r.status_code == 200 else ""
    check("image_upload", r.status_code == 200 and upload_id, r.text[:200])
    r = client.get("/api/media/uploads", headers=h)
    check("uploads_list", r.status_code == 200, r.text[:140])

    # -------------------------------------------------- exam + analysis (§125)
    r = client.post(
        "/api/exams/generate",
        headers=h,
        json={"subject_id": subject["id"], "count": 6, "duration_minutes": 20},
    )
    exam_quiz = r.json() if r.status_code == 200 else {}
    if not check(
        "exam_generate",
        r.status_code == 200 and exam_quiz.get("question_count", 0) >= 1,
        f"count={exam_quiz.get('question_count')}",
    ):
        exam_quiz = {}
    if exam_quiz:
        r = client.post(
            "/api/exams/start",
            headers=h,
            json={"quiz_id": exam_quiz["id"], "mode": "mock"},
        )
        exam_session = r.json() if r.status_code == 200 else {}
        check(
            "exam_start_timer",
            r.status_code == 200 and exam_session.get("time_left_seconds") == 1200,
            r.text[:160],
        )
        exam_attempt = exam_session.get("exam_attempt_id", "")
        first_question = (exam_session.get("questions") or [{}])[0]
        if first_question:
            r = client.post(
                f"/api/exams/attempts/{exam_attempt}/mark",
                headers=h,
                json={"question_id": first_question["id"]},
            )
            check("exam_mark_for_review", r.status_code == 200 and (r.json() or {}).get("is_marked") is True, r.text[:120])
            wrong = _wrong_answer_for(str(exam_quiz["id"]), str(first_question["id"]))
            r = client.post(
                f"/api/exams/attempts/{exam_attempt}/answer",
                headers=h,
                json={"question_id": first_question["id"], "answer": wrong},
            )
            body = r.json() if r.status_code == 200 else {}
            check(
                "exam_answer_hidden",
                r.status_code == 200 and body.get("ok") is True and "correct" not in body,
                r.text[:140],
            )
            r = client.get(f"/api/exams/attempts/{exam_attempt}", headers=h)
            state = r.json() if r.status_code == 200 else {}
            check("exam_attempt_state", r.status_code == 200 and state.get("answered_count") == 1, r.text[:140])
            r = client.post(f"/api/exams/attempts/{exam_attempt}/submit", headers=h)
            analysis = r.json() if r.status_code == 200 else {}
            check(
                "exam_submit_analysis",
                r.status_code == 200 and "by_difficulty" in analysis and "readiness" in analysis,
                r.text[:180],
            )
            check("exam_new_mistakes", analysis.get("new_mistakes", 0) >= 1, str(analysis.get("new_mistakes")))
            r = client.get("/api/exams/mistakes", headers=h)
            mistakes = r.json() if r.status_code == 200 else {}
            check("exam_mistakes_listed", r.status_code == 200 and mistakes.get("total", 0) >= 1, r.text[:140])
            if mistakes.get("items"):
                rr = client.post(f"/api/exams/mistakes/{mistakes['items'][0]['id']}/resolve", headers=h)
                check(
                    "exam_mistake_resolve",
                    rr.status_code == 200 and (rr.json() or {}).get("is_active") is False,
                    rr.text[:120],
                )
        r = client.get("/api/exams/readiness", headers=h, params={"subject_id": subject["id"]})
        check(
            "exam_readiness",
            r.status_code == 200 and len((r.json() or {}).get("factors", [])) == 6,
            r.text[:160],
        )

    # ------------------------------------------- analysis + advisor + plan (§125)
    r = client.get("/api/progress/home", headers=h)
    check("progress_home", r.status_code == 200, r.text[:140])
    r = client.get("/api/progress/report", headers=h)
    check("progress_report", r.status_code == 200, r.text[:140])
    r = client.get("/api/progress/streak", headers=h)
    check("progress_streak", r.status_code == 200 and "current" in (r.json() or {}), r.text[:120])

    r = client.get("/api/advisor", headers=h)
    advisor = r.json() if r.status_code == 200 else {}
    check(
        "advisor_overview",
        r.status_code == 200
        and all(k in advisor for k in ("context", "report", "weekly", "steps", "priorities", "plan_health")),
        r.text[:160],
    )
    problems = (advisor.get("report") or {}).get("problems") or []
    check(
        "advisor_problems_solutioned",
        isinstance(problems, list) and all(p.get("solution") and p.get("action_key") for p in problems),
        f"n={len(problems)}",
    )
    r = client.get("/api/advisor/report", headers=h)
    report = r.json() if r.status_code == 200 else {}
    check(
        "advisor_report",
        r.status_code == 200 and "strong_subjects" in report and "weak_topics" in report,
        r.text[:140],
    )
    r = client.post("/api/advisor/steps/add_session/apply", headers=h)
    applied = r.json() if r.status_code == 200 else {}
    check(
        "advisor_apply_session",
        r.status_code == 200 and applied.get("ok") is True and (applied.get("data") or {}).get("event_id"),
        r.text[:160],
    )

    r = client.post("/api/plan/generate", headers=h, json={"days": 7})
    plan = (r.json() or {}).get("plan") if r.status_code == 200 else None
    check("plan_generate", bool(plan), r.text[:140])
    r = client.get("/api/plan/current", headers=h)
    check("plan_current", r.status_code == 200, r.text[:120])
    r = client.get("/api/plan/what-now", headers=h)
    check("plan_what_now", r.status_code == 200, r.text[:140])


def main() -> int:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        journey(client, "sci", "grade12", "science")
        journey(client, "voc", "grade12voc", "technical")

    print(f"\nUAT §125: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
