"""Exam simulation, readiness and the mistake book (spec §25–§35, §66).

Code, not promises: readiness is computed from mastery rows, attempt history,
weak topics, curriculum coverage and revision state. An exam session owns the
timer, navigation and mark-for-review; grading stays in `assessment`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.errors import NotFoundError, ValidationError
from ..db import (
    Answer,
    Exam,
    ExamAttempt,
    Lesson,
    MasteryScore,
    Mistake,
    Option,
    Question,
    Quiz,
    QuizAttempt,
    Review,
    StudentProfile,
    StudentSubject,
    Subject,
    WeakTopic,
    utcnow,
)
from . import assessment, bank
from .progress import active_weak

READINESS_FACTORS: list[tuple[str, str, float]] = [
    ("mastery", "إتقان الدروس", 0.30),
    ("recent", "آخر الاختبارات", 0.25),
    ("mock", "محاكاة الامتحانات", 0.15),
    ("weak", "المواضع الضعيفة", 0.15),
    ("coverage", "تغطية المنهج", 0.10),
    ("revision", "المراجعات", 0.05),
]


# --------------------------------------------------------------------------- #
# blueprint + generation
# --------------------------------------------------------------------------- #
def _scope_lessons(db: Session, student_id: str, subject_id: str | None, limit: int) -> list[str]:
    """Lessons an exam should cover: weak ones first, then the syllabus order."""
    if not subject_id:
        return []
    lessons = (
        db.query(Lesson).filter(Lesson.subject_id == subject_id).order_by(Lesson.index).all()
    )
    weak_ids = {
        row.lesson_id
        for row in active_weak(db, student_id, limit=40)
        if row.lesson_id and (not subject_id or row.subject_id in (None, subject_id))
    }
    ordered = [l for l in lessons if l.id in weak_ids] + [l for l in lessons if l.id not in weak_ids]
    return [lesson.id for lesson in ordered[: max(1, limit)]]


def _target_difficulty(db: Session, student_id: str, subject_id: str | None, fallback: int) -> int:
    """Adaptive base difficulty (spec §27): from recent accuracy, not guessing."""
    query = db.query(QuizAttempt, Quiz).join(Quiz, Quiz.id == QuizAttempt.quiz_id).filter(
        QuizAttempt.student_id == student_id, QuizAttempt.status == "finished"
    )
    if subject_id:
        query = query.filter(Quiz.subject_id == subject_id)
    rows = query.order_by(QuizAttempt.finished_at.desc()).limit(10).all()
    if not rows:
        return fallback
    avg = sum(attempt.accuracy for attempt, _ in rows) / len(rows)
    if avg >= 85:
        return min(5, fallback + 1)
    if avg < 55:
        return max(1, fallback - 1)
    return fallback


def _draw_from_bank(
    db: Session,
    *,
    subject_id: str | None,
    lesson_id: str | None,
    chapter_id: str | None,
    scope_lessons: list[str],
    difficulty: int,
    count: int,
) -> list[dict[str, Any]]:
    def collect(difficulty_filter: int | None) -> list[Question]:
        query = db.query(Question).filter(Question.quiz_id.is_(None), Question.status == "published")
        if subject_id:
            query = query.filter(Question.subject_id == subject_id)
        if lesson_id:
            query = query.filter(Question.lesson_id == lesson_id)
        if chapter_id:
            query = query.filter(Question.chapter_id == chapter_id)
        if scope_lessons:
            query = query.filter(Question.lesson_id.in_(scope_lessons))
        if difficulty_filter:
            query = query.filter(Question.difficulty == difficulty_filter)
        return query.order_by(func.random()).limit(count).all()

    rows = collect(difficulty)
    if len(rows) < count:
        seen = {row.id for row in rows}
        rows += [r for r in collect(None) if r.id not in seen][: count - len(rows)]
    return [bank.item_from_question(row) for row in rows]


def generate_exam(
    db: Session,
    student_id: str,
    *,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    chapter_id: str | None = None,
    title: str = "",
    count: int = 20,
    difficulty: int = 3,
    duration_minutes: int = 45,
    kind: str = "mock",
) -> dict[str, Any]:
    count = max(1, min(assessment.MAX_QUESTIONS, count))
    difficulty = max(1, min(5, difficulty))
    duration_minutes = max(5, min(240, int(duration_minutes or 45)))

    lesson = db.get(Lesson, lesson_id) if lesson_id else None
    if lesson and not subject_id:
        subject_id = lesson.subject_id
    subject = db.get(Subject, subject_id) if subject_id else None

    scope_lessons = _scope_lessons(db, student_id, subject_id, limit=max(3, count // 4)) if not lesson_id else []
    target_difficulty = _target_difficulty(db, student_id, subject_id, difficulty)

    items: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    def push(candidate: dict[str, Any], *, source: str) -> None:
        digest = bank.dedup_hash(str(candidate.get("prompt", "")))
        if digest in seen_hashes:
            return
        issues = bank.validate_item(candidate)
        if bank.has_errors(issues):
            meta.setdefault("dropped", 0)
            meta["dropped"] += 1
            return
        seen_hashes.add(digest)
        # content already in the bank is reused instead of re-registered (§78)
        existing = (
            db.query(Question)
            .filter(Question.quiz_id.is_(None), Question.dedup_hash == digest)
            .first()
        )
        if existing:
            reused = bank.item_from_question(existing)
            reused["_source"] = "bank"
            items.append(reused)
            return
        candidate["_source"] = source
        items.append(candidate)

    meta: dict[str, Any] = {"from_bank": 0, "generated": 0, "dropped": 0, "difficulty": target_difficulty}

    for candidate in _draw_from_bank(
        db,
        subject_id=subject_id,
        lesson_id=lesson_id,
        chapter_id=chapter_id,
        scope_lessons=scope_lessons,
        difficulty=target_difficulty,
        count=count,
    ):
        push(candidate, source="bank")
    meta["from_bank"] = len(items)

    if len(items) < count:
        generated = assessment._ai_questions(
            db,
            student_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            count=count - len(items),
            difficulty=target_difficulty,
            types=["mcq"],
        )
        for candidate in generated:
            if len(items) >= count:
                break
            candidate.setdefault("source_kind", "ai")
            candidate.setdefault("subject_id", subject_id)
            candidate.setdefault("lesson_id", lesson_id)
            candidate.setdefault("chapter_id", chapter_id)
            push(candidate, source="generated")

    if len(items) < count:
        for candidate in assessment._local_questions(
            lesson, subject, count=count - len(items), difficulty=target_difficulty, seed=student_id
        ):
            if len(items) >= count:
                break
            candidate.setdefault("source_kind", "ai")
            candidate.setdefault("subject_id", subject_id)
            candidate.setdefault("lesson_id", lesson_id)
            candidate.setdefault("chapter_id", chapter_id)
            push(candidate, source="generated")

    meta["generated"] = sum(1 for item in items if item["_source"] == "generated")
    if not items:
        raise ValidationError("تعذّر بناء أسئلة لهذا النطاق — حدّد مادة أو درساً آخر.")

    # the bank grows with every validated generation (spec §77)
    for item in items:
        if item["_source"] == "generated":
            bank.register_generated(db, item, status="published")

    quiz = Quiz(
        student_id=student_id,
        subject_id=subject_id,
        lesson_id=lesson_id,
        title=title or (f"امتحان {subject.name_ar}" if subject else (f"امتحان {lesson.title}" if lesson else "امتحان تجريبي")),
        kind=kind,
        difficulty=target_difficulty,
        time_limit_seconds=duration_minutes * 60,
        is_adaptive=True,
        source_scope="curriculum",
        generated_by="ai",
        status="ready",
        meta={"blueprint": meta, "duration_minutes": duration_minutes, "mode": "exam"},
    )
    db.add(quiz)
    db.flush()

    for index, item in enumerate(items):
        checked_at = bank.parse_checked_at(item.get("checked_at"))
        source_kind = str(item.get("source_kind", "ai"))
        if source_kind == "official" and checked_at is None:
            checked_at = utcnow()
        question = Question(
            quiz_id=quiz.id,
            type=item.get("type", "mcq"),
            prompt=str(item.get("prompt", "")).strip(),
            explanation=str(item.get("explanation", "")),
            difficulty=max(1, min(5, int(item.get("difficulty", target_difficulty) or target_difficulty))),
            order=index,
            answer_key=str(item.get("answer_index", 0)),
            source_id=item.get("source_id"),
            source_url=str(item.get("source_url") or "").strip(),
            checked_at=checked_at,
            topic=str(item.get("topic", "")),
            source_kind=source_kind,
            subject_id=item.get("subject_id") or subject_id,
            chapter_id=item.get("chapter_id") or chapter_id,
            lesson_id=item.get("lesson_id") or lesson_id,
            year=str(item.get("year") or ""),
            page=item.get("page"),
            status="published",
            dedup_hash=bank.dedup_hash(str(item.get("prompt", ""))),
            meta={"local": bool(item.get("local"))},
        )
        db.add(question)
        db.flush()
        options = item.get("options") or []
        if question.type in ("mcq", "true_false"):
            for opt_index, text in enumerate(options):
                db.add(
                    Option(
                        question_id=question.id,
                        text=str(text),
                        is_correct=opt_index == int(item.get("answer_index", 0)),
                        order=opt_index,
                    )
                )
    db.flush()

    payload = assessment.quiz_payload(db, quiz, include_answers=False)
    payload.update(
        {
            "time_limit_seconds": quiz.time_limit_seconds,
            "duration_minutes": duration_minutes,
            "blueprint": meta,
        }
    )
    return payload


# --------------------------------------------------------------------------- #
# exam session (timer + navigation + mark-for-review)
# --------------------------------------------------------------------------- #
def _elapsed_seconds(attempt: ExamAttempt) -> int:
    start = attempt.started_at or utcnow()
    now = utcnow()
    if start.tzinfo is None and now.tzinfo is not None:
        start = start.replace(tzinfo=now.tzinfo)
    return max(0, int((now - start).total_seconds()))


def _time_left(attempt: ExamAttempt) -> int | None:
    if not attempt.time_limit_seconds:
        return None
    return max(0, attempt.time_limit_seconds - _elapsed_seconds(attempt))


def start_exam(
    db: Session,
    student_id: str,
    quiz_id: str,
    *,
    mode: str = "mock",
    exam_id: str | None = None,
) -> ExamAttempt:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None or (quiz.student_id and quiz.student_id != student_id):
        raise NotFoundError("الاختبار غير موجود.")

    existing = (
        db.query(ExamAttempt)
        .filter(
            ExamAttempt.student_id == student_id,
            ExamAttempt.quiz_id == quiz_id,
            ExamAttempt.status == "in_progress",
        )
        .first()
    )
    if existing:
        return existing

    underlying = assessment.start_attempt(db, student_id, quiz_id)
    attempt = ExamAttempt(
        student_id=student_id,
        exam_id=exam_id,
        quiz_id=quiz_id,
        attempt_id=underlying.id,
        mode=mode,
        time_limit_seconds=quiz.time_limit_seconds,
        started_at=utcnow(),
        marked=[],
        status="in_progress",
    )
    db.add(attempt)
    db.flush()
    return attempt


def answered_map(db: Session, attempt: ExamAttempt) -> dict[str, str]:
    rows = db.query(Answer).filter(Answer.attempt_id == attempt.attempt_id).all()
    return {row.question_id: row.student_answer for row in rows}


def attempt_payload(db: Session, attempt: ExamAttempt, *, include_report: bool = False) -> dict[str, Any]:
    quiz = db.get(Quiz, attempt.quiz_id)
    payload = assessment.quiz_payload(db, quiz, include_answers=False) if quiz else {"questions": []}
    left = _time_left(attempt)
    answers = answered_map(db, attempt)
    payload.update(
        {
            "exam_attempt_id": attempt.id,
            "attempt_id": attempt.attempt_id,
            "mode": attempt.mode,
            "status": attempt.status,
            "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
            "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
            "time_limit_seconds": attempt.time_limit_seconds,
            "time_left_seconds": left,
            "elapsed_seconds": _elapsed_seconds(attempt),
            "marked": list(attempt.marked or []),
            "current_index": attempt.current_index,
            "overtime": attempt.overtime,
            "answered": answers,
            "answered_count": len(answers),
        }
    )
    if include_report:
        payload["report"] = attempt.report or {}
    return payload


def get_attempt(db: Session, student_id: str, exam_attempt_id: str) -> dict[str, Any]:
    attempt = db.get(ExamAttempt, exam_attempt_id)
    if attempt is None or attempt.student_id != student_id:
        raise NotFoundError("جلسة الامتحان غير موجودة.")
    left = _time_left(attempt)
    if attempt.status == "in_progress" and left is not None and left <= 0:
        _finalize(db, attempt, expired=True)
    return attempt_payload(db, attempt, include_report=True)


def answer(
    db: Session,
    student_id: str,
    exam_attempt_id: str,
    question_id: str,
    student_answer: str,
    *,
    time_seconds: int = 0,
) -> dict[str, Any]:
    attempt = db.get(ExamAttempt, exam_attempt_id)
    if attempt is None or attempt.student_id != student_id:
        raise NotFoundError("جلسة الامتحان غير موجودة.")
    left = _time_left(attempt)
    if attempt.status != "in_progress":
        raise ValidationError("تم إرسال هذا الامتحان مسبقاً.")
    if left is not None and left <= 0:
        report = _finalize(db, attempt, expired=True)
        raise ValidationError("انتهى وقت الامتحان — أُرسل تلقائياً.", details={"report": report})

    # grading is server-side but hidden until submission (simulation rule)
    assessment.submit_answer(
        db, student_id, attempt.attempt_id, question_id, student_answer, time_seconds=time_seconds
    )
    return {
        "ok": True,
        "question_id": question_id,
        "time_left_seconds": _time_left(attempt),
        "answered_count": len(answered_map(db, attempt)),
    }


def toggle_mark(db: Session, student_id: str, exam_attempt_id: str, question_id: str) -> dict[str, Any]:
    attempt = db.get(ExamAttempt, exam_attempt_id)
    if attempt is None or attempt.student_id != student_id:
        raise NotFoundError("جلسة الامتحان غير موجودة.")
    if attempt.status != "in_progress":
        raise ValidationError("انتهت جلسة الامتحان.")
    marks = list(attempt.marked or [])
    if question_id in marks:
        marks.remove(question_id)
    else:
        marks.append(question_id)
    attempt.marked = marks
    db.flush()
    return {"marked": marks, "is_marked": question_id in marks}


def submit(db: Session, student_id: str, exam_attempt_id: str) -> dict[str, Any]:
    attempt = db.get(ExamAttempt, exam_attempt_id)
    if attempt is None or attempt.student_id != student_id:
        raise NotFoundError("جلسة الامتحان غير موجودة.")
    if attempt.status != "in_progress":
        return attempt.report or {}
    left = _time_left(attempt)
    return _finalize(db, attempt, expired=left is not None and left <= 0)


def _finalize(db: Session, attempt: ExamAttempt, *, expired: bool = False) -> dict[str, Any]:
    report = assessment.finish_attempt(db, attempt.student_id, attempt.attempt_id)
    attempt.status = "expired" if expired else "submitted"
    attempt.overtime = bool(expired)
    attempt.finished_at = utcnow()
    analysis = _analysis(db, attempt, report)
    attempt.report = analysis
    db.flush()
    return analysis


# --------------------------------------------------------------------------- #
# analysis + mistake book
# --------------------------------------------------------------------------- #
def _correct_answer_text(question: Question) -> str:
    if question.type in ("mcq", "true_false"):
        for option in sorted(question.options, key=lambda o: o.order):
            if option.is_correct:
                return option.text
    return question.answer_key


def _analysis(db: Session, attempt: ExamAttempt, report: dict[str, Any]) -> dict[str, Any]:
    quiz = db.get(Quiz, attempt.quiz_id)
    questions = sorted(quiz.questions, key=lambda q: q.order) if quiz else []
    answers = {row.question_id: row for row in db.query(Answer).filter(Answer.attempt_id == attempt.attempt_id).all()}

    by_difficulty: dict[str, dict[str, int]] = {
        str(level): {"total": 0, "correct": 0, "wrong": 0, "skipped": 0} for level in range(1, 6)
    }
    by_topic: dict[str, dict[str, int]] = {}
    mistakes: list[dict[str, Any]] = []
    new_mistakes = 0

    for question in questions:
        bucket = by_difficulty.setdefault(str(question.difficulty), {"total": 0, "correct": 0, "wrong": 0, "skipped": 0})
        bucket["total"] += 1
        answer = answers.get(question.id)
        topic_key = question.topic or "عام"
        topic = by_topic.setdefault(topic_key, {"total": 0, "correct": 0, "wrong": 0})
        topic["total"] += 1

        if answer is None:
            bucket["skipped"] += 1
            reason = "skipped"
        elif answer.is_correct:
            bucket["correct"] += 1
            topic["correct"] += 1
            continue
        else:
            bucket["wrong"] += 1
            topic["wrong"] += 1
            reason = "wrong"

        given = answer.student_answer if answer else ""
        correct_text = _correct_answer_text(question)
        mistakes.append(
            {
                "question_id": question.id,
                "prompt": question.prompt,
                "given": given,
                "correct": correct_text,
                "explanation": question.explanation,
                "topic": question.topic,
                "difficulty": question.difficulty,
                "reason": reason,
                "provenance": bank.provenance(question),
            }
        )
        if _record_mistake(db, attempt, question, given, correct_text, reason=reason):
            new_mistakes += 1

    duration = attempt.time_limit_seconds or 0
    analysis: dict[str, Any] = {
        "exam_attempt_id": attempt.id,
        "attempt_id": attempt.attempt_id,
        "quiz_id": attempt.quiz_id,
        "title": quiz.title if quiz else "امتحان",
        "mode": attempt.mode,
        "status": attempt.status,
        "overtime": bool(attempt.overtime),
        "score": round(report.get("score", 0.0), 2),
        "accuracy": report.get("accuracy", 0.0),
        "correct": report.get("correct", 0),
        "wrong": report.get("wrong", 0),
        "skipped": report.get("skipped", 0),
        "time_seconds": report.get("time_seconds", 0),
        "time_limit_seconds": duration,
        "by_difficulty": by_difficulty,
        "by_topic": by_topic,
        "mistakes": mistakes,
        "new_mistakes": new_mistakes,
        "weak_topics": report.get("weak_topics", []),
        "strong_topics": report.get("strong_topics", []),
        "previous_accuracy": report.get("previous_accuracy"),
        "delta": report.get("delta"),
        "recommendations": _recommendations(db, quiz, report.get("weak_topics", [])),
        "readiness": readiness(db, attempt.student_id, subject_id=quiz.subject_id if quiz else None),
        "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
    }
    return analysis


def _record_mistake(
    db: Session,
    attempt: ExamAttempt,
    question: Question,
    given: str,
    correct_text: str,
    *,
    reason: str,
) -> bool:
    digest = bank.dedup_hash(question.prompt)
    existing = (
        db.query(Mistake)
        .filter(
            Mistake.student_id == attempt.student_id,
            Mistake.is_active.is_(True),
        )
        .all()
    )
    if any(bank.dedup_hash(row.prompt) == digest for row in existing):
        return False
    quiz = db.get(Quiz, attempt.quiz_id)
    db.add(
        Mistake(
            student_id=attempt.student_id,
            subject_id=question.subject_id or (quiz.subject_id if quiz else None),
            lesson_id=question.lesson_id or (quiz.lesson_id if quiz else None),
            question_id=question.id,
            attempt_id=attempt.attempt_id,
            prompt=question.prompt,
            student_answer=given,
            correct_answer=correct_text,
            explanation=question.explanation,
            topic=question.topic,
            difficulty=question.difficulty,
            source_kind=question.source_kind,
            reason=reason,
        )
    )
    db.flush()
    return True


def _recommendations(db: Session, quiz: Quiz | None, weak_topics: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for topic in weak_topics[:5]:
        lesson = None
        if quiz and quiz.subject_id:
            lesson = (
                db.query(Lesson)
                .filter(
                    Lesson.subject_id == quiz.subject_id,
                    Lesson.title.like(f"%{topic[:20]}%"),
                )
                .first()
            )
        out.append(
            {
                "topic": topic,
                "lesson_id": lesson.id if lesson else None,
                "lesson_title": lesson.title if lesson else None,
                "hint": f"راجع درس «{lesson.title}»" if lesson else f"راجع موضع «{topic}» من ملاحظاتك وكتابك.",
            }
        )
    return out


def list_mistakes(
    db: Session,
    student_id: str,
    *,
    subject_id: str | None = None,
    active_only: bool = True,
    q: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    query = db.query(Mistake).filter(Mistake.student_id == student_id)
    if active_only:
        query = query.filter(Mistake.is_active.is_(True))
    if subject_id:
        query = query.filter(Mistake.subject_id == subject_id)
    if q.strip():
        query = query.filter(Mistake.prompt.like(f"%{q.strip()}%"))
    total = query.count()
    rows = query.order_by(Mistake.created_at.desc()).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "prompt": row.prompt,
                "student_answer": row.student_answer,
                "correct_answer": row.correct_answer,
                "explanation": row.explanation,
                "topic": row.topic,
                "difficulty": row.difficulty,
                "reason": row.reason,
                "source_kind": row.source_kind,
                "subject_id": row.subject_id,
                "lesson_id": row.lesson_id,
                "is_active": row.is_active,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


def resolve_mistake(db: Session, student_id: str, mistake_id: str) -> dict[str, Any]:
    row = db.get(Mistake, mistake_id)
    if row is None or row.student_id != student_id:
        raise NotFoundError("الخطأ غير موجود.")
    row.is_active = False
    row.resolved_at = utcnow()
    db.flush()
    return {"id": row.id, "is_active": False}


# --------------------------------------------------------------------------- #
# exam readiness (spec §30)
# --------------------------------------------------------------------------- #
def _scope_attempts(db: Session, student_id: str, subject_id: str | None) -> list[tuple[QuizAttempt, Quiz]]:
    query = (
        db.query(QuizAttempt, Quiz)
        .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
        .filter(QuizAttempt.student_id == student_id, QuizAttempt.status == "finished")
    )
    if subject_id:
        query = query.filter(Quiz.subject_id == subject_id)
    return query.order_by(QuizAttempt.finished_at.desc()).limit(30).all()


def readiness(db: Session, student_id: str, subject_id: str | None = None) -> dict[str, Any]:
    mastery_q = db.query(MasteryScore).filter(MasteryScore.student_id == student_id)
    weak_q = db.query(WeakTopic).filter(WeakTopic.student_id == student_id, WeakTopic.is_active.is_(True))
    if subject_id:
        mastery_q = mastery_q.filter(MasteryScore.subject_id == subject_id)
        weak_q = weak_q.filter(WeakTopic.subject_id == subject_id)

    mastery_rows = mastery_q.all()
    weak_count = weak_q.count()
    attempts = _scope_attempts(db, student_id, subject_id)
    recent = [a for a, _ in attempts[:10]]

    factors: list[dict[str, Any]] = []

    def add(key: str, score: float | None, detail: str = "") -> None:
        label, weight = next((label, weight) for k, label, weight in READINESS_FACTORS if k == key)
        factors.append(
            {"key": key, "label": label, "weight": weight, "score": round(score, 1) if score is not None else None, "detail": detail}
        )

    add(
        "mastery",
        (sum(row.score for row in mastery_rows) / len(mastery_rows)) if mastery_rows else None,
        f"{len(mastery_rows)} درساً مقيَّماً",
    )
    add(
        "recent",
        (sum(a.accuracy for a in recent) / len(recent)) if recent else None,
        f"{len(recent)} محاولة مُقيَّمة",
    )

    mocks = [
        (a, q)
        for a, q in attempts
        if q.kind in ("mock", "exam", "final", "diagnostic")
        and a.finished_at
        and a.finished_at >= utcnow() - timedelta(days=30)
    ]
    if mocks:
        avg_mock = sum(a.accuracy for a, _ in mocks) / len(mocks)
        add("mock", 0.4 * min(100.0, 30.0 + 25.0 * len(mocks)) + 0.6 * avg_mock, f"{len(mocks)} امتحاناً خلال شهر")
    else:
        add("mock", None, "لا توجد محاكاة حديثة")

    if weak_count or recent or mastery_rows:
        add("weak", max(0.0, 100.0 - 12.0 * weak_count), f"{weak_count} موضعاً ضعيفاً")
    else:
        add("weak", None, "لا توجد بيانات")

    coverage_score: float | None = None
    coverage_detail = "اختر مادة لحساب التغطية"
    topics_remaining: list[str] = []
    if subject_id:
        total_lessons = db.query(func.count(Lesson.id)).filter(Lesson.subject_id == subject_id).scalar() or 0
        covered = {row.lesson_id for row in mastery_rows if row.lesson_id}
        if total_lessons:
            coverage_score = 100.0 * len(covered) / total_lessons
            missing_q = db.query(Lesson).filter(Lesson.subject_id == subject_id)
            if covered:
                missing_q = missing_q.filter(~Lesson.id.in_(covered))
            missing = missing_q.order_by(Lesson.index).limit(6).all()
            topics_remaining = [lesson.title for lesson in missing]
            coverage_detail = f"{len(covered)}/{total_lessons} درساً"
    add("coverage", coverage_score, coverage_detail)

    reviews = db.query(Review).filter(Review.student_id == student_id)
    if subject_id:
        reviews = reviews.filter(Review.subject_id == subject_id)
    review_rows = reviews.all()
    if review_rows:
        done = sum(1 for row in review_rows if row.status == "done")
        add("revision", 100.0 * done / len(review_rows), f"{done}/{len(review_rows)} مراجعة منجزة")
    else:
        add("revision", None, "لا توجد مراجعات بعد")

    known = [f for f in factors if f["score"] is not None]
    weight_sum = sum(f["weight"] for f in known)
    score = (
        round(sum(f["score"] * f["weight"] for f in known) / weight_sum, 1) if weight_sum else None
    )

    if score is None:
        band, message = "no_data", "لا توجد بيانات كافية بعد — ابدأ باختبار تشخيصي لقياس مستواك."
    elif score >= 85:
        band, message = "ready", "جاهز — استمر بالتمارين وحافظ على المراجعات."
    elif score >= 70:
        band, message = "ready_with_work", "جاهز بشرط: راجع المواضع الضعيفة أولاً."
    elif score >= 50:
        band, message = "not_ready", "لست جاهزاً بعد — تحتاج مراجعة منهجية ومحاكاة امتحان."
    else:
        band, message = "weak", "الاستعداد ضعيف — ابدأ بأساسيات الدرس قبل أي امتحان."

    next_steps: list[str] = []
    if coverage_score is not None and coverage_score < 100 and topics_remaining:
        next_steps.append(f"أنهِ دروس لم تبدأها: {topics_remaining[0]}")
    if weak_count:
        next_steps.append(f"راجع {weak_count} مواضيع ضعيفة من دفتر أخطائك")
    if not mocks:
        next_steps.append("حلّ امتحاناً محاكياً واحداً لقياس استعدادك الحقيقي")
    if review_rows and any(row.status == "due" for row in review_rows):
        due = sum(1 for row in review_rows if row.status == "due")
        next_steps.append(f"أكمل {due} مراجعة متأخرة")

    return {
        "subject_id": subject_id,
        "score": score,
        "band": band,
        "message": message,
        "factors": factors,
        "topics_remaining": topics_remaining,
        "next_steps": next_steps,
        "data_points": len(recent),
        "computed_at": utcnow().isoformat(),
    }


# --------------------------------------------------------------------------- #
# overview for the exams home
# --------------------------------------------------------------------------- #
def overview(db: Session, profile: StudentProfile) -> dict[str, Any]:
    active = (
        db.query(ExamAttempt)
        .filter(ExamAttempt.student_id == profile.id, ExamAttempt.status == "in_progress")
        .order_by(ExamAttempt.created_at.desc())
        .first()
    )
    upcoming = (
        db.query(Exam)
        .filter(Exam.student_id == profile.id, Exam.status == "upcoming")
        .order_by(Exam.exam_date.asc())
        .limit(5)
        .all()
    )
    recent = (
        db.query(ExamAttempt)
        .filter(ExamAttempt.student_id == profile.id, ExamAttempt.status != "in_progress")
        .order_by(ExamAttempt.finished_at.desc())
        .limit(10)
        .all()
    )
    subjects = (
        db.query(Subject)
        .join(StudentSubject, StudentSubject.subject_id == Subject.id)
        .filter(StudentSubject.profile_id == profile.id, StudentSubject.is_active.is_(True))
        .all()
    )

    mistakes_count = (
        db.query(func.count(Mistake.id))
        .filter(Mistake.student_id == profile.id, Mistake.is_active.is_(True))
        .scalar()
        or 0
    )

    return {
        "subjects": [
            {"id": subject.id, "name_ar": subject.name_ar, "readiness": readiness(db, profile.id, subject.id)}
            for subject in subjects
        ],
        "upcoming": [
            {
                "id": row.id,
                "title": row.title,
                "subject_id": row.subject_id,
                "exam_date": row.exam_date.isoformat() if row.exam_date else None,
                "duration_minutes": row.duration_minutes,
                "topics": row.topics or [],
                "days_left": (row.exam_date - utcnow().date()).days if row.exam_date else None,
            }
            for row in upcoming
        ],
        "active_attempt": (
            {
                "exam_attempt_id": active.id,
                "quiz_id": active.quiz_id,
                "title": (db.get(Quiz, active.quiz_id).title if db.get(Quiz, active.quiz_id) else ""),
                "time_left_seconds": _time_left(active),
            }
            if active
            else None
        ),
        "recent": [
            {
                "exam_attempt_id": row.id,
                "quiz_id": row.quiz_id,
                "title": (db.get(Quiz, row.quiz_id).title if db.get(Quiz, row.quiz_id) else ""),
                "status": row.status,
                "accuracy": (row.report or {}).get("accuracy"),
                "overtime": row.overtime,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in recent
        ],
        "mistakes_count": mistakes_count,
        "readiness_overall": readiness(db, profile.id, None),
        "bank": bank.bank_stats(db),
    }


__all__ = [
    "answer",
    "attempt_payload",
    "generate_exam",
    "get_attempt",
    "list_mistakes",
    "overview",
    "readiness",
    "resolve_mistake",
    "start_exam",
    "submit",
    "toggle_mark",
]
