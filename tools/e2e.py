"""End-to-end smoke: boots backend (uvicorn) + frontend (next start), then hits pages."""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
FE_PORT = int(os.environ.get("FE_PORT", "3111"))
BE_PORT = int(os.environ.get("BE_PORT", "8111"))
BASE = f"http://127.0.0.1:{FE_PORT}"
API = f"http://127.0.0.1:{BE_PORT}"

FAILURES = []
PASSES = 0


def ok(cond, label, detail=""):
    global PASSES
    if cond:
        PASSES += 1
        print(f"[OK ] {label}")
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label} {detail}")


def wait_http(url, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.7)
    return False


def get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def post_json(url, payload, headers=None, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def post_multipart(url, files, headers=None, timeout=60):
    """files: {field: (filename, bytes, content_type)}"""
    boundary = "morsBoundary123"
    parts = []
    for name, (fname, content, mime) in files.items():
        parts.append(
            (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode("utf-8")
            + content
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    hdrs = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        **(headers or {}),
    }
    req = urllib.request.Request(url, data=b"".join(parts), headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def page(path, label=None):
    status, body = get(BASE + path)
    label = label or f"page {path}"
    bad = ("Unhandled Runtime Error" in body) or ("__NEXT_ERROR__" in body)
    ok(status == 200 and not bad, label, f"status={status} bad={bad}")
    return body


def main():
    logdir = ROOT / "tools" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    be_log = open(logdir / "e2e_backend.log", "w", encoding="utf-8")
    fe_log = open(logdir / "e2e_frontend.log", "w", encoding="utf-8")

    env = dict(os.environ)
    env.setdefault("DEMO_DATA", "true")
    env.setdefault("AI_PROVIDER", "mock")
    env.setdefault("APP_ENV", "development")
    env.setdefault("RATE_LIMIT_PER_MINUTE", "600")
    env.setdefault("AI_RATE_LIMIT_PER_MINUTE", "180")
    env["PYTHONUTF8"] = "1"

    procs = []
    try:
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(BE_PORT), "--log-level", "warning"],
            cwd=str(BACKEND), env=env, stdout=be_log, stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen(
            ["node", str(FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"), "start", "-p", str(FE_PORT)],
            cwd=str(FRONTEND), env=env, stdout=fe_log, stderr=subprocess.STDOUT))

        ok(wait_http(f"{API}/health"), "backend /health up")
        ok(wait_http(f"{BASE}/login"), "frontend up")

        page("/")
        for path in ["/login", "/onboarding", "/home", "/plan", "/study", "/chat",
                     "/library", "/notes", "/papers", "/progress", "/settings",
                     "/admin", "/videos", "/inbox", "/exams", "/advisor"]:
            page(path)

        st, txt = post_json(f"{API}/api/auth/login",
                            {"identifier": "demo@mors.ai", "password": "DemoPass123!"})
        ok(st == 200, "login demo", f"status={st} {txt[:160]}")
        tok = ""
        try:
            tok = json.loads(txt).get("tokens", {}).get("access_token", "")
        except Exception:
            pass
        ok(bool(tok), "access token issued")
        hdr = {"Authorization": f"Bearer {tok}"}

        st, txt = get(f"{API}/api/auth/settings", headers=hdr)
        ok(st == 200, "GET /api/auth/settings", f"status={st} {txt[:160]}")

        st, txt = get(f"{API}/api/curriculum/subjects", headers=hdr)
        ok(st == 200, "curriculum subjects", f"status={st}")
        lesson_id = ""
        subject_id = ""
        try:
            subs = json.loads(txt).get("subjects") or []
            subject_id = str((subs[0] if subs else {}).get("id") or "")
        except Exception:
            pass
        if subject_id:
            st, txt = get(f"{API}/api/curriculum/subjects/{subject_id}/tree", headers=hdr)
            ok(st == 200, "curriculum subject tree", f"status={st}")
            try:
                for ch in json.loads(txt).get("chapters") or []:
                    for unit in ch.get("units") or []:
                        for les in unit.get("lessons") or []:
                            lesson_id = str(les.get("id") or "")
                            if lesson_id:
                                break
                        if lesson_id:
                            break
                    if lesson_id:
                        break
            except Exception:
                pass
        ok(bool(lesson_id), "lesson id found", f"id={lesson_id!r} subject={subject_id!r}")
        if lesson_id:
            page(f"/lessons/{lesson_id}", f"page /lessons/{lesson_id}")

        # books: API + reader page
        st, txt = get(f"{API}/api/books", headers=hdr)
        books = []
        if st == 200:
            try:
                books = json.loads(txt).get("books") or []
            except Exception:
                books = []
        ok(st == 200 and books, "books list", f"status={st} count={len(books)}")
        if books:
            book_id = books[0]["id"]
            st, txt = get(f"{API}/api/books/{book_id}", headers=hdr)
            ok(st == 200, "book detail", f"status={st}")
            st, txt = get(f"{API}/api/books/{book_id}/page", headers=hdr, timeout=30)
            ok(st == 200, "book page 1", f"status={st}")
            page(f"/books/{book_id}", f"page /books/{book_id}")

        st, txt = post_json(f"{API}/api/quiz/generate",
                            {"lesson_id": lesson_id or None, "subject_id": subject_id or None,
                             "kind": "practice", "count": 5}, hdr)
        ok(st in (200, 201), "quiz generate", f"status={st} {txt[:200]}")
        quiz_id = ""
        try:
            quiz_id = str(json.loads(txt).get("id") or "")
        except Exception:
            pass
        if quiz_id:
            st2, txt2 = post_json(f"{API}/api/quiz/{quiz_id}/start", {}, hdr)
            ok(st2 in (200, 201), "quiz start", f"status={st2} {txt2[:160]}")
            page(f"/quiz/{quiz_id}", f"page /quiz/{quiz_id}")
        else:
            ok(False, "quiz id found", txt[:200])

        st, txt = post_json(f"{API}/api/chat/messages", {"message": "أهلاً", "mode": "explain"}, hdr)
        ok(st in (200, 201), "chat message", f"status={st} {txt[:200]}")

        # voice (§15/§70): config → speak tone → validation → local STT
        st, txt = get(f"{API}/api/voice/config", headers=hdr)
        ok(st == 200 and "tts_provider" in txt, "voice config", f"status={st} {txt[:160]}")
        st, txt = post_json(
            f"{API}/api/voice/speak", {"text": "أهلأ يا طالب", "style": "proud"}, hdr
        )
        ok(st == 200 and "rate" in txt, "voice speak", f"status={st} {txt[:160]}")
        st, _blank = post_json(f"{API}/api/voice/speak", {"text": " "}, hdr)
        ok(st == 422, "voice speak validates blank", f"status={st}")
        st, txt = post_multipart(
            f"{API}/api/voice/stt",
            {"audio": ("q.wav", b"RIFF0000WAVEfake", "audio/wav")},
            hdr,
        )
        ok(st == 200 and "browser" in txt, "voice stt stays local", f"status={st} {txt[:160]}")

        # exams: overview → build → timed session → analysis page
        st, txt = get(f"{API}/api/exams", headers=hdr)
        ok(st == 200, "exams overview", f"status={st} {txt[:160]}")

        st, txt = post_json(f"{API}/api/exams/generate",
                            {"subject_id": subject_id or None, "count": 6,
                             "duration_minutes": 15, "kind": "mock"}, hdr)
        ok(st in (200, 201), "exam generate", f"status={st} {txt[:200]}")
        exam_quiz = {}
        try:
            exam_quiz = json.loads(txt)
        except Exception:
            exam_quiz = {}
        if exam_quiz.get("id") and exam_quiz.get("question_count"):
            st, txt = post_json(f"{API}/api/exams/start",
                                {"quiz_id": exam_quiz["id"], "mode": "mock"}, hdr)
            ok(st in (200, 201), "exam start with timer", f"status={st} {txt[:200]}")
            session = {}
            try:
                session = json.loads(txt)
            except Exception:
                session = {}
            exam_attempt = str(session.get("exam_attempt_id") or "")
            questions = session.get("questions") or []
            if exam_attempt and questions:
                page(f"/exam/{exam_attempt}", f"page /exam/{exam_attempt}")
                first = questions[0]
                st, txt = post_json(
                    f"{API}/api/exams/attempts/{exam_attempt}/answer",
                    {"question_id": first["id"], "answer": first["options"][0]["id"]}, hdr)
                ok(st == 200 and "correct" not in txt, "exam answer hides grading",
                   f"status={st} {txt[:160]}")
                st, txt = post_json(f"{API}/api/exams/attempts/{exam_attempt}/mark",
                                    {"question_id": first["id"]}, hdr)
                ok(st == 200, "exam mark for review", f"status={st}")
                st, txt = post_json(f"{API}/api/exams/attempts/{exam_attempt}/submit", {}, hdr)
                body = {}
                try:
                    body = json.loads(txt)
                except Exception:
                    body = {}
                ok(st == 200 and "by_difficulty" in body and "readiness" in body,
                   "exam submit → analysis", f"status={st} {txt[:200]}")
                page(f"/exam/{exam_attempt}", f"page /exam/{exam_attempt} (report)")
            else:
                ok(False, "exam session started", txt[:200])
        else:
            ok(False, "exam quiz built", txt[:200])

        st, txt = get(f"{API}/api/exams/mistakes", headers=hdr)
        ok(st == 200, "mistake book lists errors", f"status={st} {txt[:160]}")
        st, txt = get(f"{API}/api/exams/readiness", headers=hdr)
        ok(st == 200 and "factors" in txt, "readiness factors", f"status={st}")

        # advisor: overview → report → weekly → steps → apply
        st, txt = get(f"{API}/api/advisor", headers=hdr)
        ok(st == 200, "advisor overview", f"status={st} {txt[:160]}")
        advisor = {}
        try:
            advisor = json.loads(txt)
        except Exception:
            advisor = {}
        ok(
            all(k in advisor for k in ("context", "report", "weekly", "steps", "priorities", "plan_health")),
            "advisor payload complete",
            ",".join(sorted(advisor.keys()))[:120],
        )
        problems = (advisor.get("report") or {}).get("problems") or []
        ok(
            all(p.get("solution") and p.get("action_key") for p in problems),
            "every problem carries a solution",
            f"n={len(problems)}",
        )
        st, txt = get(f"{API}/api/advisor/weekly", headers=hdr)
        weekly = {}
        try:
            weekly = json.loads(txt)
        except Exception:
            weekly = {}
        ok(st == 200 and bool(weekly.get("next_week_plan")), "advisor weekly plan", f"status={st}")
        st, txt = get(f"{API}/api/advisor/steps", headers=hdr)
        steps = []
        try:
            steps = json.loads(txt).get("steps") or []
        except Exception:
            steps = []
        ok(st == 200 and len(steps) >= 5, "advisor steps listed", f"n={len(steps)}")
        st, txt = post_json(f"{API}/api/advisor/steps/add_session/apply", {}, hdr)
        ok(st == 200 and "event_id" in txt, "advisor apply add_session", f"status={st} {txt[:160]}")
        st, txt = post_json(f"{API}/api/advisor/steps/add_quiz/apply", {}, hdr)
        ok(st == 200 and "/quiz/" in txt, "advisor apply add_quiz", f"status={st} {txt[:160]}")
        st, txt = post_json(f"{API}/api/advisor/steps/nope/apply", {}, hdr)
        ok(st == 404, "advisor unknown step 404", f"status={st}")

        # videos & courses (P4): list → detail → progress → quiz gate → reports
        st, txt = get(f"{API}/api/media/videos", headers=hdr)
        videos = []
        if st == 200:
            try:
                videos = json.loads(txt).get("videos") or []
            except Exception:
                videos = []
        ok(st == 200 and videos, "media videos list", f"status={st} n={len(videos)}")

        st, txt = get(f"{API}/api/media/courses", headers=hdr)
        courses = []
        if st == 200:
            try:
                courses = json.loads(txt).get("courses") or []
            except Exception:
                courses = []
        ok(st == 200 and courses, "media courses list", f"status={st} n={len(courses)}")

        report_id = ""
        if videos:
            vid = videos[0]["id"]
            st, txt = get(f"{API}/api/media/videos/{vid}", headers=hdr)
            detail = {}
            try:
                detail = json.loads(txt)
            except Exception:
                detail = {}
            ok(
                st == 200
                and all(k in detail for k in ("status", "progress", "prev", "next", "course")),
                "video detail payload",
                f"status={st}",
            )
            page(f"/videos/{vid}", f"page /videos/{vid}")

            st, txt = post_json(
                f"{API}/api/media/videos/{vid}/progress",
                {"position": 45, "watched_seconds": 45, "key_idea": "خطوة بخطوة"},
                hdr,
            )
            ok(st == 200, "video progress saved", f"status={st} {txt[:160]}")

            st, txt = get(f"{API}/api/media/continue", headers=hdr)
            ok(st == 200 and "video" in txt, "continue watching", f"status={st}")

            st, txt = post_json(
                f"{API}/api/media/videos/{vid}/report",
                {"kind": "not_working", "detail": "الرابط يفتح صفحة محذوفة"},
                hdr,
            )
            if st == 200:
                try:
                    report_id = str(json.loads(txt).get("report_id") or "")
                except Exception:
                    report_id = ""
            ok(st == 200 and report_id, "content report created", f"status={st} {txt[:160]}")

            st, _bad = post_json(f"{API}/api/media/videos/{vid}/report", {"kind": "hacked"}, hdr)
            ok(st == 422, "content report kind validated", f"status={st}")

            st, txt = post_json(f"{API}/api/media/videos/{vid}/quiz", {}, hdr)
            quiz_vid = ""
            if st == 200:
                try:
                    quiz_vid = str(json.loads(txt).get("quiz_id") or "")
                except Exception:
                    quiz_vid = ""
            ok(st == 200 and quiz_vid, "video quiz generated", f"status={st} {txt[:160]}")
            if quiz_vid:
                page(f"/quiz/{quiz_vid}", f"page /quiz/{quiz_vid} (video gate)")
        else:
            ok(False, "videos available for P4 checks", txt[:200])

        if courses:
            course_id = next((c["id"] for c in courses if c.get("video_count")), "")
            if course_id:
                st, txt = get(f"{API}/api/media/courses/{course_id}", headers=hdr)
                ok(st == 200, "course progress payload", f"status={st} {txt[:160]}")
                page(f"/courses/{course_id}", f"page /courses/{course_id}")
            else:
                ok(False, "course with videos", "none of the courses has videos")

        # admin: review queue (§84) — student blocked, admin can resolve
        st, _deny = get(f"{API}/api/admin/content-reports", headers=hdr)
        ok(st == 403, "student blocked from review queue", f"status={st}")

        st, txt = post_json(
            f"{API}/api/auth/login",
            {"identifier": "admin@mors.ai", "password": "DemoPass123!"},
            {},
        )
        admin_tok = ""
        if st == 200:
            try:
                admin_tok = json.loads(txt).get("tokens", {}).get("access_token", "")
            except Exception:
                admin_tok = ""
        ok(bool(admin_tok), "admin login (review queue)", f"status={st}")
        if admin_tok:
            ahdr = {"Authorization": f"Bearer {admin_tok}"}
            st, txt = get(f"{API}/api/admin/content-reports", headers=ahdr)
            ok(st == 200, "admin content reports list", f"status={st}")
            if report_id:
                st, txt = post_json(
                    f"{API}/api/admin/content-reports/{report_id}/resolve", {}, ahdr
                )
                body = {}
                try:
                    body = json.loads(txt)
                except Exception:
                    body = {}
                ok(st == 200 and body.get("status") == "resolved", "admin resolve report",
                   f"status={st} {txt[:160]}")

        # publishing pipeline (§83) + background scheduler (§126) — P6
        st, txt = get(f"{API}/api/curriculum/subjects", headers=hdr)
        subjects = []
        if st == 200:
            try:
                subjects = json.loads(txt).get("subjects") or []
            except Exception:
                subjects = []
        ok(st == 200 and subjects, "subjects for publishing", f"n={len(subjects)}")
        if subjects and admin_tok:
            st, txt = post_json(
                f"{API}/api/admin/drafts",
                {"entity": "lesson", "payload": {"subject_id": subjects[0]["id"], "title": "درس E2E"}},
                ahdr,
            )
            draft_id = ""
            if st == 200:
                try:
                    draft_id = json.loads(txt).get("id", "")
                except Exception:
                    draft_id = ""
            ok(st == 200 and draft_id, "admin draft created", f"status={st} {txt[:160]}")

            st, txt = post_json(f"{API}/api/admin/drafts/{draft_id}/process", {}, ahdr)
            body = json.loads(txt) if st == 200 else {}
            ok(body.get("status") == "validated" and body.get("ai_notes"), "draft AI processing",
               f"status={st} {txt[:160]}")

            st, txt = post_json(
                f"{API}/api/admin/drafts/{draft_id}/review", {"approve": True, "note": "E2E"}, ahdr
            )
            body = json.loads(txt) if st == 200 else {}
            ok(body.get("status") == "published" and body.get("entity_id"), "draft published",
               f"status={st} {txt[:160]}")

            # a future-scheduled draft must stay untouched by the job
            st, txt = post_json(
                f"{API}/api/admin/drafts",
                {"entity": "lesson",
                 "payload": {"subject_id": subjects[0]["id"], "title": "درس مجدول E2E"}},
                ahdr,
            )
            s_id = ""
            if st == 200:
                try:
                    s_id = json.loads(txt).get("id", "")
                except Exception:
                    s_id = ""
            post_json(f"{API}/api/admin/drafts/{s_id}/process", {}, ahdr)
            st, txt = post_json(
                f"{API}/api/admin/drafts/{s_id}/review",
                {"approve": True, "publish_at": "2030-01-01T00:00:00Z"},
                ahdr,
            )
            body = json.loads(txt) if st == 200 else {}
            ok(body.get("status") == "scheduled" and not body.get("entity_id"),
               "draft scheduled for later", f"status={st} {txt[:160]}")

            st, txt = get(f"{API}/api/admin/scheduler", headers=ahdr)
            jobs = []
            if st == 200:
                try:
                    jobs = json.loads(txt).get("jobs") or []
                except Exception:
                    jobs = []
            ok(st == 200 and len(jobs) == 3, "scheduler jobs listed", f"n={len(jobs)}")

            st, txt = post_json(f"{API}/api/admin/scheduler/publish_due_content/run", {}, ahdr)
            body = json.loads(txt) if st == 200 else {}
            ok(st == 200 and body.get("status") == "ok"
               and "درس مجدول E2E" not in body.get("detail", {}).get("published", []),
               "job skips the future draft", f"status={st} {txt[:160]}")

            st, txt = post_json(f"{API}/api/admin/scheduler/no_such_job/run", {}, ahdr)
            ok(st == 404, "scheduler unknown job 404", f"status={st}")

            st, _deny = get(f"{API}/api/admin/drafts", headers=hdr)
            ok(st == 403, "student blocked from drafts", f"status={st}")

        print()
        print(f"RESULT {PASSES} passed, {len(FAILURES)} failed")
        if FAILURES:
            print("FAILED: " + ", ".join(FAILURES))
        return 1 if FAILURES else 0
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=8)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        be_log.close()
        fe_log.close()


if __name__ == "__main__":
    sys.exit(main())
