"""المرشد الطلابي — the advisor that reads the whole journey (§22–§24, §58, §88).

Rules first: every problem it reports is backed by real rows (mastery, weak
topics, repeated mistakes, review debt, plan completion), every problem carries
a concrete solution, and every solution has an `apply` action that actually
changes the system — reviews, quizzes, sessions, difficulty, the plan itself.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.errors import NotFoundError, ValidationError
from ..db import (
    CalendarEvent,
    Exam,
    ExamAttempt,
    Lesson,
    LearningProfile,
    MasteryScore,
    Mistake,
    Quiz,
    QuizAttempt,
    Review,
    StudentProfile,
    StudentSubject,
    StudyPlan,
    StudySession,
    StudyStreak,
    Subject,
    Task,
    WeakTopic,
    utcnow,
)
from . import assessment, bank, planner
from . import exams as exams_service
from .dashboard import weekly_summary
from .progress import active_weak, progress_report
from .review import due_reviews, schedule_review

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
AR_DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


# --------------------------------------------------------------------------- #
# §22 — the questions the advisor asks (answered from data, not interviews)
# --------------------------------------------------------------------------- #
def student_context(db: Session, student_id: str) -> dict[str, Any]:
    profile = db.get(StudentProfile, student_id)
    subjects = (
        db.query(Subject)
        .join(StudentSubject, StudentSubject.subject_id == Subject.id)
        .filter(StudentSubject.profile_id == student_id, StudentSubject.is_active.is_(True))
        .all()
    )
    exam = (
        db.query(Exam)
        .filter(Exam.student_id == student_id, Exam.status == "upcoming")
        .order_by(Exam.exam_date.asc())
        .first()
    )
    weak = active_weak(db, student_id, 5)
    streak = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).first()
    return {
        "goal": (profile.goals if profile else "") or "",
        "daily_study_minutes": profile.daily_study_minutes if profile else 0,
        "goal_date": profile.goal_date.isoformat() if profile and profile.goal_date else None,
        "subjects": [
            {"id": s.id, "name_ar": s.name_ar, "color": s.color or "#2f8ff7"} for s in subjects
        ],
        "next_exam": (
            {
                "title": exam.title,
                "exam_date": exam.exam_date.isoformat() if exam.exam_date else None,
                "days_left": (exam.exam_date - utcnow().date()).days if exam.exam_date else None,
            }
            if exam
            else None
        ),
        "stuck_at": [w.topic for w in weak],
        "streak": streak.current if streak else 0,
    }


# --------------------------------------------------------------------------- #
# per-subject picture (shared by report + priorities)
# --------------------------------------------------------------------------- #
def _subject_stats(db: Session, student_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(StudentSubject, Subject)
        .join(Subject, Subject.id == StudentSubject.subject_id)
        .filter(StudentSubject.profile_id == student_id, StudentSubject.is_active.is_(True))
        .all()
    )
    stats: list[dict[str, Any]] = []
    for link, subject in rows:
        mastery = (
            db.query(MasteryScore)
            .filter(MasteryScore.student_id == student_id, MasteryScore.subject_id == subject.id)
            .all()
        )
        avg_mastery = round(sum(m.score for m in mastery) / len(mastery), 1) if mastery else None
        attempts = (
            db.query(QuizAttempt, Quiz)
            .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
            .filter(QuizAttempt.student_id == student_id, QuizAttempt.status == "finished", Quiz.subject_id == subject.id)
            .order_by(QuizAttempt.finished_at.desc())
            .limit(10)
            .all()
        )
        accuracy = round(sum(a.accuracy for a, _ in attempts) / len(attempts), 1) if attempts else None
        weak_count = (
            db.query(func.count(WeakTopic.id))
            .filter(
                WeakTopic.student_id == student_id,
                WeakTopic.subject_id == subject.id,
                WeakTopic.is_active.is_(True),
            )
            .scalar()
            or 0
        )
        score = avg_mastery if avg_mastery is not None else accuracy
        stats.append(
            {
                "subject_id": subject.id,
                "name_ar": subject.name_ar,
                "color": subject.color or "#2f8ff7",
                "mastery": avg_mastery,
                "attempts": len(attempts),
                "accuracy": accuracy,
                "weak_topics": weak_count,
                "score": score,
                "readiness": exams_service.readiness(db, student_id, subject.id),
            }
        )
    stats.sort(key=lambda s: (s["score"] is None, -(s["score"] or 0)))
    return stats


# --------------------------------------------------------------------------- #
# §23 — Student Success Report (problem + solution for each finding)
# --------------------------------------------------------------------------- #
def success_report(db: Session, student_id: str) -> dict[str, Any]:
    subject_stats = _subject_stats(db, student_id)
    weak = active_weak(db, student_id, 12)
    mistakes = db.query(Mistake).filter(Mistake.student_id == student_id, Mistake.is_active.is_(True)).all()
    profile = db.get(StudentProfile, student_id)
    report = progress_report(db, student_id)
    week = weekly_summary(db, student_id)

    strong_subjects = [
        {"subject_id": s["subject_id"], "name_ar": s["name_ar"], "score": s["score"]}
        for s in subject_stats
        if s["score"] is not None and s["score"] >= 75
    ]
    weak_subjects = [
        {"subject_id": s["subject_id"], "name_ar": s["name_ar"], "score": s["score"]}
        for s in subject_stats
        if s["score"] is not None and s["score"] < 55
    ]

    problems: list[dict[str, Any]] = []

    # 1) weak topics → active recall + spaced repetition
    if weak:
        topics = [w.topic for w in weak[:4]]
        problems.append(
            {
                "key": "weak_topics",
                "severity": "high" if any(w.severity >= 3 for w in weak) else "medium",
                "title": f"تتعثر في {len(weak)} مواضيع",
                "evidence": topics,
                "solution": "زد التذكّر النشط: سؤال واحد مغلق عن كل موضوع يومياً + مراجعة متباعدة كل 3 أيام.",
                "action_key": "add_review",
                "action_label": "أضف مراجعة متباعدة الآن",
            }
        )

    # 2) repeated mistakes (same prompt / same topic more than once)
    by_topic: dict[str, int] = {}
    for row in mistakes:
        key = row.topic or bank.normalize_prompt(row.prompt)[:40]
        by_topic[key] = by_topic.get(key, 0) + 1
    repeated = {k: v for k, v in by_topic.items() if v >= 2}
    if repeated:
        worst = sorted(repeated.items(), key=lambda kv: -kv[1])[:3]
        problems.append(
            {
                "key": "repeated_mistakes",
                "severity": "high" if max(repeated.values()) >= 3 else "medium",
                "title": "أخطاء تتكرر",
                "evidence": [f"{k} × {v}" for k, v in worst],
                "solution": "اختبار قصير 5 أسئلة على نفس المواضع + اكتب بخطوتك سبب الخطأ قبل إعادة المحاولة.",
                "action_key": "add_quiz",
                "action_label": "أنشئ اختباراً قصيراً",
            }
        )

    # 3) study habits — abandoned sessions / broken streak
    profile_row = db.query(LearningProfile).filter(LearningProfile.student_id == student_id).first()
    completion = profile_row.session_completion_rate if profile_row else None
    abandoned = profile_row.sessions_abandoned if profile_row else 0
    streak = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).first()
    habit_evidence: list[str] = []
    if completion is not None and completion < 0.6:
        habit_evidence.append(f"أنجزت {int(completion * 100)}% من جلساتك فقط")
    if abandoned:
        habit_evidence.append(f"{abandoned} جلسة تُركت دون إنهاء")
    if streak is None or streak.current == 0:
        habit_evidence.append("لا توجد سلسلة دراسة حالياً")
    if habit_evidence:
        problems.append(
            {
                "key": "study_habits",
                "severity": "medium",
                "title": "عادات الدراسة غير ثابتة",
                "evidence": habit_evidence,
                "solution": "قسّم الجلسات إلى 25 دقيقة بتركيز كامل + راحة 5، وابدأ بجلسة واحدة يومياً تُنجزها فعلاً.",
                "action_key": "add_session",
                "action_label": "جدّل جلسة قريبة",
            }
        )

    # 4) time management — plan heavier than reality
    health = plan_health(db, student_id)
    if health.get("overloaded"):
        problems.append(
            {
                "key": "time_management",
                "severity": "high",
                "title": "الخطة أكبر من وقتك",
                "evidence": health["evidence"],
                "solution": health["suggestion"],
                "action_key": "adjust_plan",
                "action_label": "عدّل الخطة",
                "requires_approval": True,
            }
        )
    elif profile and week.get("minutes") is not None and week["minutes"] < profile.daily_study_minutes * 0.4:
        problems.append(
            {
                "key": "time_management",
                "severity": "low",
                "title": "وقت الدراسة أقل من هدفك",
                "evidence": [
                    f"هدفك {profile.daily_study_minutes} دقيقة يومياً — أنجزت {week['minutes']} دقيقة هذا الأسبوع"
                ],
                "solution": "احجز نافذة زمنية ثابتة واحدة يومياً بدل الاعتماد على الفراغ.",
                "action_key": "add_session",
                "action_label": "احجز نافذة دراسة",
            }
        )

    # 5) review debt
    pressure = _review_pressure(db, student_id)
    if pressure["overdue"] >= 3 or pressure["lapses"] >= 3:
        problems.append(
            {
                "key": "review_problems",
                "severity": "high" if pressure["overdue"] >= 6 else "medium",
                "title": "مراجعات متأخرة",
                "evidence": [f"{pressure['overdue']} مراجعة متأخرة", f"{pressure['lapses']} تعثر في الاسترجاع"],
                "solution": "راجع المستحق أولاً بجلسات 10 دقائق — التأخير يمسح التعلّم أسرع من نقص الجلسة.",
                "action_key": "add_review",
                "action_label": "رتّب المراجعات",
            }
        )

    # 6) exam problems
    exam_evidence = _exam_problems(db, student_id)
    if exam_evidence["evidence"]:
        problems.append(
            {
                "key": "exam_problems",
                "severity": "high" if exam_evidence.get("hard") else "medium",
                "title": "مشكلات في الامتحانات",
                "evidence": exam_evidence["evidence"],
                "solution": "امتحان محاكاة أسبوعي بمؤقّت + مراجعة دفتر أخطائك قبل الامتحان الحقيقي بليلة.",
                "action_key": "start_mock",
                "action_label": "ابدأ محاكاة الآن",
            }
        )

    problems.sort(key=lambda p: SEVERITY_ORDER.get(p["severity"], 3))

    return {
        "strong_subjects": strong_subjects,
        "weak_subjects": weak_subjects,
        "weak_topics": [
            {"topic": w.topic, "severity": w.severity, "errors": w.errors, "subject_id": w.subject_id}
            for w in weak
        ],
        "repeated_mistakes": [
            {"topic": k, "count": v}
            for k, v in sorted(by_topic.items(), key=lambda kv: -kv[1])
            if v >= 2
        ],
        "study_habits": {
            "sessions": report["totals"]["sessions"],
            "week_minutes": report["totals"]["week_minutes"],
            "week_sessions": report["totals"]["week_sessions"],
            "streak": report["streak"]["current"],
            "completion_rate": completion,
            "abandoned": abandoned,
        },
        "time_management": {
            "daily_target": profile.daily_study_minutes if profile else 0,
            "week_minutes": week.get("minutes", 0),
            "plan_completion": health.get("completion"),
        },
        "review_problems": pressure,
        "exam_problems": exam_evidence,
        "problems": problems,
        "subjects": subject_stats,
        "generated_at": utcnow().isoformat(),
    }


def _review_pressure(db: Session, student_id: str) -> dict[str, Any]:
    now = utcnow()
    rows = db.query(Review).filter(Review.student_id == student_id, Review.status != "done").all()
    overdue = 0
    for row in rows:
        due = row.due_at
        if due is None:
            continue
        if due.tzinfo is None and now.tzinfo is not None:
            due = due.replace(tzinfo=now.tzinfo)
        if due < now:
            overdue += 1
    lapses = sum(row.lapses for row in rows)
    return {
        "pending": len(rows),
        "overdue": overdue,
        "lapses": lapses,
        "due_today": len(due_reviews(db, student_id, horizon_days=1)),
    }


def _exam_problems(db: Session, student_id: str) -> dict[str, Any]:
    attempts = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.student_id == student_id, QuizAttempt.status == "finished")
        .order_by(QuizAttempt.finished_at.desc())
        .limit(10)
        .all()
    )
    evidence: list[str] = []
    hard = False
    if attempts:
        avg = sum(a.accuracy for a in attempts) / len(attempts)
        if avg < 60:
            evidence.append(f"متوسط نتائجك {round(avg)}% في آخر {len(attempts)} اختباراً")
            hard = True
        skipped = sum(a.skipped_count for a in attempts)
        total_q = sum(a.correct_count + a.wrong_count + a.skipped_count for a in attempts)
        if total_q and skipped / total_q > 0.25:
            evidence.append(f"تترك {int(skipped / total_q * 100)}% من الأسئلة دون إجابة")
    expired = (
        db.query(func.count(ExamAttempt.id))
        .filter(ExamAttempt.student_id == student_id, ExamAttempt.overtime.is_(True))
        .scalar()
        or 0
    )
    if expired:
        evidence.append(f"تجاوزت وقت الامتحان {expired} مرة")
        hard = True
    return {"evidence": evidence, "hard": hard, "overtime": expired, "quizzes": len(attempts)}


# --------------------------------------------------------------------------- #
# §58 — is the schedule realistic?
# --------------------------------------------------------------------------- #
def plan_health(db: Session, student_id: str) -> dict[str, Any]:
    horizon = utcnow().date() - timedelta(days=14)
    tasks = (
        db.query(Task)
        .filter(Task.student_id == student_id, Task.scheduled_date >= horizon)
        .all()
    )
    if not tasks:
        return {
            "available": False,
            "realistic": None,
            "completion": None,
            "total": 0,
            "overloaded": False,
            "message": "لا توجد خطة سارية — أنشئ خطة لأسبوعك أولاً.",
            "suggestion": "ولّد خطة أسبوعية من صفحة خطتي.",
            "evidence": [],
            "action_key": "adjust_plan",
        }
    completed = sum(1 for t in tasks if t.status == "completed")
    postponed = sum(1 for t in tasks if t.status in ("postponed", "skipped"))
    total = len(tasks)
    completion = round(completed / total, 2)
    overloaded = total >= 4 and completion < 0.6
    evidence = [f"{completed}/{total} مهمة مُنجزة خلال 14 يوماً"]
    if postponed:
        evidence.append(f"{postponed} مهمة مؤجلة أو متروكة")
    if overloaded:
        message = "جدولك أثقل مما تُنجزه فعلاً — الاستمرار عليه يخلق تأخيراً متراكماً."
        suggestion = f"قلّل إلى {max(3, round(total / 14 * 0.6))} مهام يومياً واجعل المراجعة قبل الدرس الجديد."
    else:
        message = "الجدول واقعي — أنجزت أكثر من نصف مهامك، واصل بنفس الإيقاع."
        suggestion = "حافظ على نفس عدد المهام، وأضف مراجعة واحدة فقط."
    return {
        "available": True,
        "realistic": not overloaded,
        "overloaded": overloaded,
        "completion": completion,
        "total": total,
        "completed": completed,
        "postponed": postponed,
        "message": message,
        "suggestion": suggestion,
        "evidence": evidence,
        "action_key": "adjust_plan",
    }


# --------------------------------------------------------------------------- #
# §89 — weekly learning report
# --------------------------------------------------------------------------- #
def weekly_review(db: Session, student_id: str) -> dict[str, Any]:
    week_ago = utcnow() - timedelta(days=7)
    summary = weekly_summary(db, student_id)
    weak = active_weak(db, student_id, 6)

    completed_lessons = (
        db.query(func.count(MasteryScore.id))
        .filter(MasteryScore.student_id == student_id, MasteryScore.updated_at >= week_ago)
        .scalar()
        or 0
    )
    tasks = (
        db.query(Task)
        .filter(Task.student_id == student_id, Task.status.in_(["completed", "skipped", "postponed"]))
        .all()
    )
    recent_tasks = [t for t in tasks if t.completed_at and t.completed_at >= week_ago]
    missed = sum(
        1
        for t in tasks
        if t.scheduled_date
        and t.scheduled_date >= week_ago.date()
        and t.status in ("skipped", "postponed")
    )
    deltas = [
        (t.mastery_after - t.mastery_before)
        for t in recent_tasks
        if t.mastery_before is not None and t.mastery_after is not None
    ]
    interrupted = (
        db.query(func.count(StudySession.id))
        .filter(
            StudySession.student_id == student_id,
            StudySession.status == "interrupted",
            StudySession.started_at >= week_ago,
        )
        .scalar()
        or 0
    )

    improvement = "flat"
    if summary.get("trend") == "up":
        improvement = "up"
    elif summary.get("trend") == "down":
        improvement = "down"
    elif deltas and sum(deltas) > 1:
        improvement = "up"
    elif deltas and sum(deltas) < -1:
        improvement = "down"

    context = student_context(db, student_id)
    next_week: list[dict[str, Any]] = []
    for topic in [w.topic for w in weak[:3]]:
        next_week.append({"title": f"مراجعة نشطة: {topic}", "minutes": 20, "reason": "موضع ضعيف متكرر"})
    due = len(due_reviews(db, student_id, horizon_days=7))
    if due:
        next_week.append({"title": f"{due} مراجعة متباعدة مستحقة", "minutes": 15, "reason": "منع النسيان"})
    if context["next_exam"]:
        next_week.append(
            {
                "title": f"تجهيز: {context['next_exam']['title']}",
                "minutes": 45,
                "reason": f"باقي {context['next_exam']['days_left']} يوم",
            }
        )
    if not next_week:
        next_week.append({"title": "اختبار قصير على أحدث درس", "minutes": 25, "reason": "تثبيت التقدّم"})

    return {
        "study_hours": round((summary.get("minutes") or 0) / 60, 1),
        "sessions": summary.get("sessions", 0),
        "completed_lessons": completed_lessons,
        "quiz_average": summary.get("average_accuracy"),
        "quiz_count": summary.get("quizzes", 0),
        "mastery_changes": {
            "improved": sum(1 for d in deltas if d > 0),
            "dropped": sum(1 for d in deltas if d < 0),
            "avg_delta": round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
        },
        "weak_topics": [
            {"topic": w.topic, "severity": w.severity, "errors": w.errors} for w in weak
        ],
        "missed_sessions": missed + interrupted,
        "improvement": improvement,
        "next_week_plan": next_week,
        "trend": summary.get("trend", "flat"),
        "generated_at": utcnow().isoformat(),
    }


# --------------------------------------------------------------------------- #
# §24 — concrete actions the advisor can take (after the student agrees)
# --------------------------------------------------------------------------- #
def _focus_lesson(db: Session, student_id: str) -> tuple[Lesson | None, Subject | None, str]:
    weak = active_weak(db, student_id, 1)
    lesson = None
    subject = None
    topic = ""
    if weak:
        topic = weak[0].topic
        if weak[0].lesson_id:
            lesson = db.get(Lesson, weak[0].lesson_id)
        if weak[0].subject_id:
            subject = db.get(Subject, weak[0].subject_id)
    if lesson is None and subject is None:
        stats = _subject_stats(db, student_id)
        weakest = [s for s in stats if s["score"] is not None]
        chosen = weakest[-1] if weakest else (stats[0] if stats else None)
        if chosen:
            subject = db.get(Subject, chosen["subject_id"])
    if lesson is None and subject is None:
        link = (
            db.query(StudentSubject)
            .filter(StudentSubject.profile_id == student_id, StudentSubject.is_active.is_(True))
            .order_by(StudentSubject.priority)
            .first()
        )
        if link:
            subject = db.get(Subject, link.subject_id)
    if lesson is None and subject is not None:
        lesson = db.query(Lesson).filter(Lesson.subject_id == subject.id).order_by(Lesson.index).first()
    return lesson, subject, topic


def steps(db: Session, student_id: str) -> list[dict[str, Any]]:
    lesson, subject, topic = _focus_lesson(db, student_id)
    weak = active_weak(db, student_id, 1)
    health = plan_health(db, student_id)
    base_difficulty = 3
    if weak:
        base_difficulty = max(1, weak[0].severity if weak[0].severity else 3)

    return [
        {
            "key": "add_review",
            "title": f"أضف مراجعة متباعدة: {topic or (lesson.title if lesson else 'أضعف موضوع')}",
            "detail": "تظهر في خطتك خلال يوم وتسحبها من المراجعات المتأخرة.",
            "available": bool(weak or lesson),
            "requires_approval": False,
            "kind": "review",
        },
        {
            "key": "add_quiz",
            "title": f"اختبار قصير 5 أسئلة على {topic or (lesson.title if lesson else (subject.name_ar if subject else 'المادة'))}",
            "detail": "يُبنى من البنك والمنهج بمستوى أهدأ من مستواك الحالي.",
            "available": bool(lesson or subject),
            "requires_approval": False,
            "kind": "quiz",
        },
        {
            "key": "add_session",
            "title": "جدّل جلسة دراسة 30 دقيقة اليوم",
            "detail": "نافذة ثابتة في التقويم — تقليل الاعتماد على الفراغ.",
            "available": True,
            "requires_approval": False,
            "kind": "calendar",
        },
        {
            "key": "ease_difficulty",
            "title": f"خفّض صعوبة الأسئلة في {subject.name_ar if subject else 'أضعف مادة'}",
            "detail": "يقلّل مستوى أسئلة اختباراتك الأخيرة درجة واحدة ويمنع الإحباط.",
            "available": bool(subject),
            "requires_approval": False,
            "kind": "settings",
        },
        {
            "key": "suggest_lesson",
            "title": "اقترح الدرس التالي الأنسب لك",
            "detail": "يختاره النظام حسب تقدّمك ومتطلباته المسبقة، لا حسب ترتيب المنهج فقط.",
            "available": True,
            "requires_approval": False,
            "kind": "lesson",
        },
        {
            "key": "adjust_plan",
            "title": "عدّل الخطة لتصبح واقعية",
            "detail": health.get("suggestion", "إعادة توزيع مهام الأسبوع على قدرك."),
            "available": bool(health.get("available")),
            "requires_approval": True,
            "kind": "plan",
        },
        {
            "key": "start_mock",
            "title": "ابدأ امتحاناً محاكياً بمؤقّت",
            "detail": "15 سؤالاً، 30 دقيقة، تحليل كامل بعد الإرسال.",
            "available": bool(subject),
            "requires_approval": False,
            "kind": "exam",
        },
    ]


def apply_step(db: Session, student_id: str, key: str) -> dict[str, Any]:
    """Actually change the system (§24) — never just print advice."""
    available = {step["key"]: step for step in steps(db, student_id)}
    if key not in available:
        raise NotFoundError("إجراء غير معروف.")
    if not available[key]["available"]:
        raise ValidationError("هذا الإجراء غير متاح حالياً — لا توجد بيانات كافية لديه.")

    lesson, subject, topic = _focus_lesson(db, student_id)

    if key == "add_review":
        row = schedule_review(
            db,
            student_id,
            lesson_id=lesson.id if lesson else None,
            subject_id=subject.id if subject else None,
            topic=topic or (lesson.title if lesson else ""),
            quality=3,
            due_in_days=1.0,
            source="advisor",
        )
        db.flush()
        return {
            "ok": True,
            "message": f"أضفنا مراجعة «{row.topic or lesson and lesson.title or ''}» بعد يوم.",
            "link": "/plan",
            "data": {"review_id": row.id, "due_at": row.due_at.isoformat() if row.due_at else None},
        }

    if key == "add_quiz":
        difficulty = max(1, min(5, (weak_first_severity(db, student_id) or 3) - 1))
        payload = assessment.generate_quiz(
            db,
            student_id,
            lesson_id=lesson.id if lesson else None,
            subject_id=subject.id if subject else None,
            title=f"اختبار قصير — {topic or (lesson.title if lesson else '')}".strip(),
            kind="quiz",
            count=5,
            difficulty=difficulty,
        )
        db.flush()
        return {
            "ok": True,
            "message": f"جاهز: {payload['question_count']} أسئلة بمستوى {difficulty}.",
            "link": f"/quiz/{payload['id']}",
            "data": {"quiz_id": payload["id"], "difficulty": difficulty},
        }

    if key == "add_session":
        start = _next_slot(db, student_id)
        event = CalendarEvent(
            student_id=student_id,
            kind="custom",
            title=f"جلسة دراسة — {topic or (subject.name_ar if subject else 'مراجعة')}",
            start_at=start,
            end_at=start + timedelta(minutes=30),
            color="#2f8ff7",
            meta={"source": "advisor"},
        )
        db.add(event)
        db.flush()
        return {
            "ok": True,
            "message": f"حجزنا لك نافذة دراسة يوم {AR_DAYS[start.weekday()]} الساعة {start.strftime('%H:%M')}.",
            "link": "/plan",
            "data": {"event_id": event.id, "start_at": start.isoformat()},
        }

    if key == "ease_difficulty":
        difficulty_q = db.query(Quiz).filter(
            Quiz.student_id == student_id,
            Quiz.difficulty > 1,
        )
        if subject:
            difficulty_q = difficulty_q.filter(Quiz.subject_id == subject.id)
        recent = difficulty_q.order_by(Quiz.created_at.desc()).limit(3).all()
        lowered = 0
        for quiz in recent:
            quiz.difficulty = max(1, quiz.difficulty - 1)
            for question in quiz.questions:
                question.difficulty = max(1, question.difficulty - 1)
                lowered += 1
        if not recent:
            payload = assessment.generate_quiz(
                db,
                student_id,
                subject_id=subject.id if subject else None,
                title="اختبار مُخفّض الصعوبة",
                kind="practice",
                count=5,
                difficulty=1,
            )
            db.flush()
            return {
                "ok": True,
                "message": "لم توجد اختبارات سابقة — أنشأنا اختباراً سهلاً بدلها.",
                "link": f"/quiz/{payload['id']}",
                "data": {"quiz_id": payload["id"], "difficulty": 1},
            }
        db.flush()
        return {
            "ok": True,
            "message": f"خفّضنا صعوبة {len(recent)} اختبار ({lowered} سؤالاً).",
            "link": "/exams",
            "data": {"quizzes": len(recent), "questions": lowered},
        }

    if key == "suggest_lesson":
        suggestion = planner.what_now(db, student_id)
        chosen = suggestion.get("lesson") or {}
        if not chosen:
            raise ValidationError("ما لقينا درساً مناسباً الآن — أنهِ مهمة من خطتك أولاً.")
        return {
            "ok": True,
            "message": f"الخطوة الأفضل الآن: {chosen.get('title', '')}.",
            "link": f"/lessons/{chosen.get('id')}",
            "data": {"lesson_id": chosen.get("id"), "duration_minutes": suggestion.get("duration_minutes")},
        }

    if key == "adjust_plan":
        result = planner.recovery_plan(db, student_id)
        plan = db.get(StudyPlan, result.get("plan_id"))
        payload = planner.plan_payload(plan) if plan else {}
        return {
            "ok": True,
            "message": "أعدنا ترتيب أسبوعك على قدرك — راجع المهام الجديدة.",
            "link": "/plan",
            "data": {"plan_id": result.get("plan_id"), "days": len(payload.get("days", []))},
        }

    if key == "start_mock":
        quiz = exams_service.generate_exam(
            db,
            student_id,
            subject_id=subject.id if subject else None,
            count=15,
            duration_minutes=30,
            kind="mock",
        )
        attempt = exams_service.start_exam(db, student_id, quiz["id"], mode="mock")
        db.flush()
        return {
            "ok": True,
            "message": f"الامتحان جاهز: {quiz['question_count']} سؤالاً خلال 30 دقيقة.",
            "link": f"/exam/{attempt.id}",
            "data": {"exam_attempt_id": attempt.id, "quiz_id": quiz["id"]},
        }

    raise ValidationError("إجراء غير معروف.")


def weak_first_severity(db: Session, student_id: str) -> int | None:
    weak = active_weak(db, student_id, 1)
    return weak[0].severity if weak else None


def _next_slot(db: Session, student_id: str):
    from datetime import datetime, time as dtime

    profile = db.get(StudentProfile, student_id)
    now = utcnow()
    hour = 17
    if profile and profile.free_windows:
        try:
            first = profile.free_windows[0]
            hour = int(str(first.get("start", "17:00")).split(":")[0])
        except Exception:  # noqa: BLE001 - a bad window must not break the advisor
            hour = 17
    start = datetime.combine(now.date(), dtime(hour, 0))
    if start.replace(tzinfo=None) <= now.replace(tzinfo=None):
        start = start + timedelta(days=1)
    return start


# --------------------------------------------------------------------------- #
# §91/§92 — smart, balanced prioritization
# --------------------------------------------------------------------------- #
def priorities(db: Session, student_id: str) -> dict[str, Any]:
    stats = [s for s in _subject_stats(db, student_id) if s["score"] is not None]
    if not stats:
        stats = _subject_stats(db, student_id)
    exams_by_subject: dict[str, int] = {}
    for row in (
        db.query(Exam)
        .filter(Exam.student_id == student_id, Exam.status == "upcoming")
        .all()
    ):
        if row.subject_id and row.exam_date:
            days = max(0, (row.exam_date - utcnow().date()).days)
            exams_by_subject[row.subject_id] = min(
                exams_by_subject.get(row.subject_id, days), days
            )

    ranked = []
    for stat in stats:
        readiness = stat["readiness"].get("score")
        gap = 100 - (readiness if readiness is not None else (stat["score"] or 50))
        urgency = 0
        days_left = exams_by_subject.get(stat["subject_id"])
        if days_left is not None and days_left <= 14:
            urgency = 30 - days_left * 1.5
        score = round(gap * 0.6 + stat["weak_topics"] * 6 + max(0, urgency), 1)
        ranked.append(
            {
                "subject_id": stat["subject_id"],
                "name_ar": stat["name_ar"],
                "score": stat["score"],
                "weak_topics": stat["weak_topics"],
                "readiness": readiness,
                "days_to_exam": days_left,
                "priority_score": score,
            }
        )
    ranked.sort(key=lambda r: -r["priority_score"])

    # §92: never dump everything on one subject
    shares: list[int] = []
    n = len(ranked)
    if n == 1:
        shares = [100]
    elif n == 2:
        shares = [60, 40]
    elif n == 3:
        shares = [45, 30, 25]
    else:
        head = [40, 25]
        rest_each = int((100 - sum(head)) / (n - 2))
        shares = head + [rest_each] * (n - 2)
        drift = 100 - sum(shares)
        shares[-1] += drift

    for index, row in enumerate(ranked):
        row["share"] = shares[index] if index < len(shares) else 10
        row["rank"] = index + 1
        row["label"] = (
            "أولوية قصوى"
            if index == 0
            else ("أولوية" if index <= 1 else ("اعتدالية" if index <= 2 else "تثبيت"))
        )
    return {
        "subjects": ranked,
        "message": (
            f"خُصّص {ranked[0]['share']}% من أسبوعك لـ{ranked[0]['name_ar']} — الأضعف والأقرب امتحاناً، "
            "مع الحفاظ على باقي المواد."
            if ranked
            else "أضف موادك ليرتب النظام أولويتك."
        ),
    }


# --------------------------------------------------------------------------- #
# one payload for the page
# --------------------------------------------------------------------------- #
def overview(db: Session, student_id: str) -> dict[str, Any]:
    report = success_report(db, student_id)
    return {
        "context": student_context(db, student_id),
        "report": report,
        "weekly": weekly_review(db, student_id),
        "steps": steps(db, student_id),
        "priorities": priorities(db, student_id),
        "plan_health": plan_health(db, student_id),
        "headline": _headline(report),
    }


def _headline(report: dict[str, Any]) -> str:
    problems = report.get("problems", [])
    if not problems:
        return "ما شفت مشاكل واضحة — كمّل نفس النسق وراجع تقدّمك أسبوعياً."
    worst = problems[0]
    return f"{worst['title']}: {worst['solution']}"


__all__ = [
    "apply_step",
    "overview",
    "plan_health",
    "priorities",
    "steps",
    "student_context",
    "success_report",
    "weekly_review",
]
