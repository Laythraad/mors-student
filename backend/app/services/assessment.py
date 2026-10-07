"""Quiz generation, adaptive attempts and test reports.

Two generation paths:
* **AI** — richer, tied to the retrieved curriculum, requires sources.
* **Local** — deterministic fallback built from the lesson's own objectives
  and keywords, so a student with no API key still gets a real quiz.

Adaptive difficulty is code: correct → level up, wrong → level down, repeated
wrong on the same topic → weak topic → straight into the study plan.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..ai import AIRequest, ask, lesson_context, retrieve, chunks_to_context
from ..config import settings
from ..core.errors import NotFoundError, ValidationError
from ..db import (
    Lesson,
    Option,
    Question,
    QuestionFlag,
    Quiz,
    QuizAttempt,
    StudentProfile,
    StudentSubject,
    Subject,
    Answer,
    WeakTopic,
    utcnow,
)
from ..mors import EventType, bus
from . import bank
from .progress import register_weak, update_mastery
from .review import schedule_review

DIFFICULTY_BANDS = {1: "أساسي", 2: "سهل", 3: "متوسط", 4: "صعب", 5: "متقدم"}
MAX_QUESTIONS = 30


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #
def _ai_questions(
    db: Session,
    student_id: str,
    *,
    subject_id: str | None,
    lesson_id: str | None,
    count: int,
    difficulty: int,
    types: list[str],
) -> list[dict[str, Any]]:
    lesson_row = db.get(Lesson, lesson_id) if lesson_id else None
    chunks = retrieve(
        db,
        lesson_row.title if lesson_row else "",
        student_id=None,
        subject_id=subject_id,
        lesson_id=lesson_id,
        top_k=settings.rag_top_k,
    )
    context = "\n".join(
        filter(
            None,
            [
                lesson_context(db, lesson_id),
                chunks_to_context(chunks),
            ],
        )
    )
    schema = (
        'JSON فقط بالشكل: {"questions":[{"type":"mcq","prompt":"...","options":["...","...","...","..."],'
        '"answer_index":0,"explanation":"...","difficulty":3,"topic":"..."}]}'
    )
    answer = ask(
        db,
        AIRequest(
            task="quiz",
            input=(
                f"أنشئ {count} أسئلة بمستوى صعوبة {difficulty} "
                f"بالأنواع: {', '.join(types)}."
            ),
            student_id=student_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            context={"curriculum": context},
            constraints="لا تولّد معلومة غير موجودة في السياق. اذكر المصدر إن وُجد.",
            schema=schema,
            want_json=True,
            max_tokens=4096,
        ),
    )
    if not answer.data:
        return []
    raw = answer.data.get("questions") if isinstance(answer.data, dict) else None
    if not isinstance(raw, list):
        raw = [answer.data] if isinstance(answer.data, dict) else []
    return [q for q in raw if isinstance(q, dict) and q.get("prompt")][:MAX_QUESTIONS]


def _local_questions(
    lesson: Lesson | None,
    subject: Subject | None,
    *,
    count: int,
    difficulty: int,
    seed: str = "",
) -> list[dict[str, Any]]:
    """Deterministic fallback — never invents curriculum facts, only frames
    the lesson's own objectives/keywords as recall checks."""
    topics: list[str] = []
    if lesson:
        topics.extend([str(o) for o in (lesson.objectives or []) if o])
        topics.extend([str(k) for k in (lesson.keywords or []) if k])
        if lesson.title:
            topics.append(lesson.title)
    if not topics and subject:
        topics = [subject.name_ar]
    if not topics:
        topics = ["الدرس"]

    rng = random.Random(f"{seed}|{difficulty}|{count}")
    questions: list[dict[str, Any]] = []
    filler = [
        "أي مما يلي ينطبق على {topic}؟",
        "اختر العبارة الصحيحة المتعلقة بـ {topic}.",
        "حدّد المصطلح المطابق: {topic}",
    ]
    for index in range(min(count, 10)):
        topic = topics[index % len(topics)]
        prompt = rng.choice(filler).format(topic=topic)
        options = [
            f"التعريف الصحيح لـ {topic}",
            f"تعريف خاطئ شائع بخصوص {topic}",
            "لا علاقة له بالموضوع",
            "غير مذكور في الدرس",
        ]
        order = list(range(4))
        rng.shuffle(order)
        shuffled = [options[i] for i in order]
        answer_index = shuffled.index(options[0])
        questions.append(
            {
                "type": "mcq",
                "prompt": prompt,
                "options": shuffled,
                "answer_index": answer_index,
                "explanation": f"{topic} مذكور ضمن أهداف الدرس — راجع النص الأصلي.",
                "difficulty": max(1, min(5, difficulty + (1 if index % 3 == 0 else 0))),
                "topic": topic,
                "local": True,
            }
        )
    return questions


def generate_quiz(
    db: Session,
    student_id: str,
    *,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    title: str = "",
    kind: str = "quiz",
    count: int = 10,
    difficulty: int = 3,
    types: list[str] | None = None,
    source_scope: str = "curriculum",
) -> dict[str, Any]:
    count = max(1, min(MAX_QUESTIONS, count))
    difficulty = max(1, min(5, difficulty))
    types = types or ["mcq"]

    lesson = db.get(Lesson, lesson_id) if lesson_id else None
    if lesson and not subject_id:
        subject_id = lesson.subject_id
    subject = db.get(Subject, subject_id) if subject_id else None

    raw: list[dict[str, Any]] = []
    if source_scope in ("curriculum", "book", "sources"):
        raw = _ai_questions(
            db,
            student_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            count=count,
            difficulty=difficulty,
            types=types,
        )
    if len(raw) < count:
        raw.extend(
            _local_questions(lesson, subject, count=count - len(raw), difficulty=difficulty, seed=student_id)
        )

    quiz = Quiz(
        student_id=student_id,
        subject_id=subject_id,
        lesson_id=lesson_id,
        title=title or (f"اختبار {lesson.title}" if lesson else (f"اختبار {subject.name_ar}" if subject else "اختبار")),
        kind=kind,
        difficulty=difficulty,
        is_adaptive=True,
        source_scope=source_scope,
        generated_by="ai",
        status="ready",
    )
    db.add(quiz)
    db.flush()

    source_id = lesson.source_id if lesson else None
    for index, item in enumerate(raw[:count]):
        question = Question(
            quiz_id=quiz.id,
            type=item.get("type", "mcq") if item.get("type") in {"mcq", "true_false", "fill_blank", "short_answer", "problem", "essay", "calculation"} else "mcq",
            prompt=str(item.get("prompt", "")).strip(),
            explanation=str(item.get("explanation", "")),
            difficulty=max(1, min(5, int(item.get("difficulty", difficulty) or difficulty))),
            order=index,
            answer_key=str(item.get("answer_index", 0)),
            source_id=source_id if source_scope != "practice" else None,
            topic=str(item.get("topic", "")),
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
    return quiz_payload(db, quiz, include_answers=False)


def quiz_payload(db: Session, quiz: Quiz, *, include_answers: bool = False) -> dict[str, Any]:
    questions = []
    for question in sorted(quiz.questions, key=lambda q: q.order):
        options = sorted(question.options, key=lambda o: o.order)
        payload: dict[str, Any] = {
            "id": question.id,
            "type": question.type,
            "prompt": question.prompt,
            "difficulty": question.difficulty,
            "points": question.points,
            "topic": question.topic,
            "options": [
                {"id": o.id, "text": o.text, "correct": o.is_correct} if include_answers else {"id": o.id, "text": o.text}
                for o in options
            ],
        }
        if include_answers:
            payload["answer_key"] = question.answer_key
            payload["explanation"] = question.explanation
        payload["provenance"] = bank.provenance(question)
        questions.append(payload)
    return {
        "id": quiz.id,
        "title": quiz.title,
        "kind": quiz.kind,
        "difficulty": quiz.difficulty,
        "subject_id": quiz.subject_id,
        "lesson_id": quiz.lesson_id,
        "question_count": len(questions),
        "questions": questions,
    }


# --------------------------------------------------------------------------- #
# attempts
# --------------------------------------------------------------------------- #
def start_attempt(db: Session, student_id: str, quiz_id: str) -> QuizAttempt:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None or quiz.student_id != student_id:
        raise NotFoundError("الاختبار غير موجود.")
    existing = (
        db.query(QuizAttempt)
        .filter(
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.student_id == student_id,
            QuizAttempt.status == "in_progress",
        )
        .first()
    )
    if existing:
        return existing
    attempt = QuizAttempt(
        quiz_id=quiz_id,
        student_id=student_id,
        max_score=float(sum(q.points for q in quiz.questions)),
        started_at=utcnow(),
    )
    db.add(attempt)
    db.flush()
    bus.emit(db, student_id, EventType.QUIZ_STARTED, {"quiz_id": quiz_id, "attempt_id": attempt.id})
    return attempt


def _grade(db: Session, attempt: QuizAttempt, question: Question, student_answer: str) -> tuple[bool | None, float]:
    text = (student_answer or "").strip()
    if not text:
        return None, 0.0

    if question.type == "mcq" or question.type == "true_false":
        correct_ids = {o.id for o in question.options if o.is_correct}
        is_correct = text in correct_ids
        if not is_correct:
            # also accept a literal "0/1 index" answer from clients
            try:
                index = int(text)
                options = sorted(question.options, key=lambda o: o.order)
                is_correct = 0 <= index < len(options) and options[index].is_correct
            except ValueError:
                is_correct = False
        return is_correct, question.points if is_correct else 0.0

    key = (question.answer_key or "").strip().lower()
    if question.type == "fill_blank":
        accepted = [part.strip().lower() for part in key.split("|") if part.strip()]
        is_correct = text.lower() in accepted
    else:
        is_correct = text.lower() == key if key else False
    return is_correct, question.points if is_correct else 0.0


def submit_answer(
    db: Session,
    student_id: str,
    attempt_id: str,
    question_id: str,
    student_answer: str,
    *,
    time_seconds: int = 0,
    hint_used: bool = False,
) -> dict[str, Any]:
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.student_id != student_id:
        raise NotFoundError("المحاولة غير موجودة.")
    question = db.get(Question, question_id)
    if question is None or question.quiz_id != attempt.quiz_id:
        raise NotFoundError("السؤال غير موجود.")

    is_correct, points = _grade(db, attempt, question, student_answer)
    previous = (
        db.query(Answer)
        .filter(Answer.attempt_id == attempt.id, Answer.question_id == question_id)
        .first()
    )
    attempts_count = ((previous.attempts if previous else 0) or 0) + 1

    difficulty_before = question.difficulty
    difficulty_after = question.difficulty
    feedback = ""

    if is_correct:
        difficulty_after = min(5, question.difficulty + 1)
        feedback = "إجابة صحيحة."
    elif is_correct is False:
        difficulty_after = max(1, question.difficulty - 1)
        feedback = (
            "جرّب مرة ثانية — تلميح: ركّز على التعريف الأساسي."
            if attempts_count == 1
            else "خلّينا نشرحها بطريقة ثانية."
        )
    question.difficulty = difficulty_after

    if previous:
        previous.student_answer = student_answer
        previous.is_correct = is_correct
        previous.awarded_points = points
        previous.time_seconds = time_seconds
        previous.difficulty_before = difficulty_before
        previous.difficulty_after = difficulty_after
        previous.hint_used = hint_used
        previous.attempts = attempts_count
        previous.feedback = feedback
    else:
        db.add(
            Answer(
                attempt_id=attempt.id,
                question_id=question_id,
                student_answer=student_answer,
                is_correct=is_correct,
                awarded_points=points,
                time_seconds=time_seconds,
                difficulty_before=difficulty_before,
                difficulty_after=difficulty_after,
                hint_used=hint_used,
                attempts=attempts_count,
                feedback=feedback,
            )
        )
    db.flush()

    if question.topic or (question.quiz.lesson_id is None):
        topic = question.topic or question.prompt[:60]
        update_mastery(
            db,
            student_id,
            subject_id=question.quiz.subject_id,
            lesson_id=question.quiz.lesson_id,
            topic=topic,
            correct=bool(is_correct),
        )
    if is_correct is False and question.topic:
        row, created = register_weak(
            db,
            student_id,
            topic=question.topic,
            subject_id=question.quiz.subject_id,
            lesson_id=question.quiz.lesson_id,
        )
        if created:
            bus.emit(
                db,
                student_id,
                EventType.WEAK_TOPIC_DETECTED,
                {"topic": question.topic, "subject_id": question.quiz.subject_id},
            )
    event = (
        EventType.QUIZ_QUESTION_CORRECT
        if is_correct
        else EventType.QUIZ_QUESTION_MISSED
    )
    bus.emit(
        db,
        student_id,
        event,
        {
            "question_id": question_id,
            "topic": question.topic,
            "consecutive_errors": 0 if is_correct else 1,
        },
    )

    return {
        "correct": is_correct,
        "points": points,
        "feedback": feedback,
        "difficulty_before": difficulty_before,
        "difficulty_after": difficulty_after,
        "explanation": question.explanation,
        # revealed only after the student answered — the client needs it to teach
        "correct_option": next(
            ({"id": o.id, "text": o.text} for o in question.options if o.is_correct),
            None,
        ),
        "provenance": bank.provenance(question),
        "attempts": attempts_count,
    }


def finish_attempt(db: Session, student_id: str, attempt_id: str) -> dict[str, Any]:
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.student_id != student_id:
        raise NotFoundError("المحاولة غير موجودة.")
    if attempt.status == "finished":
        return attempt_report(db, attempt)

    answers = db.query(Answer).filter(Answer.attempt_id == attempt.id).all()
    question_map = {q.id: q for q in db.query(Question).filter(Question.quiz_id == attempt.quiz_id).all()}
    quiz = db.get(Quiz, attempt.quiz_id)
    correct = sum(1 for a in answers if a.is_correct)
    wrong = sum(1 for a in answers if a.is_correct is False)
    skipped = max(0, len(question_map) - len(answers))
    score = sum(a.awarded_points for a in answers)
    max_score = float(sum(q.points for q in quiz.questions)) if quiz else 0.0

    attempt.score = score
    attempt.max_score = max_score
    attempt.accuracy = round(score / max_score * 100, 1) if max_score else 0.0
    attempt.correct_count = correct
    attempt.wrong_count = wrong
    attempt.skipped_count = skipped
    attempt.finished_at = utcnow()
    attempt.time_seconds = int(
        max(0, ((attempt.finished_at or utcnow()) - attempt.started_at).total_seconds())
    )
    attempt.status = "finished"

    weak_topics = sorted(
        {
            question_map[a.question_id].topic
            for a in answers
            if a.is_correct is False and a.question_id in question_map and question_map[a.question_id].topic
        }
    )
    strong_topics = sorted(
        {
            question_map[a.question_id].topic
            for a in answers
            if a.is_correct and a.question_id in question_map and question_map[a.question_id].topic
        }
    )
    previous = (
        db.query(QuizAttempt)
        .filter(
            QuizAttempt.student_id == student_id,
            QuizAttempt.id != attempt.id,
            QuizAttempt.status == "finished",
        )
        .order_by(QuizAttempt.finished_at.desc())
        .first()
    )
    attempt.report = {
        "weak_topics": weak_topics,
        "strong_topics": strong_topics,
        "previous_accuracy": previous.accuracy if previous else None,
        "delta": round(attempt.accuracy - (previous.accuracy or 0), 1) if previous else None,
    }

    if quiz and quiz.lesson_id:
        schedule_review(
            db,
            student_id,
            lesson_id=quiz.lesson_id,
            subject_id=quiz.subject_id,
            topic=(db.get(Lesson, quiz.lesson_id).title if db.get(Lesson, quiz.lesson_id) else ""),
            quality=5 if attempt.accuracy >= 85 else (4 if attempt.accuracy >= 70 else (3 if attempt.accuracy >= 55 else 1)),
        )

    passed = attempt.accuracy >= 60
    payload = {
        "quiz_id": attempt.quiz_id,
        "attempt_id": attempt.id,
        "score": attempt.accuracy,
        "previous": attempt.report.get("previous_accuracy"),
        "weak_topics": weak_topics,
        "strong_topics": strong_topics,
        "foundation_weak": bool(weak_topics) and attempt.accuracy >= 80,
        "kind": quiz.kind if quiz else "quiz",
    }
    bus.emit(db, student_id, EventType.QUIZ_COMPLETED, payload)
    if quiz and quiz.kind in ("exam", "diagnostic"):
        bus.emit(
            db,
            student_id,
            EventType.EXAM_PASSED if passed else EventType.EXAM_FAILED,
            payload,
        )
    if quiz and quiz.kind == "diagnostic":
        profile = db.get(StudentProfile, student_id)
        if profile is not None and not profile.diagnostic_done:
            profile.diagnostic_done = True  # onboarding "diagnostic" step

    # §40 — a post-video quiz decides whether the lesson closes
    video_id = (quiz.meta or {}).get("video_id") if quiz else None
    if video_id:
        from . import videos as videos_service  # local import: videos imports this module

        try:
            videos_service.record_video_quiz(db, student_id, str(video_id), attempt.id)
        except (NotFoundError, ValidationError):
            # a deleted video must never break quiz grading
            pass

    db.flush()
    return attempt_report(db, attempt)


def _given_text(db: Session, question: Question, answer: Answer) -> str:
    """Human wording for what the student chose (MCQ answers are option ids)."""
    raw = (answer.student_answer or "").strip()
    if not raw:
        return ""
    if question.type in ("mcq", "true_false"):
        option = db.get(Option, raw)
        if option is not None:
            return option.text
        options = sorted(question.options, key=lambda o: o.order)
        try:
            index = int(raw)
            if 0 <= index < len(options):
                return options[index].text
        except ValueError:
            pass
    return raw


def attempt_report(db: Session, attempt: QuizAttempt) -> dict[str, Any]:
    quiz = db.get(Quiz, attempt.quiz_id)
    answers = db.query(Answer).filter(Answer.attempt_id == attempt.id).all()
    by_question = {a.question_id: a for a in answers}
    mistakes = []
    for question in quiz.questions if quiz else []:
        answer = by_question.get(question.id)
        if answer is None:
            mistakes.append(
                {
                    "question_id": question.id,
                    "question": question.prompt,
                    "given": "",
                    "topic": question.topic,
                    "skipped": True,
                }
            )
        elif answer.is_correct is False:
            mistakes.append(
                {
                    "question_id": question.id,
                    "question": question.prompt,
                    "given": _given_text(db, question, answer),
                    "topic": question.topic,
                    "explanation": question.explanation,
                    "provenance": bank.provenance(question),
                }
            )
    report = attempt.report or {}
    return {
        "attempt_id": attempt.id,
        "quiz_id": attempt.quiz_id,
        "title": quiz.title if quiz else "",
        "score": round(attempt.score, 2),
        "max_score": attempt.max_score,
        "accuracy": attempt.accuracy,
        "correct": attempt.correct_count,
        "wrong": attempt.wrong_count,
        "skipped": attempt.skipped_count,
        "time_seconds": attempt.time_seconds,
        "mistakes": mistakes,
        "weak_topics": report.get("weak_topics", []),
        "strong_topics": report.get("strong_topics", []),
        "previous_accuracy": report.get("previous_accuracy"),
        "delta": report.get("delta"),
        "recommended_review": report.get("weak_topics", [])[:4],
        "next_test_days": _next_test_days(attempt.accuracy),
        "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
    }


def _next_test_days(accuracy: float) -> int:
    if accuracy >= 85:
        return 7
    if accuracy >= 70:
        return 4
    if accuracy >= 55:
        return 2
    return 1


def diagnostic_quiz(db: Session, student_id: str, *, subject_ids: list[str], count: int = 12) -> dict[str, Any]:
    """Short placement test offered during onboarding (never blocking)."""
    lessons = (
        db.query(Lesson)
        .filter(Lesson.subject_id.in_(subject_ids or [""]))
        .order_by(Lesson.index)
        .limit(count)
        .all()
    )
    if not lessons:
        raise ValidationError("ما موجود دروس لهذه المواد بعد.")
    return generate_quiz(
        db,
        student_id,
        subject_id=lessons[0].subject_id,
        lesson_id=lessons[0].id,
        title="اختبار تحديد المستوى",
        kind="diagnostic",
        count=min(count, 10),
        difficulty=2,
    )


# --------------------------------------------------------------------------- #
# §3 inspiration — "flag this question" for a human teacher
# --------------------------------------------------------------------------- #
def flag_question(
    db: Session, student_id: str, question_id: str, *, kind: str, detail: str = ""
) -> dict[str, Any]:
    question = db.get(Question, question_id)
    if question is None:
        raise NotFoundError("السؤال غير موجود.")
    quiz = db.get(Quiz, question.quiz_id) if question.quiz_id else None
    if quiz is not None and quiz.student_id != student_id:
        # bank questions (quiz_id None) are shared, generated quizzes are not
        raise NotFoundError("السؤال غير موجود.")

    row = QuestionFlag(
        student_id=student_id,
        question_id=question.id,
        quiz_id=quiz.id if quiz else None,
        lesson_id=question.lesson_id or (quiz.lesson_id if quiz else None),
        kind=kind,
        detail=(detail or "").strip()[:500],
    )
    db.add(row)
    db.flush()
    return {
        "flag_id": row.id,
        "status": row.status,
        "message": "وصل البلاغ — يراجعه فريق المحتوى.",
    }


def list_question_flags(db: Session, *, status: str | None = None, limit: int = 100) -> dict[str, Any]:
    q = db.query(QuestionFlag).order_by(QuestionFlag.created_at.desc())
    if status:
        q = q.filter(QuestionFlag.status == status)
    rows = q.limit(limit).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        question = db.get(Question, row.question_id) if row.question_id else None
        quiz = db.get(Quiz, row.quiz_id) if row.quiz_id else None
        profile = db.get(StudentProfile, row.student_id)
        user = profile.user if profile else None
        items.append(
            {
                "id": row.id,
                "kind": row.kind,
                "detail": row.detail,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                "question": {
                    "id": row.question_id,
                    "prompt": (question.prompt[:200] if question else ""),
                },
                "quiz": {"id": row.quiz_id, "title": quiz.title if quiz else ""},
                "lesson_id": row.lesson_id,
                "student": user.full_name if user else "",
            }
        )
    return {"flags": items, "open": sum(1 for r in rows if r.status == "open")}


def resolve_question_flag(db: Session, flag_id: str) -> dict[str, Any]:
    row = db.get(QuestionFlag, flag_id)
    if row is None:
        raise NotFoundError("البلاغ غير موجود.")
    row.status = "resolved"
    row.resolved_at = utcnow()
    db.flush()
    return {"flag_id": row.id, "status": row.status}


# --------------------------------------------------------------------------- #
# §3 inspiration — daily quick quiz (2–3 questions, server clock only)
# --------------------------------------------------------------------------- #
BAGHDAD_UTC_OFFSET = timedelta(hours=3)  # config.default_timezone = Asia/Baghdad (no DST)
DAILY_QUESTIONS = 3


def _local_today() -> date:
    """Calendar day in the student's zone, from the server clock (never the device)."""
    return (utcnow() + BAGHDAD_UTC_OFFSET).date()


def _local_day_start_utc() -> datetime:
    """First instant of that day, expressed as naive UTC (storage convention)."""
    midnight_local = datetime.combine(_local_today(), datetime.min.time())
    return midnight_local - BAGHDAD_UTC_OFFSET


def daily_quiz_row(db: Session, student_id: str) -> Quiz | None:
    return (
        db.query(Quiz)
        .filter(
            Quiz.student_id == student_id,
            Quiz.kind == "daily",
            Quiz.created_at >= _local_day_start_utc(),
        )
        .order_by(Quiz.created_at.desc())
        .first()
    )


def _daily_subject_id(db: Session, student_id: str) -> str | None:
    """Weakest active subject first, else the student's highest-priority choice."""
    weak = (
        db.query(WeakTopic)
        .filter(
            WeakTopic.student_id == student_id,
            WeakTopic.subject_id.is_not(None),
            WeakTopic.is_active.is_(True),
        )
        .order_by(WeakTopic.updated_at.desc())
        .limit(1)
        .first()
    )
    if weak is not None and weak.subject_id:
        return weak.subject_id
    chosen = (
        db.query(StudentSubject)
        .filter(StudentSubject.profile_id == student_id, StudentSubject.is_active.is_(True))
        .order_by(StudentSubject.priority.asc(), StudentSubject.created_at.asc())
        .first()
    )
    if chosen is not None:
        return chosen.subject_id
    subject = db.query(Subject).order_by(Subject.name_ar).first()
    return subject.id if subject else None


def daily_status(db: Session, student_id: str) -> dict[str, Any]:
    quiz = daily_quiz_row(db, student_id)
    if quiz is None:
        return {
            "available": True,
            "generated": False,
            "question_count": DAILY_QUESTIONS,
            "completed": False,
            "day": _local_today().isoformat(),
        }
    attempt = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.quiz_id == quiz.id, QuizAttempt.student_id == student_id)
        .order_by(QuizAttempt.started_at.desc())
        .first()
    )
    finished = attempt is not None and attempt.status == "finished"
    return {
        "available": True,
        "generated": True,
        "quiz_id": quiz.id,
        "title": quiz.title,
        "question_count": len(quiz.questions),
        "subject_id": quiz.subject_id,
        "attempt_id": attempt.id if attempt else None,
        "completed": finished,
        "accuracy": attempt.accuracy if finished else None,
        "day": _local_today().isoformat(),
    }


def ensure_daily_quiz(db: Session, student_id: str) -> dict[str, Any]:
    """One quick quiz per student per day — reused until it exists."""
    existing = daily_quiz_row(db, student_id)
    if existing is not None:
        payload = dict(quiz_payload(db, existing, include_answers=False))
        payload.update({"reused": True, "day": _local_today().isoformat()})
        return payload
    payload = generate_quiz(
        db,
        student_id,
        subject_id=_daily_subject_id(db, student_id),
        title="اختبار اليوم",
        kind="daily",
        count=DAILY_QUESTIONS,
        difficulty=3,
    )
    payload.update({"reused": False, "day": _local_today().isoformat()})
    return payload


__all__ = [
    "generate_quiz",
    "quiz_payload",
    "start_attempt",
    "submit_answer",
    "finish_attempt",
    "attempt_report",
    "diagnostic_quiz",
    "flag_question",
    "list_question_flags",
    "resolve_question_flag",
    "daily_status",
    "ensure_daily_quiz",
    "DAILY_QUESTIONS",
    "DIFFICULTY_BANDS",
]
