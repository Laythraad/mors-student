"""End-to-end smoke test for the service layer (no FastAPI, no frontend).

Run:  python -X utf8 tools/smoke_services.py
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

TEMP = Path(tempfile.gettempdir()) / "mors_smoke.db"
if TEMP.exists():
    TEMP.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP.as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["DEMO_DATA"] = "false"
os.environ["AI_PROVIDER"] = "mock"

from app.db import (  # noqa: E402
    Book,
    BookPage,
    Branch,
    Chapter,
    Lesson,
    Source,
    Stage,
    StudentProfile,
    Subject,
    Unit,
    init_db,
    SessionLocal,
)
from app.mors import assert_tone  # noqa: E402
from app.core.errors import NotFoundError, ValidationError  # noqa: E402
from app.services import (  # noqa: E402
    assessment,
    auth,
    bank as bank_service,
    exams as exams_service,
    planner,
    progress,
    sessions,
)

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    print(f"[{'OK ' if ok else 'FAIL'}] {name} {detail}")


def main() -> int:
    init_db()
    from app.mors.handlers import register_handlers

    register_handlers()
    db = SessionLocal()
    try:
        # ---- curriculum ------------------------------------------------
        stage = Stage(code="grade4", name_ar="الرابع العلمي")
        db.add(stage)
        db.flush()
        branch = Branch(stage_id=stage.id, code="science", name_ar="علمي")
        db.add(branch)
        db.flush()
        subject = Subject(branch_id=branch.id, code="MATH", name_ar="الرياضيات")
        db.add(subject)
        db.flush()
        source = Source(title="كتاب الرياضيات الرسمي", kind="book")
        db.add(source)
        db.flush()
        book = Book(subject_id=subject.id, title="كتاب الرياضيات")
        db.add(book)
        db.flush()
        chapter = Chapter(book_id=book.id, title="الفصل الأول", index=1)
        db.add(chapter)
        db.flush()
        unit = Unit(chapter_id=chapter.id, title="الوحدة الأولى", index=1)
        db.add(unit)
        db.flush()
        lesson = Lesson(
            unit_id=unit.id,
            chapter_id=chapter.id,
            subject_id=subject.id,
            title="المتتاليات الحسابية",
            summary="تعريف المتتالية الحسابية وخصائصها.",
            objectives=["يحدد الحد الأول", "يحسب الفرق المشترك", "يكتب قانون الحد العام"],
            keywords=["متتالية", "فرق مشترك", "الحد العام"],
            source_id=source.id,
            index=1,
        )
        db.add(lesson)
        db.flush()
        for number, heading in ((1, "تمهيد"), (2, "أمثلة محلولة"), (3, "تدريب")):
            db.add(
                BookPage(
                    book_id=book.id,
                    chapter_id=chapter.id,
                    unit_id=unit.id,
                    lesson_id=lesson.id,
                    page_number=number,
                    heading=heading,
                    text=f"{heading}: المتتالية الحسابية فرقها ثابت بين الحدود المتتالية.",
                    is_demo=True,
                )
            )
        book.page_count = 3
        db.commit()

        # ---- auth -------------------------------------------------------
        user = auth.register(
            db, full_name="أحمد الجبوري", email="ahmad@example.com", password="Sup3rSecret!"
        )
        db.commit()
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).one()
        auth.ensure_learning_profile(db, profile.id)
        auth.ensure_streak(db, profile.id)
        auth.set_subjects(db, profile, [subject.id])
        check("default_quiet_hours", inbox_quiet_default(db, profile.id) == (23, 7))
        profile.sleep_start = _time0()
        profile.sleep_end = _time0()
        db.flush()
        tokens = auth.issue_tokens(user)
        check("register+tokens", tokens.get("access_token", "").count(".") == 2)

        # ---- study session ---------------------------------------------
        session = sessions.start_session(
            db, profile.id, lesson_id=lesson.id, goal="فهم الفرق المشترك"
        )
        check("start_session", session.status == "active", session.title)
        sessions.heartbeat(db, profile.id, session.id, elapsed_seconds=60 * 38)
        result = sessions.end_session(
            db, profile.id, session.id, feedback="hard", understanding=0.4
        )
        check("end_session", result["ok"] and result["minutes"] == 38, str(result["minutes"]))
        check("session_mors", bool(result["mors"].get("expression")), str(result["mors"].get("scenario")))

        adaptive = sessions.adaptive_duration(db, profile.id)
        check("adaptive_duration", adaptive["recommended_minutes"] > 0, adaptive["reason"])

        # ---- quiz -------------------------------------------------------
        quiz = assessment.generate_quiz(
            db, profile.id, lesson_id=lesson.id, count=5, difficulty=3
        )
        check("generate_quiz", quiz["question_count"] == 5, str(quiz["question_count"]))
        check("quiz_hides_answers", "answer_key" not in quiz["questions"][0])

        from app.db import Quiz as QuizModel

        quiz_row = db.get(QuizModel, quiz["id"])
        with_answers = assessment.quiz_payload(db, quiz_row, include_answers=True)

        attempt = assessment.start_attempt(db, profile.id, quiz["id"])
        check("start_attempt", attempt.status == "in_progress")

        correct_ids = 0
        for index, question in enumerate(with_answers["questions"]):
            correct_id = next(o["id"] for o in question["options"] if o["correct"])
            if index % 2 == 0:
                answer = correct_id
                correct_ids += 1
            else:
                wrong = next((o["id"] for o in question["options"] if not o["correct"]), "wrong")
                answer = wrong
            outcome = assessment.submit_answer(
                db, profile.id, attempt.id, question["id"], answer, time_seconds=12
            )
            check(
                f"grade_q{index}",
                outcome["correct"] == (index % 2 == 0),
                str(outcome["correct"]),
            )

        report = assessment.finish_attempt(db, profile.id, attempt.id)
        check(
            "attempt_report",
            report["correct"] + report["wrong"] + report["skipped"] == 5,
            f"acc={report['accuracy']}",
        )

        # ---- exams: bank → simulation → analysis → readiness ------------
        bank_question = bank_service.add_question(
            db,
            {
                "prompt": "ما مجموع أضلاع المثلث الذي أطوالها ٣ و ٤ و ٥؟",
                "options": ["12", "9", "7", "10"],
                "answer_index": 0,
                "explanation": "٣ + ٤ + ٥ = ١٢ وحدة.",
                "difficulty": 2,
                "topic": "خصائص المثلث",
                "subject_id": subject.id,
                "lesson_id": lesson.id,
                "source_kind": "ai",
            },
        )
        check("bank_add", bank_question.status == "validated", bank_question.dedup_hash[:10])
        try:
            bank_service.add_question(
                db,
                {
                    "prompt": "ما مجموع أضلاع المثلث الذي أطوالها ٣ و ٤ و ٥؟",
                    "options": ["11", "12"],
                    "answer_index": 1,
                    "difficulty": 2,
                    "subject_id": subject.id,
                },
            )
            duplicate_blocked = False
        except ValidationError:
            duplicate_blocked = True
        check("bank_rejects_duplicate", duplicate_blocked)

        exam_payload = exams_service.generate_exam(
            db, profile.id, subject_id=subject.id, count=5, duration_minutes=10
        )
        check(
            "exam_generated",
            exam_payload["question_count"] >= 1,
            str(exam_payload["blueprint"]),
        )
        check(
            "exam_registered_to_bank",
            exam_payload["blueprint"]["generated"] + exam_payload["blueprint"]["from_bank"]
            == exam_payload["question_count"],
        )

        session = exams_service.start_exam(db, profile.id, exam_payload["id"], mode="mock")
        session_payload = exams_service.attempt_payload(db, session)
        check(
            "exam_timer_started",
            bool(session_payload["time_left_seconds"])
            and session_payload["time_left_seconds"] <= 600,
            str(session_payload["time_left_seconds"]),
        )
        check(
            "exam_hides_answers",
            all("correct" not in q["options"][0] for q in session_payload["questions"] if q["options"]),
        )
        answered = exams_service.answer(
            db, profile.id, session.id, session_payload["questions"][0]["id"], "إجابة خاطئة"
        )
        check("exam_answer_hidden", answered["ok"] is True and "correct" not in answered)

        mark_target = session_payload["questions"][
            1 if len(session_payload["questions"]) > 1 else 0
        ]
        marked = exams_service.toggle_mark(db, profile.id, session.id, mark_target["id"])
        check("exam_mark_for_review", marked["is_marked"] is True)

        analysis = exams_service.submit(db, profile.id, session.id)
        check(
            "exam_analysis",
            {"by_difficulty", "mistakes", "readiness", "recommendations"} <= set(analysis),
            f"acc={analysis['accuracy']}",
        )
        check("exam_mistakes_recorded", analysis["new_mistakes"] >= 1, str(analysis["new_mistakes"]))
        mistakes = exams_service.list_mistakes(db, profile.id)
        check("mistake_book", mistakes["total"] >= 1, str(mistakes["total"]))
        resolved = exams_service.resolve_mistake(db, profile.id, mistakes["items"][0]["id"])
        check("mistake_resolved", resolved["is_active"] is False)

        ready = exams_service.readiness(db, profile.id, subject.id)
        check(
            "readiness_factors",
            len(ready["factors"]) == 6 and ready["band"] in {"no_data", "weak", "not_ready", "ready_with_work", "ready"},
            f"score={ready['score']} band={ready['band']}",
        )
        check("readiness_has_steps", isinstance(ready["next_steps"], list))

        from app.db import ExamAttempt as _ExamAttempt
        from datetime import timedelta as _timedelta

        timer_payload = exams_service.generate_exam(
            db, profile.id, subject_id=subject.id, count=3, duration_minutes=10
        )
        timer_session = exams_service.start_exam(db, profile.id, timer_payload["id"])
        row = db.get(_ExamAttempt, timer_session.id)
        row.started_at = row.started_at - _timedelta(seconds=1000)
        db.flush()
        expired = exams_service.get_attempt(db, profile.id, timer_session.id)
        check(
            "exam_timer_enforced",
            expired["status"] in {"submitted", "expired"} and expired["overtime"] is True,
            expired["status"],
        )

        # ---- weak topic → plan -----------------------------------------
        weak = progress.active_weak(db, profile.id)
        check("weak_recorded", len(weak) >= 1, weak[0].topic if weak else "")

        plan = planner.generate_plan(db, profile.id, days=3)
        payload = planner.plan_payload(plan)
        check("generate_plan", len(payload["days"]) == 3, str(len(payload["days"])))
        check("plan_has_tasks", any(d["tasks"] for d in payload["days"]))

        now = planner.what_now(db, profile.id)
        check(
            "what_now",
            bool(now.get("lesson")),
            f"cands={len(planner.build_candidates(db, profile.id))} {str(now)[:80]}",
        )

        # ---- progress ---------------------------------------------------
        report2 = progress.progress_report(db, profile.id)
        check(
            "progress_report",
            "streak" in report2 or "mastery" in report2,
            str(list(report2)),
        )

        # ---- advisor: report → weekly → steps → apply --------------------
        from app.core.errors import NotFoundError as _NotFoundError
        from app.services import advisor as advisor_service

        adv_report = advisor_service.success_report(db, profile.id)
        check(
            "advisor_report_problems",
            isinstance(adv_report["problems"], list)
            and all(p["solution"] and p["action_key"] for p in adv_report["problems"]),
            f"n={len(adv_report['problems'])}",
        )
        check(
            "advisor_report_sections",
            {"strong_subjects", "weak_subjects", "weak_topics", "review_problems"} <= set(adv_report),
            str(sorted(adv_report))[:120],
        )

        adv_weekly = advisor_service.weekly_review(db, profile.id)
        check(
            "advisor_weekly_review",
            adv_weekly["improvement"] in {"up", "down", "flat"} and bool(adv_weekly["next_week_plan"]),
            str(adv_weekly["study_hours"]),
        )

        adv_steps = advisor_service.steps(db, profile.id)
        check(
            "advisor_steps",
            len(adv_steps) >= 5 and all("requires_approval" in s and "available" in s for s in adv_steps),
            str([s["key"] for s in adv_steps]),
        )

        adv_health = advisor_service.plan_health(db, profile.id)
        check(
            "advisor_plan_health",
            adv_health["available"] is True and adv_health["completion"] is not None,
            adv_health["message"][:80],
        )

        adv_priorities = advisor_service.priorities(db, profile.id)
        adv_shares = [row["share"] for row in adv_priorities["subjects"]]
        check(
            "advisor_priorities_balanced",
            bool(adv_shares)
            and sum(adv_shares) == 100
            and (len(adv_shares) == 1 or max(adv_shares) <= 60),
            str(adv_shares),
        )

        adv_apply = advisor_service.apply_step(db, profile.id, "add_session")
        check(
            "advisor_apply_session",
            adv_apply["ok"] is True and bool(adv_apply["data"]["event_id"]),
            adv_apply["message"],
        )
        adv_apply = advisor_service.apply_step(db, profile.id, "adjust_plan")
        check(
            "advisor_apply_plan",
            adv_apply["ok"] is True and bool(adv_apply["data"]["plan_id"]),
            adv_apply["message"],
        )
        try:
            advisor_service.apply_step(db, profile.id, "nope")
            unknown_blocked = False
        except _NotFoundError:
            unknown_blocked = True
        check("advisor_unknown_step", unknown_blocked)

        adv_overview = advisor_service.overview(db, profile.id)
        check(
            "advisor_overview",
            {"context", "report", "weekly", "steps", "priorities", "plan_health", "headline"}
            <= set(adv_overview)
            and bool(adv_overview["headline"]),
            adv_overview["headline"][:80],
        )

        from app.db import Notification as Notif, MorsState as MorsStateRow

        notifications = db.query(Notif).filter(Notif.student_id == profile.id).count()
        check("notifications_created", notifications >= 1, str(notifications))
        states = db.query(MorsStateRow).filter(MorsStateRow.student_id == profile.id).count()
        check("mors_states_recorded", states >= 3, str(states))

        # ---- chat -------------------------------------------------------
        from app.services import chat as chat_service

        refused = chat_service.chat(
            db, profile.id, "اشرح لي المفهوم ذا بالتفصيل من الكتاب", lesson_id=lesson.id
        )
        check("chat_refuses_without_source", refused["refused"] is True)
        check("chat_refusal_text", refused["reply"] == chat_service.NO_SOURCE)

        smalltalk = chat_service.chat(db, profile.id, "شلونك اليوم")
        check("chat_chitchat_ok", bool(smalltalk["reply"]) and not smalltalk["refused"])
        check(
            "conversation_saved",
            len(chat_service.list_conversations(db, profile.id)) >= 1,
        )
        chat_service.ask_for_help(db, profile.id, question="ما فهمت الفرق المشترك")

        # ---- books / reader --------------------------------------------
        from app.rag.ingest import index_book
        from app.rag.search import hybrid_search
        from app.services import books as books_service

        listed = books_service.list_books(db, profile)
        check("books_listed", len(listed["books"]) == 1, str(len(listed["books"])))
        row = listed["books"][0]
        check("books_page_count", row["page_count"] == 3, str(row["page_count"]))

        detail = books_service.get_book(db, book.id, profile)
        lessons_toc = [l for u in detail["toc"][0]["units"] for l in u["lessons"]]
        check("books_toc", bool(lessons_toc) and lessons_toc[0]["first_page"] == 1, str(lessons_toc))

        page1 = books_service.get_page(db, book.id, 1, profile)
        check("books_page_text", len(page1["text"]) > 20, page1["citation"])
        check("books_page_citation", page1["citation"].endswith("صفحة 1"), page1["citation"])
        clamped = books_service.get_page(db, book.id, 999, profile)
        check("books_page_clamp", clamped["page_number"] == 3, str(clamped["page_number"]))

        found = books_service.search_book(db, book.id, "تدريب")
        check("books_search", len(found["results"]) == 1, str(len(found["results"])))

        saved = books_service.save_progress(db, profile, book.id, last_page=2, bookmark={"page": 2, "label": "م"})
        check("books_progress", saved["last_page"] == 2 and saved["percent"] > 0, str(saved))

        indexed = index_book(db, book)
        db.commit()
        check("book_indexed", indexed >= 1, str(indexed))
        hits = hybrid_search(db, "الفرق المشترك بين الحدود", top_k=3)
        check("book_citation_in_rag", any(h.get("book") and h.get("page") for h in hits),
              hits[0].get("citation", "") if hits else "")

        from_page = chat_service.chat(
            db,
            profile.id,
            "اشرح لي هذا الجزء من الكتاب",
            book_id=book.id,
            page_number=1,
            mode="explain",
        )
        check("chat_with_book_page", not from_page["refused"], str(from_page["confidence"]))
        check(
            "chat_cites_book_page",
            any(c.get("page") == 1 for c in from_page["citations"]),
            str([c.get("citation") for c in from_page["citations"]][:1]),
        )

        # ---- dashboard / coach / inbox ---------------------------------
        from app.services import coach, dashboard

        page = dashboard.home(db, profile.id)
        check("dashboard_keys", {"mors", "today", "next", "streak"} <= set(page))
        check("dashboard_greeting", bool(page["greeting"]), page["greeting"])
        check("dashboard_today", page["today"]["date"] is not None)

        summary = dashboard.weekly_summary(db, profile.id)
        check("weekly_summary", summary["sessions"] >= 1, str(summary))

        brief = coach.daily_brief(db, profile.id, deliver=True)
        check("coach_brief", bool(brief["lines"]), brief["generated_by"])
        check("coach_delivered", brief["delivered"] is True)
        check("coach_actions", len(coach.action_items(db, profile.id)) >= 1)
        check("streak_brief", coach.streak_brief(db, profile.id)["state"] in {"active", "at_risk"})

        from app.services import notifications as inbox

        unread = inbox.unread_count(db, profile.id)
        check("inbox_unread", unread >= 3, str(unread))
        feed = inbox.pending_messages(db, profile.id, limit=50)
        check("mors_feed", len(feed) >= 1, feed[0]["text"] if feed else "")
        check("mors_text_arabic", bool(feed) and not _is_mojibake(feed[0]["text"]))
        delivered = inbox.mark_delivered(db, profile.id, [m["id"] for m in feed])
        check(
            "mors_delivered",
            delivered == len(feed) and inbox.pending_messages(db, profile.id, limit=50) == [],
            f"{delivered}/{len(feed)}",
        )
        state = inbox.mors_state(db, profile.id)
        check("mors_state_sprite", state["sprite"].endswith(".png"), state["state"])

        # ---- notes / summaries / flashcards -----------------------------
        from app.services import notes as notes_service
        from app.services import papers as papers_service

        note = notes_service.create_note(
            db, profile.id, title="ملاحظة المتتاليات", body="الفرق المشترك ثابت.",
            subject_id=subject.id, lesson_id=lesson.id, tags=["رياضيات"],
        )
        notes_service.update_note(db, profile.id, note.id, {"pinned": True, "body": "محدثة"})
        listed = notes_service.list_notes(db, profile.id, query="المتتاليات")
        check("notes_crud", len(listed) == 1 and listed[0]["pinned"])

        from app.services.search import index_note

        index_note(db, note)

        summary = notes_service.create_summary(db, profile.id, lesson_id=lesson.id)
        check("summary_created", bool(summary["body"]), summary["title"][:30])

        cards = notes_service.flashcards_from_lesson(db, profile.id, lesson_id=lesson.id, count=4)
        check("flashcards_created", len(cards) >= 2, str(len(cards)))
        reviewed = notes_service.review_flashcard(db, profile.id, cards[0]["id"], 5)
        check("flashcard_review", reviewed["interval_days"] >= 1)

        # ---- papers -----------------------------------------------------
        paper = papers_service.create_paper(
            db, profile.id, title="ورقة المتتاليات", lesson_id=lesson.id, subject_id=subject.id
        )
        page_id = paper.pages[0].id
        saved = papers_service.save_blocks(
            db,
            profile.id,
            page_id=page_id,
            blocks=[
                {"type": "heading", "content": {"text": "عنوان"}},
                {"type": "text", "content": {"text": "نص الملاحظة"}},
                {"type": "list", "content": {"items": ["أ", "ب"]}},
            ],
        )
        check("paper_blocks", len(saved[0]["blocks"]) == 3, str(len(saved[0]["blocks"])))
        generated = papers_service.generate_paper(
            db, profile.id, lesson_id=lesson.id, kind="worksheet"
        )
        check("paper_generated", generated["page_count"] >= 1 and len(generated["pages"][0]["blocks"]) >= 2)
        check("papers_listed", len(papers_service.list_papers(db, profile.id)) >= 2)

        # ---- search -----------------------------------------------------
        from app.services import search as search_service

        found = search_service.global_search(db, profile.id, "المتتاليات")
        check("search_lessons", len(found["groups"]["lessons"]) >= 1, str(found["total"]))
        check("search_notes", len(found["groups"]["notes"]) >= 1)
        check("search_empty_query", search_service.global_search(db, profile.id, "")["total"] == 0)

        # ---- upload -----------------------------------------------------
        from app.services import upload as upload_service

        upload = upload_service.save_upload(
            db,
            student_id=profile.id,
            uploader_id=user.id,
            filename="مذكرة.txt",
            data="المتتالية الحسابية فرقها ثابت.".encode("utf-8"),
            mime="text/plain",
            subject_id=subject.id,
        )
        check("upload_indexed", upload["status"] == "indexed", upload["status"] + " " + upload["error"])
        check("upload_listed", len(upload_service.list_uploads(db, profile.id)) == 1)
        check(
            "upload_chunks",
            upload_service.get_upload(db, profile.id, upload["id"])["meta"].get("chunks", 0) >= 1,
        )

        # ---- videos -----------------------------------------------------
        from app.db import Video as VideoModel
        from app.services import videos as videos_service

        video = VideoModel(
            title="شرح المتتاليات",
            url="https://example.com/v1",
            duration_seconds=100,
            subject_id=subject.id,
            lesson_id=lesson.id,
            transcript="المتتالية الحسابية فرقها ثابت بين حدودها.",
        )
        db.add(video)
        db.flush()
        listed_videos = videos_service.list_videos(db, profile.id, lesson_id=lesson.id)
        check("videos_listed", len(listed_videos) == 1)
        progress_row = videos_service.report_progress(
            db, profile.id, video.id, position=95, watched_seconds=95
        )
        check("video_completed", progress_row["progress"]["completed"] is True)
        hits = videos_service.search_transcripts(db, profile.id, "الحسابية")
        check("video_transcript_search", len(hits) == 1)

        # ---- courses / continue / quiz gate / reports (P4) --------------
        from app.db import Course as CourseModel

        course = db.query(CourseModel).filter(CourseModel.title == "كورس اختبار المدخول").first()
        if course is None:
            course = CourseModel(title="كورس اختبار المدخول", subject_id=subject.id, is_demo=True)
            db.add(course)
            db.flush()
        video.course_id = course.id
        db.flush()

        listed_courses = videos_service.list_courses(db, profile.id)
        check(
            "courses_listed_with_progress",
            any(c["id"] == course.id for c in listed_courses),
            str(len(listed_courses)),
        )
        course_detail = videos_service.course_progress(db, profile.id, course.id)
        check(
            "course_progress_shape",
            course_detail["video_total"] >= 1
            and course_detail["modules"]
            and 0.0 <= float(course_detail["progress_percent"]) <= 100.0,
            f"{course_detail['progress_percent']}%",
        )
        check(
            "course_lesson_statuses",
            all(
                l["status"] in {"new", "started", "watched", "quiz_failed", "completed"}
                for l in course_detail["lessons"]
            ),
            str(len(course_detail["lessons"])),
        )

        cont = videos_service.continue_watching(db, profile.id)
        check(
            "continue_watching",
            bool(cont) and cont["link"].startswith("/videos/") and "resume_from" in cont,
            str(cont and cont["title"]),
        )

        # §40 gate: a passing score closes the lesson, a failing one keeps it open
        gate = videos_service.start_video_quiz(db, profile.id, video.id)
        check("video_quiz_started", gate["question_count"] >= 1, gate["quiz_id"])
        gate_row = db.get(QuizModel, gate["quiz_id"])
        gate_answers = assessment.quiz_payload(db, gate_row, include_answers=True)
        gate_attempt = assessment.start_attempt(db, profile.id, gate["quiz_id"])
        for question in gate_answers["questions"]:
            correct_id = next(o["id"] for o in question["options"] if o["correct"])
            assessment.submit_answer(
                db, profile.id, gate_attempt.id, question["id"], correct_id, time_seconds=10
            )
        gate_report = assessment.finish_attempt(db, profile.id, gate_attempt.id)
        check("video_quiz_gate_pass", gate_report["accuracy"] >= 60, str(gate_report["accuracy"]))
        after_pass = videos_service.get_video(db, profile.id, video.id)
        check("video_lesson_completed", after_pass["status"] == "completed", after_pass["status"])

        video2 = VideoModel(
            title="فيديو ثاني للفشل",
            url="https://example.com/v2",
            duration_seconds=60,
            subject_id=subject.id,
            lesson_id=lesson.id,
            course_id=course.id,
            transcript="نص تجريبي آخر للاختبار.",
        )
        db.add(video2)
        db.flush()
        gate2 = videos_service.start_video_quiz(db, profile.id, video2.id)
        gate2_row = db.get(QuizModel, gate2["quiz_id"])
        gate2_answers = assessment.quiz_payload(db, gate2_row, include_answers=True)
        gate2_attempt = assessment.start_attempt(db, profile.id, gate2["quiz_id"])
        for question in gate2_answers["questions"]:
            wrong_id = next(
                (o["id"] for o in question["options"] if not o["correct"]), "wrong"
            )
            assessment.submit_answer(
                db, profile.id, gate2_attempt.id, question["id"], wrong_id, time_seconds=10
            )
        gate2_report = assessment.finish_attempt(db, profile.id, gate2_attempt.id)
        check("video_quiz_gate_fail", gate2_report["accuracy"] < 60, str(gate2_report["accuracy"]))
        after_fail = videos_service.get_video(db, profile.id, video2.id)
        check("video_stays_open_on_fail", after_fail["status"] == "quiz_failed", after_fail["status"])

        # §84 content report → review queue → resolve
        report = videos_service.report_content(
            db, profile.id, video.id, kind="not_working", detail="الرابط يفتح صفحة محذوفة"
        )
        check("content_report_created", report["status"] == "open", report["report_id"])
        queue = videos_service.list_content_reports(db, status="open")
        check(
            "content_report_queued",
            any(r["id"] == report["report_id"] for r in queue["reports"]),
            str(queue["open"]),
        )
        resolved = videos_service.resolve_content_report(db, report["report_id"])
        check("content_report_resolved", resolved["status"] == "resolved", resolved["status"])
        open_queue = videos_service.list_content_reports(db, status="open")
        check(
            "content_report_left_queue",
            all(r["id"] != report["report_id"] for r in open_queue["reports"]),
        )

        # ---- voice (§15/§70) --------------------------------------------
        from app.core.errors import UnsupportedFeatureError
        from app.services import voice as voice_service

        vcfg = voice_service.voice_config(db, user)
        check(
            "voice_config",
            vcfg["tts_provider"] and vcfg["styles"] and vcfg["realtime"] is False,
            vcfg["tts_provider"],
        )
        check("voice_config_user_prefs", "voice_enabled" in vcfg["user"])

        spoken = voice_service.speak("أهلاً بك، هذا صوتي.", style="happy")
        check(
            "voice_speak_style_tone",
            spoken["provider"] == "browser"
            and spoken["rate"] >= 1.0
            and spoken["lang"] == "ar-IQ",
            f"rate={spoken['rate']}",
        )
        try:
            voice_service.speak("أهلاً", style="nope")
            bad_style = False
        except ValidationError:
            bad_style = True
        check("voice_bad_style_rejected", bad_style)

        old_tts = voice_service.settings.ai_tts_provider
        voice_service.settings.ai_tts_provider = "openai"
        try:
            voice_service.speak("أهلاً")
            unavailable = False
        except UnsupportedFeatureError:
            unavailable = True
        finally:
            voice_service.settings.ai_tts_provider = old_tts
        check("voice_unavailable_provider", unavailable)

        browser_stt = voice_service.transcribe(b"RIFFfake")
        check(
            "voice_stt_browser_local",
            browser_stt["available"] is False and browser_stt["text"] == "",
        )

        old_stt = voice_service.settings.ai_stt_provider
        voice_service.settings.ai_stt_provider = "mock"
        try:
            mock_stt = voice_service.transcribe(
                b"RIFFfake", filename="q.wav", mime="audio/wav"
            )
        finally:
            voice_service.settings.ai_stt_provider = old_stt
        check(
            "voice_stt_mock",
            mock_stt["available"] and mock_stt["text"] == voice_service.MOCK_TRANSCRIPT,
        )

        # ---- export -----------------------------------------------------
        from app.services import export as export_service

        export_data = export_service.progress_json(db, profile.id)
        check("export_json", {"dashboard", "progress", "plans"} <= set(export_data))
        ics = export_service.plan_ics(db, profile.id)
        check("export_ics", ics.startswith("BEGIN:VCALENDAR"))
        pdf = export_service.progress_pdf(db, profile.id)
        check("export_pdf", pdf[:5] == b"%PDF-", str(len(pdf)))

        # ---- admin ------------------------------------------------------
        from app.services import admin as admin_service

        prompts = admin_service.list_prompts(db)
        check("admin_prompts", len(prompts) == 10, str(len(prompts)))
        first = prompts[0]["key"]
        updated = admin_service.update_prompt(
            db, first, template=prompts[0]["template"] + "\n- أضف قاعدة جديدة للتجربة.", updated_by=user.id
        )
        check("admin_prompt_update", updated["version"] == 2, str(updated))
        admin_service.reset_prompt(db, first)
        check("admin_prompt_reset", True)
        stats = admin_service.curriculum_stats(db)
        check("admin_stats", stats["lessons"] >= 1 and stats["users"] >= 1, str(stats["lessons"]))
        usage = admin_service.ai_usage(db, days=7)
        check("admin_usage", usage["requests"] >= 1, str(usage["requests"]))
        admin_service.set_setting(db, "maintenance", "off")
        check("admin_setting", admin_service.get_setting(db, "maintenance") == "off")
        admin_service.list_users(db, query="ahmad")
        events = admin_service.recent_events(db, limit=10)
        check("admin_events", len(events) >= 1, str(len(events)))

        # ---- publishing pipeline (§83) + scheduler (§126) -----------
        from datetime import timedelta as _td

        from app.db import ContentDraft as ContentDraftModel, utcnow as _utcnow
        from app.services import publishing as publishing_service
        from app.services import scheduler as scheduler_service

        draft = publishing_service.create_draft(
            db,
            entity="lesson",
            payload={"subject_id": subject.id, "title": "درس الاختبار الدخاني"},
            created_by=user.id,
        )
        check("draft_created", draft["status"] == "draft", draft["id"])
        processed = publishing_service.process_draft(db, draft["id"])
        check(
            "draft_ai_processed",
            processed["status"] == "validated" and bool(processed["ai_notes"]),
            processed["status"],
        )
        scheduled = publishing_service.review_draft(
            db,
            draft["id"],
            approve=True,
            reviewer=user.id,
            publish_at=_utcnow() + _td(hours=1),
        )
        check("draft_scheduled", scheduled["status"] == "scheduled", scheduled["status"])
        due = publishing_service.run_due_publications(db)
        check(
            "auto_publish_skips_future",
            "درس الاختبار الدخاني" not in due["published"],
            str(due["published"]),
        )
        row = db.get(ContentDraftModel, draft["id"])
        row.publish_at = _utcnow() - _td(minutes=1)
        db.flush()
        due = publishing_service.run_due_publications(db)
        check("auto_publish_due", "درس الاختبار الدخاني" in due["published"], str(due))
        check("draft_materialised", db.get(Lesson, row.entity_id) is not None, str(row.entity_id))

        bad = publishing_service.create_draft(
            db, entity="chapter", payload={"title": "فصل بلا كتاب"}, created_by=user.id
        )
        bad_state = publishing_service.process_draft(db, bad["id"])
        check(
            "draft_validation_rejects",
            bad_state["status"] == "rejected" and bool(bad_state["issues"]),
            str(bad_state["issues"]),
        )
        try:
            publishing_service.review_draft(db, bad["id"], approve=True, reviewer=user.id)
            check("draft_review_requires_validation", False)
        except ValidationError:
            check("draft_review_requires_validation", True)
        publishing_service.delete_draft(db, bad["id"])
        check("draft_deleted", True)

        jobs = scheduler_service.jobs_status(db)
        check("scheduler_jobs_listed", len(jobs) == 3, ",".join(j["name"] for j in jobs))
        run = scheduler_service.run_job(db, "prune_rate_counters")
        check("scheduler_run_ok", run["status"] == "ok", str(run["detail"]))
        try:
            scheduler_service.run_job(db, "no_such_job")
            check("scheduler_unknown_job", False)
        except NotFoundError:
            check("scheduler_unknown_job", True)

        # ---- tone guard -------------------------------------------------
        messages = [
            m for m in _collect_messages(db, profile.id)
        ]
        for message in messages:
            assert_tone(message)
        check("tone_ok", True, f"{len(messages)} mors messages")
        check(
            "no_mojibake",
            not any(_is_mojibake(m) for m in messages),
            next((m for m in messages if _is_mojibake(m)), "")[:40],
        )
        import re as _re

        leftover = [m for m in messages if _re.search(r"\{\w+\}", m)]
        check("no_unfilled_placeholders", not leftover, leftover[0] if leftover else "")

        from app.mors.messages import MESSAGES

        for scenario_name, lines in MESSAGES.items():
            for line in lines:
                assert_tone(line)
        check("all_templates_tone", True, f"{len(MESSAGES)} scenarios")
        check(
            "all_sprites_exist",
            _missing_sprites(MESSAGES) == [],
            str(_missing_sprites(MESSAGES)),
        )

        failing = [name for name, ok, _ in CHECKS if not ok]
        print(f"\n{len(CHECKS) - len(failing)}/{len(CHECKS)} checks passed")
        if failing:
            print("failed:", ", ".join(failing))
        return 1 if failing else 0
    finally:
        db.close()


def _time0():
    from datetime import time

    return time(0, 0)


def inbox_quiet_default(db, student_id):
    from app.services.notifications import quiet_hours

    return quiet_hours(db, student_id)


def _is_mojibake(text: str) -> bool:
    return any(marker in text for marker in ("ط§", "ظ„", "ظ†", "â€"))


def _missing_sprites(scenarios) -> list[str]:
    from app.mors.states import SPECS

    sprites = {spec.sprite for spec in SPECS.values()}
    return sorted(s for s in sprites if not (ROOT / "frontend" / "public" / "mors" / f"{s}.png").exists())


def _collect_messages(db, student_id: str) -> list[str]:
    from app.db import MorsMessage

    return [m.text for m in db.query(MorsMessage).filter(MorsMessage.student_id == student_id).all()]


if __name__ == "__main__":
    raise SystemExit(main())
