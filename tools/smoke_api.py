"""End-to-end smoke test for the HTTP API layer (FastAPI TestClient).

Run:  python -X utf8 tools/smoke_api.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8")

TEMP = Path(tempfile.gettempdir()) / "mors_api_smoke.db"
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

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    print(f"[{'OK ' if ok else 'FAIL'}] {name} {detail}")


def main() -> int:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        # ---------------------------------------------------------------- health
        r = client.get("/health")
        check("health", r.status_code == 200 and r.json()["status"] == "ok", r.text[:80])

        # ------------------------------------------------------------ curriculum
        r = client.get("/api/curriculum/stages")
        stages = r.json().get("stages", []) if r.status_code == 200 else []
        check("curriculum.stages", r.status_code == 200 and stages, f"{len(stages)} stages")
        stage = next((s for s in stages if "الرابع" in str(s.get("name_ar", ""))), stages[0])

        r = client.get("/api/curriculum/branches", params={"stage_id": stage["id"]})
        branches = r.json().get("branches", [])
        check("curriculum.branches", r.status_code == 200 and branches, f"{len(branches)}")
        branch = next((b for b in branches if b.get("code") == "science"), branches[0])

        r = client.get("/api/curriculum/subjects", params={"branch_id": branch["id"]})
        subjects = r.json().get("subjects", [])
        check("curriculum.subjects", r.status_code == 200 and subjects, f"{len(subjects)} subjects")
        subject = subjects[0]

        r = client.get(f"/api/curriculum/subjects/{subject['id']}/tree")
        chapters = r.json().get("chapters", []) if r.status_code == 200 else []
        lesson_id = None
        for chapter in chapters:
            for unit in chapter.get("units", []):
                if unit.get("lessons"):
                    lesson_id = unit["lessons"][0]["id"]
                    break
            if lesson_id:
                break
        check("curriculum.subject_tree", r.status_code == 200 and bool(lesson_id), str(lesson_id)[:40])

        # ------------------------------------------------------------ demo login
        r = client.post("/api/auth/login", json={"identifier": "demo@mors.ai", "password": "DemoPass123!"})
        check("auth.demo_login", r.status_code == 200, r.text[:120])
        demo_token = r.json()["tokens"]["access_token"]
        demo_headers = {"Authorization": f"Bearer {demo_token}"}

        r = client.get("/api/auth/me", headers=demo_headers)
        check("auth.me", r.status_code == 200 and r.json()["user"]["role"] == "student", r.text[:100])

        # ---------------------------------------------------------------- books
        r = client.get("/api/books", headers=demo_headers)
        payload = r.json() if r.status_code == 200 else {}
        books = payload.get("books", [])
        check("books.index", r.status_code == 200 and books, f"{len(books)} books")
        book = books[0] if books else {"id": ""}

        r = client.get(f"/api/books/{book['id']}", headers=demo_headers)
        detail = r.json() if r.status_code == 200 else {}
        check(
            "books.detail",
            r.status_code == 200 and detail.get("toc") and detail.get("is_indexed"),
            f"pages={detail.get('page_count')}",
        )

        r = client.get(f"/api/books/{book['id']}/page", params={"n": 1}, headers=demo_headers)
        page1 = r.json() if r.status_code == 200 else {}
        check(
            "books.page",
            r.status_code == 200 and len(page1.get("text", "")) > 40 and "صفحة 1" in page1.get("citation", ""),
            page1.get("citation", "")[:80],
        )

        r = client.get(f"/api/books/{book['id']}/search", params={"q": "الدرس"}, headers=demo_headers)
        check("books.search", r.status_code == 200 and r.json().get("results"), f"{len(r.json().get('results', []))} hits")

        r = client.put(
            f"/api/books/{book['id']}/progress",
            headers=demo_headers,
            json={"last_page": 3, "bookmark": {"page": 3, "label": "تجربة"}},
        )
        progress = r.json() if r.status_code == 200 else {}
        check("books.progress", r.status_code == 200 and progress.get("last_page") == 3, str(progress)[:120])

        r = client.post(
            "/api/chat/messages",
            headers=demo_headers,
            json={
                "message": "اشرح لي هذا الجزء",
                "mode": "explain",
                "book_id": book["id"],
                "page_number": 1,
            },
        )
        chat = r.json() if r.status_code == 200 else {}
        cites = chat.get("citations", [])
        check(
            "books.chat_page_citation",
            r.status_code == 200 and any(c.get("page") == 1 for c in cites),
            str([c.get("citation") for c in cites][:1])[:120],
        )

        r = client.post(f"/api/books/{book['id']}/reindex", headers=demo_headers)
        check("books.reindex_role_gate", r.status_code == 403, f"status={r.status_code}")

        # ------------------------------------------------------------- register
        r = client.post(
            "/api/auth/register",
            json={"full_name": "طالب جديد", "email": "newbie@mors.ai", "password": "NewPass123!"},
        )
        check("auth.register", r.status_code == 200, r.text[:140])
        new_token = r.json()["tokens"]["access_token"]
        new_headers = {"Authorization": f"Bearer {new_token}"}

        r = client.patch(
            "/api/auth/profile",
            headers=new_headers,
            json={"stage_id": stage["id"], "branch_id": branch["id"], "daily_study_minutes": 60},
        )
        check("auth.patch_profile", r.status_code == 200, r.text[:100])

        r = client.put(
            "/api/auth/subjects",
            headers=new_headers,
            json={"subject_ids": [subjects[0]["id"]]},
        )
        check("auth.set_subjects", r.status_code == 200, r.text[:100])

        r = client.get("/api/onboarding/steps", headers=new_headers)
        check("onboarding.steps", r.status_code == 200 and "steps" in r.json(), r.text[:120])

        r = client.post("/api/onboarding/step/welcome", headers=new_headers)
        check("onboarding.advance", r.status_code == 200, r.text[:80])

        r = client.get("/api/onboarding/recommend", headers=new_headers)
        check("onboarding.recommend", r.status_code == 200, f"{len(r.json().get('subjects', []))} subjects")

        # ---------------------------------------------------------------- plan
        r = client.post("/api/plan/generate", headers=demo_headers, json={"days": 7})
        check("plan.generate", r.status_code == 200 and r.json().get("plan"), r.text[:160])
        plan = r.json().get("plan") or {}
        task = None
        for day in plan.get("days", []):
            if day.get("tasks"):
                task = day["tasks"][0]
                break
        check("plan.has_task", task is not None, str(task)[:80])

        r = client.get("/api/plan/current", headers=demo_headers)
        check("plan.current", r.status_code == 200, r.text[:100])

        r = client.get("/api/plan/what-now", headers=demo_headers)
        check("plan.what_now", r.status_code == 200 and "mors" in r.json() or r.status_code == 200, r.text[:160])

        r = client.get("/api/plan/tasks", headers=demo_headers)
        check("plan.tasks", r.status_code == 200 and r.json().get("tasks"), f"{len(r.json().get('tasks', []))} tasks")

        r = client.get("/api/plan/calendar", headers=demo_headers)
        check("plan.calendar", r.status_code == 200, f"{len(r.json().get('events', []))} events")

        r = client.post(
            "/api/plan/exams",
            headers=demo_headers,
            json={"title": "امتحان تجريبي", "exam_date": _soon(9), "subject_id": subjects[0]["id"]},
        )
        check("plan.create_exam", r.status_code == 200, r.text[:120])

        r = client.get("/api/plan/exams", headers=demo_headers)
        exam = (r.json().get("exams") or [{}])[0]
        check("plan.list_exams", r.status_code == 200 and exam.get("days_left") is not None, r.text[:140])

        # --------------------------------------------------------------- study
        r = client.post(
            "/api/study/start",
            headers=demo_headers,
            json={"lesson_id": lesson_id, "goal": "فهم الفرق المشترك", "focus_mode": False},
        )
        check("study.start", r.status_code == 200 and r.json().get("session"), r.text[:200])
        session_id = r.json()["session"]["id"]

        r = client.post(
            f"/api/study/{session_id}/heartbeat",
            headers=demo_headers,
            json={"elapsed_seconds": 60 * 25},
        )
        check("study.heartbeat", r.status_code == 200, r.text[:120])

        r = client.get("/api/study/active", headers=demo_headers)
        check("study.active", r.status_code == 200, r.text[:120])

        r = client.post(
            f"/api/study/{session_id}/end",
            headers=demo_headers,
            json={"status": "completed", "feedback": "medium", "understanding": 0.7, "mistakes": 2},
        )
        body = r.json() if r.status_code == 200 else {}
        check("study.end", r.status_code == 200 and body.get("ok"), r.text[:200])
        check("study.end_mors", bool((body.get("mors") or {}).get("expression")), str(body.get("mors"))[:100])

        r = client.post("/api/study/feedback", headers=demo_headers, json={"feedback": "hard"})
        check("study.feedback", r.status_code == 200, r.text[:140])

        r = client.get("/api/study/suggested-duration", headers=demo_headers)
        check("study.suggested_duration", r.status_code == 200, r.text[:140])

        r = client.post("/api/study/break", headers=demo_headers)
        check("study.break", r.status_code == 200, r.text[:160])

        # ---------------------------------------------------------------- quiz
        r = client.post(
            "/api/quiz/generate",
            headers=demo_headers,
            json={"lesson_id": lesson_id, "count": 5, "difficulty": 3},
        )
        check("quiz.generate", r.status_code == 200 and r.json().get("question_count") == 5, r.text[:200])
        quiz = r.json()
        check("quiz.hides_answers", "answer_key" not in str(quiz.get("questions", [])[:1]), "")

        r = client.post(f"/api/quiz/{quiz['id']}/start", headers=demo_headers)
        check("quiz.start_attempt", r.status_code == 200 and r.json().get("attempt_id"), r.text[:140])
        attempt_id = r.json()["attempt_id"]

        # fetch answers server-side to answer correctly
        answers = _quiz_answers(client, demo_headers, quiz["id"])
        for question_id, answer in answers:
            r = client.post(
                f"/api/quiz/attempts/{attempt_id}/answer",
                headers=demo_headers,
                json={"question_id": question_id, "answer": answer, "time_seconds": 20},
            )
            if r.status_code != 200:
                check("quiz.answer", False, r.text[:200])
                break
        else:
            check("quiz.answer", True, f"{len(answers)} answers")

        r = client.post(f"/api/quiz/attempts/{attempt_id}/finish", headers=demo_headers)
        report = r.json() if r.status_code == 200 else {}
        check("quiz.finish", r.status_code == 200 and "accuracy" in report, r.text[:240])
        check("quiz.accuracy_100", report.get("accuracy", 0) == 100.0, str(report.get("accuracy")))

        r = client.get(f"/api/quiz/attempts/{attempt_id}/report", headers=demo_headers)
        check("quiz.report", r.status_code == 200, r.text[:120])

        r = client.get("/api/quiz", headers=demo_headers)
        check("quiz.history", r.status_code == 200 and r.json().get("quizzes"), r.text[:140])

        # ---------------------------------------------------------------- exams
        r = client.get("/api/exams", headers=demo_headers)
        exams_home = r.json() if r.status_code == 200 else {}
        check(
            "exams.home",
            r.status_code == 200 and "subjects" in exams_home and "readiness_overall" in exams_home,
            r.text[:160],
        )

        r = client.post(
            "/api/exams/generate",
            headers=demo_headers,
            json={"subject_id": subject["id"], "count": 6, "duration_minutes": 20},
        )
        exam_quiz = r.json() if r.status_code == 200 else {}
        check(
            "exams.generate",
            r.status_code == 200 and exam_quiz.get("question_count", 0) >= 1,
            r.text[:200],
        )

        r = client.post(
            "/api/exams/start",
            headers=demo_headers,
            json={"quiz_id": exam_quiz["id"], "mode": "mock"},
        )
        session = r.json() if r.status_code == 200 else {}
        check(
            "exams.start_timer",
            r.status_code == 200 and session.get("time_left_seconds") == 1200,
            r.text[:200],
        )
        exam_attempt = session.get("exam_attempt_id", "")
        first_question = (session.get("questions") or [{}])[0]

        r = client.post(
            f"/api/exams/attempts/{exam_attempt}/mark",
            headers=demo_headers,
            json={"question_id": first_question["id"]},
        )
        check(
            "exams.mark_for_review",
            r.status_code == 200 and r.json().get("is_marked") is True,
            r.text[:140],
        )

        r = client.post(
            f"/api/exams/attempts/{exam_attempt}/answer",
            headers=demo_headers,
            json={
                "question_id": first_question["id"],
                "answer": first_question["options"][0]["id"],
            },
        )
        body = r.json() if r.status_code == 200 else {}
        check(
            "exams.answer_hidden",
            r.status_code == 200 and body.get("ok") is True and "correct" not in body,
            r.text[:160],
        )

        r = client.get(f"/api/exams/attempts/{exam_attempt}", headers=demo_headers)
        state = r.json() if r.status_code == 200 else {}
        check(
            "exams.attempt_state",
            r.status_code == 200 and state.get("answered_count") == 1,
            r.text[:160],
        )

        r = client.post(f"/api/exams/attempts/{exam_attempt}/submit", headers=demo_headers)
        analysis = r.json() if r.status_code == 200 else {}
        check(
            "exams.submit_analysis",
            r.status_code == 200 and "by_difficulty" in analysis and "readiness" in analysis,
            r.text[:220],
        )
        check(
            "exams.submit_accuracy",
            0 <= analysis.get("accuracy", -1) <= 100,
            str(analysis.get("accuracy")),
        )
        check("exams.submit_mistakes", analysis.get("new_mistakes", 0) >= 1, str(analysis.get("new_mistakes")))

        r = client.get("/api/exams/mistakes", headers=demo_headers)
        mistakes = r.json() if r.status_code == 200 else {}
        check("exams.mistakes", r.status_code == 200 and mistakes.get("total", 0) >= 1, r.text[:160])
        if mistakes.get("items"):
            rr = client.post(
                f"/api/exams/mistakes/{mistakes['items'][0]['id']}/resolve", headers=demo_headers
            )
            check(
                "exams.mistake_resolve",
                rr.status_code == 200 and rr.json().get("is_active") is False,
                rr.text[:140],
            )

        r = client.get(
            "/api/exams/readiness",
            headers=demo_headers,
            params={"subject_id": subject["id"]},
        )
        check(
            "exams.readiness",
            r.status_code == 200 and len(r.json().get("factors", [])) == 6,
            r.text[:200],
        )

        r = client.get("/api/exams/bank", headers=demo_headers)
        check("exams.bank_requires_role", r.status_code == 403, str(r.status_code))

        # ------------------------------------------------------------- advisor
        r = client.get("/api/advisor", headers=demo_headers)
        advisor = r.json() if r.status_code == 200 else {}
        check(
            "advisor.overview",
            r.status_code == 200
            and all(
                k in advisor
                for k in ("context", "report", "weekly", "steps", "priorities", "plan_health", "headline")
            ),
            r.text[:200],
        )
        problems = (advisor.get("report") or {}).get("problems") or []
        check(
            "advisor.problems_solutioned",
            isinstance(problems, list) and all(p.get("solution") and p.get("action_key") for p in problems),
            f"n={len(problems)}",
        )

        r = client.get("/api/advisor/report", headers=demo_headers)
        check(
            "advisor.report",
            r.status_code == 200 and "strong_subjects" in r.json() and "weak_topics" in r.json(),
            r.text[:160],
        )

        r = client.get("/api/advisor/weekly", headers=demo_headers)
        weekly = r.json() if r.status_code == 200 else {}
        check(
            "advisor.weekly",
            r.status_code == 200 and bool(weekly.get("next_week_plan")) and "study_hours" in weekly,
            r.text[:160],
        )

        r = client.get("/api/advisor/steps", headers=demo_headers)
        steps_payload = r.json() if r.status_code == 200 else {}
        steps = steps_payload.get("steps") or []
        check("advisor.steps", r.status_code == 200 and len(steps) >= 5, f"n={len(steps)}")
        shares = [row.get("share", 0) for row in (steps_payload.get("priorities") or {}).get("subjects", [])]
        check("advisor.priorities_shares", bool(shares) and sum(shares) == 100, str(shares))
        check(
            "advisor.plan_health",
            "completion" in (steps_payload.get("plan_health") or {}),
            str((steps_payload.get("plan_health") or {}).get("message", ""))[:80],
        )

        r = client.post("/api/advisor/steps/add_session/apply", headers=demo_headers)
        applied = r.json() if r.status_code == 200 else {}
        check(
            "advisor.apply_session",
            r.status_code == 200 and applied.get("ok") is True and applied.get("data", {}).get("event_id"),
            r.text[:200],
        )

        r = client.post("/api/advisor/steps/add_review/apply", headers=demo_headers)
        applied = r.json() if r.status_code == 200 else {}
        check(
            "advisor.apply_review",
            r.status_code == 200 and applied.get("data", {}).get("review_id"),
            r.text[:200],
        )

        r = client.post("/api/advisor/steps/nope/apply", headers=demo_headers)
        check("advisor.unknown_step_404", r.status_code == 404, str(r.status_code))

        # ---------------------------------------------------------------- chat
        r = client.post(
            "/api/chat/messages",
            headers=demo_headers,
            json={"message": "اشرح لي المتتاليات الحسابية", "mode": "tutor", "lesson_id": lesson_id},
        )
        check("chat.message", r.status_code == 200, r.text[:240])
        chat_conversation_id = (r.json() or {}).get("conversation_id")

        r = client.post(
            "/api/chat/messages",
            headers=demo_headers,
            json={"message": "ما هو الدعم العسكري الأمريكي في العراق؟", "mode": "tutor"},
        )
        body = r.json() if r.status_code == 200 else {}
        check("chat.refusal_off_topic", r.status_code == 200 and body.get("refused") is True, r.text[:240])

        r = client.post("/api/chat/conversations", headers=demo_headers, json={"lesson_id": lesson_id})
        conversation_id = r.json().get("id")
        check("chat.create_conversation", r.status_code == 200 and conversation_id, r.text[:140])
        r = client.get(
            f"/api/chat/conversations/{chat_conversation_id}",
            headers=demo_headers,
        )
        check(
            "chat.transcript",
            r.status_code == 200 and bool(r.json().get("messages")),
            r.text[:140],
        )

        # ---------------------------------------------------------------- voice
        r = client.get("/api/voice/config", headers=demo_headers)
        vcfg = r.json() if r.status_code == 200 else {}
        check(
            "voice.config",
            r.status_code == 200 and vcfg.get("tts_provider") and "styles" in vcfg,
            r.text[:200],
        )
        r = client.post(
            "/api/voice/speak",
            headers=demo_headers,
            json={"text": "أهلأ، أنا مورس.", "style": "happy"},
        )
        spoken = r.json() if r.status_code == 200 else {}
        check(
            "voice.speak",
            r.status_code == 200
            and spoken.get("provider") == "browser"
            and float(spoken.get("rate", 0)) >= 1.0,
            r.text[:200],
        )
        r = client.post("/api/voice/speak", headers=demo_headers, json={"text": "   "})
        check("voice.speak_blank_422", r.status_code == 422, f"status={r.status_code}")
        r = client.post(
            "/api/voice/speak",
            headers=demo_headers,
            json={"text": "أهلاً", "style": "zombie"},
        )
        check("voice.bad_style_422", r.status_code == 422, f"status={r.status_code}")
        r = client.post(
            "/api/voice/stt",
            headers=demo_headers,
            files={"audio": ("q.wav", b"RIFF0000WAVEfake", "audio/wav")},
        )
        vstt = r.json() if r.status_code == 200 else {}
        check(
            "voice.stt_browser_local",
            r.status_code == 200
            and vstt.get("provider") == "browser"
            and vstt.get("available") is False,
            r.text[:200],
        )
        r = client.patch(
            "/api/auth/settings",
            headers=demo_headers,
            json={"voice_enabled": False, "tts_voice": "ar", "stt_provider": "browser"},
        )
        check(
            "voice.settings_persist",
            r.status_code == 200 and r.json()["settings"]["tts_voice"] == "ar",
            r.text[:200],
        )
        r = client.get("/api/voice/config", headers=demo_headers)
        check(
            "voice.settings_reflected",
            r.json().get("user", {}).get("tts_voice") == "ar"
            and r.json().get("user", {}).get("voice_enabled") is False,
            r.text[:200],
        )
        client.patch(
            "/api/auth/settings",
            headers=demo_headers,
            json={"voice_enabled": True, "tts_voice": "system", "stt_provider": "browser"},
        )

        # ------------------------------------------------------------ progress
        r = client.get("/api/progress/home", headers=demo_headers)
        check("progress.home", r.status_code == 200, r.text[:160])
        r = client.get("/api/progress/report", headers=demo_headers)
        check("progress.report", r.status_code == 200, r.text[:160])
        r = client.get("/api/progress/week", headers=demo_headers)
        check("progress.week", r.status_code == 200, r.text[:120])
        r = client.get("/api/progress/weak", headers=demo_headers)
        check("progress.weak", r.status_code == 200, r.text[:160])
        r = client.get("/api/progress/streak", headers=demo_headers)
        check("progress.streak", r.status_code == 200 and "current" in r.json(), r.text[:120])
        r = client.get("/api/progress/achievements", headers=demo_headers)
        check("progress.achievements", r.status_code == 200 and len(r.json().get("achievements", [])) >= 10, r.text[:160])
        r = client.get("/api/progress/mastery", headers=demo_headers)
        check("progress.mastery", r.status_code == 200, r.text[:120])
        r = client.get("/api/progress/coach/daily", headers=demo_headers, params={"deliver": "false"})
        check("progress.coach_daily", r.status_code == 200, r.text[:200])
        r = client.get("/api/progress/coach/actions", headers=demo_headers)
        check("progress.coach_actions", r.status_code == 200, r.text[:160])

        # --------------------------------------------------------------- inbox
        r = client.get("/api/inbox/notifications", headers=demo_headers)
        check("inbox.notifications", r.status_code == 200, f"{len(r.json().get('notifications', []))} rows")
        r = client.get("/api/inbox/mors/state", headers=demo_headers)
        check("inbox.mors_state", r.status_code == 200, r.text[:160])
        r = client.get("/api/inbox/mors/messages", headers=demo_headers)
        check("inbox.mors_messages", r.status_code == 200, r.text[:200])
        r = client.get("/api/inbox/delivery-policy", headers=demo_headers)
        check("inbox.delivery_policy", r.status_code == 200, r.text[:160])

        # ------------------------------------------------------------- library
        r = client.post(
            "/api/library/notes",
            headers=demo_headers,
            json={"title": "ملخص المتتاليات", "body": "الفرق المشترك ثابت.", "lesson_id": lesson_id},
        )
        check("library.create_note", r.status_code == 200 and r.json().get("id"), r.text[:200])
        note_id = r.json()["id"]
        r = client.get("/api/library/notes", headers=demo_headers, params={"q": "المتتاليات"})
        check("library.search_notes", r.status_code == 200 and r.json().get("notes"), r.text[:200])
        r = client.patch(f"/api/library/notes/{note_id}", headers=demo_headers, json={"pinned": True})
        check("library.pin_note", r.status_code == 200, r.text[:120])

        r = client.post(
            "/api/library/summaries",
            headers=demo_headers,
            json={"lesson_id": lesson_id, "kind": "quick", "use_ai": False},
        )
        check("library.summary", r.status_code == 200 and r.json().get("body"), r.text[:200])

        r = client.post(
            "/api/library/flashcards/generate",
            headers=demo_headers,
            json={"lesson_id": lesson_id, "count": 6, "use_ai": False},
        )
        cards = r.json().get("cards", []) if r.status_code == 200 else []
        check("library.flashcards", r.status_code == 200 and cards, r.text[:200])

        if cards:
            r = client.post(
                f"/api/library/flashcards/{cards[0]['id']}/review",
                headers=demo_headers,
                json={"quality": 4},
            )
            check("library.review_card", r.status_code == 200, r.text[:200])

        r = client.get("/api/library/flashcards/due", headers=demo_headers)
        check("library.due_cards", r.status_code == 200, r.text[:160])

        r = client.post(
            "/api/library/papers",
            headers=demo_headers,
            json={"title": "ورقة عمل المتتاليات", "kind": "worksheet", "lesson_id": lesson_id},
        )
        check("library.create_paper", r.status_code == 200 and r.json().get("id"), r.text[:200])
        paper_id = r.json()["id"]

        r = client.get(f"/api/library/papers/{paper_id}", headers=demo_headers)
        paper = r.json() if r.status_code == 200 else {}
        check("library.get_paper", r.status_code == 200 and paper.get("pages"), r.text[:200])
        page_id = (paper.get("pages") or [{}])[0].get("id")
        if page_id:
            r = client.put(
                f"/api/library/pages/{page_id}/blocks",
                headers=demo_headers,
                json={"blocks": [{"type": "heading", "content": {"text": "العنوان"}}]},
            )
            check("library.save_blocks", r.status_code == 200, r.text[:200])

        r = client.post(
            "/api/library/papers/generate",
            headers=demo_headers,
            json={"lesson_id": lesson_id, "kind": "worksheet", "use_ai": False},
        )
        check("library.generate_paper", r.status_code == 200, r.text[:240])

        # --------------------------------------------------------------- media
        r = client.post(
            "/api/media/uploads",
            headers=demo_headers,
            files={"file": ("notes.txt", "المتتالية الحسابية فرق مشترك ثابت".encode("utf-8"), "text/plain")},
            data={"subject_id": subjects[0]["id"], "kind": "notes"},
        )
        check("media.upload", r.status_code == 200, r.text[:240])
        upload_id = r.json().get("id") if r.status_code == 200 else None

        r = client.get("/api/media/uploads", headers=demo_headers)
        check("media.list_uploads", r.status_code == 200, r.text[:200])

        r = client.get("/api/media/search", headers=demo_headers, params={"q": "المتتاليات"})
        check("media.search", r.status_code == 200, r.text[:240])

        r = client.get("/api/media/teachers")
        check("media.teachers", r.status_code == 200 and r.json().get("teachers"), r.text[:160])
        r = client.get("/api/media/courses", headers=demo_headers)
        courses = r.json().get("courses", []) if r.status_code == 200 else []
        check("media.courses", r.status_code == 200 and courses, r.text[:160])
        r = client.get("/api/media/videos", headers=demo_headers)
        videos = r.json().get("videos", []) if r.status_code == 200 else []
        check("media.videos", r.status_code == 200 and videos, r.text[:200])
        report_id = ""
        if videos:
            r = client.post(
                f"/api/media/videos/{videos[0]['id']}/progress",
                headers=demo_headers,
                json={"position": 120, "watched_seconds": 120, "key_idea": "الفرق المشترك ثابت"},
            )
            check("media.video_progress", r.status_code == 200, r.text[:200])

            vid = videos[0]["id"]
            r = client.get(f"/api/media/videos/{vid}", headers=demo_headers)
            detail = r.json() if r.status_code == 200 else {}
            check(
                "media.video_detail",
                r.status_code == 200
                and all(k in detail for k in ("status", "progress", "prev", "next", "course")),
                r.text[:200],
            )

            r = client.get("/api/media/continue", headers=demo_headers)
            check(
                "media.continue",
                r.status_code == 200 and "video" in r.json(),
                r.text[:200],
            )

            course_id = next((c["id"] for c in courses if c.get("video_count")), "")
            if course_id:
                r = client.get(f"/api/media/courses/{course_id}", headers=demo_headers)
                payload = r.json() if r.status_code == 200 else {}
                check(
                    "media.course_progress",
                    r.status_code == 200
                    and payload.get("modules")
                    and 0 <= float(payload.get("progress_percent", -1)) <= 100,
                    r.text[:200],
                )
            else:
                check("media.course_progress", False, "no course with videos")

            r = client.post(
                f"/api/media/videos/{vid}/report",
                headers=demo_headers,
                json={"kind": "not_working", "detail": "الرابط يفتح صفحة محذوفة"},
            )
            report_id = r.json().get("report_id", "") if r.status_code == 200 else ""
            check("media.content_report", r.status_code == 200 and report_id, r.text[:200])

            r = client.post(
                f"/api/media/videos/{vid}/report",
                headers=demo_headers,
                json={"kind": "hacked"},
            )
            check("media.report_kind_validation", r.status_code == 422, f"status={r.status_code}")

            # §40 gate: pass closes the lesson, a fail keeps it open
            target = next((v for v in videos if v.get("status") != "completed"), videos[0])
            r = client.post(f"/api/media/videos/{target['id']}/quiz", headers=demo_headers)
            gate = r.json() if r.status_code == 200 else {}
            check("media.video_quiz_start", r.status_code == 200 and gate.get("quiz_id"), r.text[:200])
            if gate.get("quiz_id"):
                accuracy = _finish_video_quiz(client, demo_headers, gate["quiz_id"], correct=True)
                check("media.video_quiz_pass", accuracy is not None and accuracy >= 60, str(accuracy))
                r = client.get(f"/api/media/videos/{target['id']}", headers=demo_headers)
                state = r.json().get("status") if r.status_code == 200 else ""
                check("media.video_completed_after_pass", state == "completed", str(state))

                target2 = next(
                    (v for v in videos if v["id"] != target["id"] and v.get("status") != "quiz_failed"),
                    None,
                )
                if target2:
                    r = client.post(f"/api/media/videos/{target2['id']}/quiz", headers=demo_headers)
                    gate2 = r.json() if r.status_code == 200 else {}
                    if gate2.get("quiz_id"):
                        accuracy2 = _finish_video_quiz(
                            client, demo_headers, gate2["quiz_id"], correct=False
                        )
                        check("media.video_quiz_fail", accuracy2 is not None and accuracy2 < 60, str(accuracy2))
                        r = client.get(f"/api/media/videos/{target2['id']}", headers=demo_headers)
                        state2 = r.json().get("status") if r.status_code == 200 else ""
                        check("media.video_stays_open_on_fail", state2 == "quiz_failed", str(state2))
                    else:
                        check("media.video_quiz_fail", False, r.text[:160])
                else:
                    check("media.video_stays_open_on_fail", False, "no second video")
            else:
                check("media.video_completed_after_pass", False, r.text[:160])
        r = client.get("/api/media/videos-search", headers=demo_headers, params={"q": "الفرق المشترك"})
        check("media.transcript_search", r.status_code == 200, r.text[:240])

        # -------------------------------------------------------------- export
        r = client.get("/api/progress/export/json", headers=demo_headers)
        body = r.json() if r.status_code == 200 else {}
        check(
            "export.json",
            r.status_code == 200 and "progress" in body and "plans" in body,
            r.text[:160],
        )
        r = client.get("/api/progress/export/ics", headers=demo_headers)
        check("export.ics", r.status_code == 200 and "BEGIN:VCALENDAR" in r.text[:200], r.text[:80])
        r = client.get("/api/progress/export/pdf", headers=demo_headers)
        check("export.pdf", r.status_code == 200 and r.content[:5] == b"%PDF-", str(r.content[:16]))

        # --------------------------------------------------------------- admin
        r = client.post("/api/auth/login", json={"identifier": "admin@mors.ai", "password": "DemoPass123!"})
        check("admin.login", r.status_code == 200, r.text[:140])
        admin_headers = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}

        # --------------------------------------------- content review queue
        r = client.get("/api/admin/content-reports", headers=admin_headers)
        queue = r.json() if r.status_code == 200 else {}
        check(
            "admin.content_reports",
            r.status_code == 200 and isinstance(queue.get("reports"), list),
            r.text[:200],
        )
        if report_id:
            mine = next((x for x in queue.get("reports", []) if x["id"] == report_id), None)
            check(
                "admin.content_report_visible",
                mine is not None and mine.get("kind") == "not_working" and mine.get("status") == "open",
                str(bool(mine)),
            )
            r = client.post(f"/api/admin/content-reports/{report_id}/resolve", headers=admin_headers)
            check(
                "admin.content_report_resolve",
                r.status_code == 200 and r.json().get("status") == "resolved",
                r.text[:200],
            )
            r = client.get(
                "/api/admin/content-reports", headers=admin_headers, params={"status": "open"}
            )
            check(
                "admin.content_report_left_open_queue",
                all(x["id"] != report_id for x in r.json().get("reports", [])),
            )
            r = client.get("/api/admin/content-reports", headers=demo_headers)
            check("admin.content_reports_student_forbidden", r.status_code == 403, f"status={r.status_code}")
        else:
            check("admin.content_report_visible", False, "no report was created")

        # ---------------------------------------------------- question bank
        bank_question = {
            "prompt": "ما ناتج ضرب ٦ في ٤ من جدول الضرب؟",
            "options": ["24", "22", "26", "20"],
            "answer_index": 0,
            "explanation": "٦ × ٤ = ٢٤.",
            "difficulty": 1,
            "topic": "الضرب",
            "subject_id": subject["id"],
            "source_kind": "ai",
        }
        r = client.post("/api/exams/bank", headers=admin_headers, json=bank_question)
        created = r.json() if r.status_code == 200 else {}
        check("bank.add", r.status_code == 200 and created.get("status") == "validated", r.text[:200])

        r = client.post("/api/exams/bank", headers=admin_headers, json=bank_question)
        check("bank.duplicate_rejected", r.status_code == 422, str(r.status_code))

        r = client.post(
            f"/api/exams/bank/{created.get('id', '')}/validate", headers=admin_headers
        )
        check("bank.validate", r.status_code == 200 and r.json().get("valid") is True, r.text[:200])

        r = client.get("/api/exams/bank", headers=admin_headers, params={"q": "جدول الضرب"})
        listed = r.json() if r.status_code == 200 else {}
        check(
            "bank.list_filters",
            r.status_code == 200 and listed.get("total", 0) >= 1 and "stats" in listed,
            r.text[:200],
        )
        check(
            "bank.hides_correct_flag",
            all("correct" not in item for item in listed.get("items", [])),
            "",
        )

        r = client.get("/api/admin/prompts", headers=admin_headers)
        check("admin.prompts", r.status_code == 200 and r.json().get("prompts"), r.text[:200])
        prompts = r.json().get("prompts") or []
        first_key = prompts[0].get("key") if prompts else None
        if first_key:
            original = prompts[0].get("template", "")
            r = client.put(
                f"/api/admin/prompts/{first_key}",
                headers=admin_headers,
                json={"template": original + "\n# تعديل تجريبي من الاختبار"},
            )
            check("admin.update_prompt", r.status_code == 200, r.text[:200])
            r = client.delete(f"/api/admin/prompts/{first_key}", headers=admin_headers)
            check("admin.reset_prompt", r.status_code == 200, r.text[:200])

        r = client.get("/api/admin/stats", headers=admin_headers)
        check("admin.stats", r.status_code == 200, r.text[:200])
        r = client.get("/api/admin/usage", headers=admin_headers)
        check("admin.usage", r.status_code == 200, r.text[:200])
        r = client.get("/api/admin/events", headers=admin_headers)
        check("admin.events", r.status_code == 200, r.text[:200])
        r = client.get("/api/admin/users", headers=admin_headers)
        check("admin.users", r.status_code == 200 and r.json().get("users"), r.text[:200])
        r = client.put("/api/admin/settings/theme", headers=admin_headers, json={"value": "dark"})
        check("admin.put_setting", r.status_code == 200, r.text[:200])
        r = client.get("/api/admin/settings/theme", headers=admin_headers)
        check("admin.get_setting", r.status_code == 200 and r.json().get("value") == "dark", r.text[:200])

        # ------------------------------------- publishing pipeline (§83)
        r = client.post(
            "/api/admin/drafts",
            headers=admin_headers,
            json={"entity": "lesson", "payload": {"subject_id": subject["id"], "title": "درس الدخان"}},
        )
        draft = r.json() if r.status_code == 200 else {}
        check("draft.create", r.status_code == 200 and draft.get("status") == "draft", r.text[:200])
        r = client.post(f"/api/admin/drafts/{draft.get('id', '')}/process", headers=admin_headers)
        processed = r.json() if r.status_code == 200 else {}
        check(
            "draft.process",
            processed.get("status") == "validated" and bool(processed.get("ai_notes")),
            r.text[:200],
        )
        r = client.post(
            f"/api/admin/drafts/{draft.get('id', '')}/review",
            headers=admin_headers,
            json={"approve": True, "note": "نشر مباشر"},
        )
        published = r.json() if r.status_code == 200 else {}
        check(
            "draft.publish",
            published.get("status") == "published" and published.get("entity_id"),
            r.text[:200],
        )
        r = client.get(
            "/api/admin/drafts", headers=admin_headers, params={"status": "published", "q": "الدخان"}
        )
        check(
            "draft.list",
            r.status_code == 200
            and any(d.get("id") == draft.get("id") for d in r.json().get("drafts", [])),
            r.text[:200],
        )
        r = client.delete(f"/api/admin/drafts/{draft.get('id', '')}", headers=admin_headers)
        check("draft.delete_published_blocked", r.status_code == 422, str(r.status_code))
        r = client.get("/api/admin/drafts", headers=demo_headers)
        check("draft.student_forbidden", r.status_code == 403, str(r.status_code))

        # ------------------------------ scheduled publishing (§83) + job (§126)
        from datetime import datetime, timedelta, timezone

        r = client.post(
            "/api/admin/drafts",
            headers=admin_headers,
            json={"entity": "lesson", "payload": {"subject_id": subject["id"], "title": "درس مجدول"}},
        )
        sdraft = r.json() if r.status_code == 200 else {}
        check("draft.scheduled_create", r.status_code == 200, r.text[:160])
        client.post(f"/api/admin/drafts/{sdraft.get('id', '')}/process", headers=admin_headers)
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        r = client.post(
            f"/api/admin/drafts/{sdraft.get('id', '')}/review",
            headers=admin_headers,
            json={"approve": True, "publish_at": future},
        )
        check(
            "draft.scheduled_review",
            r.status_code == 200
            and r.json().get("status") == "scheduled"
            and not r.json().get("entity_id"),
            r.text[:200],
        )
        r = client.post("/api/admin/scheduler/publish_due_content/run", headers=admin_headers)
        check(
            "scheduler.skips_future_draft",
            r.status_code == 200
            and "درس مجدول" not in r.json().get("detail", {}).get("published", []),
            r.text[:200],
        )
        from app.db import ContentDraft as ContentDraftModel, SessionLocal as _SL, utcnow as _utc

        dbx = _SL()
        try:
            rowx = dbx.get(ContentDraftModel, sdraft.get("id"))
            rowx.publish_at = _utc() - timedelta(minutes=1)
            dbx.commit()
        finally:
            dbx.close()
        r = client.post("/api/admin/scheduler/publish_due_content/run", headers=admin_headers)
        check(
            "scheduler.publishes_due_draft",
            r.status_code == 200
            and "درس مجدول" in r.json().get("detail", {}).get("published", []),
            r.text[:200],
        )

        # ------------------------------------------------ scheduler admin API
        r = client.get("/api/admin/scheduler", headers=admin_headers)
        check(
            "scheduler.status",
            r.status_code == 200 and len(r.json().get("jobs", [])) == 3,
            r.text[:200],
        )
        r = client.post("/api/admin/scheduler/prune_rate_counters/run", headers=admin_headers)
        check("scheduler.run", r.status_code == 200 and r.json().get("status") == "ok", r.text[:200])
        r = client.post("/api/admin/scheduler/no_such_job/run", headers=admin_headers)
        check("scheduler.unknown_404", r.status_code == 404, str(r.status_code))

        # ---------------------------------------------- auth rules / errors
        client.cookies.clear()
        r = client.get("/api/progress/home")
        check("auth.required_401", r.status_code == 401, r.text[:120])
        r = client.get("/api/admin/stats", headers=demo_headers)
        check("admin.forbidden_403", r.status_code == 403, r.text[:140])
        r = client.get("/api/curriculum/lessons/nope")
        check("error.404_shape", r.status_code == 404 and "error" in r.json(), r.text[:140])

        # ----------------------------------------- account deletion (§128)
        r = client.post(
            "/api/auth/register",
            json={
                "full_name": "طالب الحذف",
                "email": "del-smoke@mors.ai",
                "password": "Delete1234!",
            },
        )
        del_headers = (
            {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
            if r.status_code == 200
            else {}
        )
        check("account.register_for_delete", r.status_code == 200, r.text[:140])
        r = client.request(
            "DELETE", "/api/auth/account", headers=del_headers, json={"password": "nope"}
        )
        check("account.delete_wrong_password", r.status_code == 401, f"status={r.status_code}")
        r = client.request(
            "DELETE", "/api/auth/account", headers=del_headers, json={"password": "Delete1234!"}
        )
        check(
            "account.delete_ok",
            r.status_code == 200 and r.json().get("deleted") is True,
            r.text[:140],
        )
        r = client.post(
            "/api/auth/login",
            json={"identifier": "del-smoke@mors.ai", "password": "Delete1234!"},
        )
        check("account.deleted_login_fails", r.status_code == 401, f"status={r.status_code}")
        r = client.request(
            "DELETE", "/api/auth/account", headers=admin_headers, json={"password": "DemoPass123!"}
        )
        check("account.sealed_admin", r.status_code == 422, f"status={r.status_code}")

        # ------------------------------------------------------ mors tone guard
        r = client.get("/api/inbox/mors/messages", headers=demo_headers, params={"limit": 20})
        texts = " ".join(str(m.get("text", "")) for m in r.json().get("messages", []))
        banned = ["تستاهل", "غبي", "خبل", "كسلان"]
        check("mors.no_banned_words", not any(b in texts for b in banned), texts[:200])
        check("mors.no_placeholder", "{" not in texts and "}" not in texts, texts[:200])

    failed = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    if failed:
        print("FAILURES:")
        for name, _, detail in failed:
            print(f"  - {name}: {detail}")
    return 1 if failed else 0


def _quiz_answers(client, headers: dict[str, str], quiz_id: str) -> list[tuple[str, str]]:
    """Read the quiz with its answer key (students only ever see `correct: False`)."""
    from app.db import Quiz as QuizModel, SessionLocal

    db = SessionLocal()
    try:
        row = db.get(QuizModel, quiz_id)
        out: list[tuple[str, str]] = []
        for question in row.questions:
            correct = [o for o in question.options if o.is_correct]
            if correct:
                answer = correct[0].id  # mcq grading matches the option id
            else:
                answer = question.answer_key or ""
            out.append((question.id, answer))
        return out
    finally:
        db.close()


def _quiz_wrong_answers(quiz_id: str) -> list[tuple[str, str]]:
    """Deliberately wrong answers (a non-correct option, or junk for text inputs)."""
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


def _finish_video_quiz(
    client, headers: dict[str, str], quiz_id: str, *, correct: bool
) -> float | None:
    """Start → answer (right or wrong) → finish; return accuracy or None."""
    started = client.post(f"/api/quiz/{quiz_id}/start", headers=headers)
    if started.status_code != 200:
        return None
    attempt_id = started.json()["attempt_id"]
    answers = _quiz_answers(client, headers, quiz_id) if correct else _quiz_wrong_answers(quiz_id)
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


def _soon(days: int) -> str:
    from datetime import date, timedelta

    return (date.today() + timedelta(days=days)).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
