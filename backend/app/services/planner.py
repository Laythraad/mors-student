"""Smart scheduling: daily plans, recovery plans and exam countdowns.

The planner is **deterministic first** — it must produce a usable plan with
no network and no key — and the AI layer is used only to polish the wording
and the rationale. Scoring, sequencing and duration estimates are code, not
prompt output, so a plan can never be silently wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..db import (
    CalendarEvent,
    Exam,
    Lesson,
    LearningProfile,
    MasteryScore,
    PlanDay,
    StudentProfile,
    StudentSubject,
    StudyPlan,
    Subject,
    Task,
    Unit,
    Chapter,
    utcnow,
)
from ..mors import EventType, PersonalityContext, bus
from ..mors.models_helper import queue_message, react, record_state
from .progress import MASTERY_STRONG, MASTERY_WEAK, active_weak, mastery_map
from .review import review_pressure

MAX_TASKS_PER_DAY = 6
URGENT_EXAM_DAYS = 7


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
@dataclass
class Candidate:
    lesson: Lesson
    subject: Subject
    mastery: float
    weak: bool
    overdue: bool = False
    exam_soon: bool = False
    prerequisites_ok: bool = True
    score: float = 0.0
    reason: str = ""


def _learning_profile(db: Session, student_id: str) -> LearningProfile | None:
    return (
        db.query(LearningProfile).filter(LearningProfile.student_id == student_id).one_or_none()
    )


def estimate_duration(db: Session, student_id: str, lesson: Lesson) -> int:
    """AI-relevant inputs turned into a number: pages, difficulty, level and
    the student's own session history."""
    profile = _learning_profile(db, student_id)
    base = lesson.estimated_minutes or 45
    difficulty = max(1, min(5, lesson.difficulty or 3))

    minutes = base + (difficulty - 3) * 6
    pages = 0
    if lesson.page_start and lesson.page_end:
        pages = max(0, (lesson.page_end or lesson.page_start) - lesson.page_start + 1)
    minutes += pages * 1.2

    if profile:
        factor = {
            "slow": 1.25,
            "normal": 1.0,
            "fast": 0.85,
        }.get(profile.learning_speed, 1.0)
        minutes *= factor
        if profile.session_completion_rate and profile.session_completion_rate < 0.5:
            minutes *= 0.8  # they keep abandoning long sessions — shorten them
        elif profile.session_completion_rate and profile.session_completion_rate > 0.85:
            minutes *= 1.1
    if lesson.subject_id:
        subject = db.get(Subject, lesson.subject_id)
        if subject and "رياض" in (subject.name_ar or ""):
            minutes *= 1.15  # problem-solving subjects need the extra room

    return max(15, min(180, int(round(minutes / 5) * 5)))


def _selected_subject_ids(db: Session, student_id: str) -> list[str]:
    rows = (
        db.query(StudentSubject)
        .filter(StudentSubject.profile_id == student_id, StudentSubject.is_active.is_(True))
        .order_by(StudentSubject.priority)
        .all()
    )
    return [r.subject_id for r in rows]


def _active_exams(db: Session, student_id: str) -> list[Exam]:
    today = utcnow().date()
    return (
        db.query(Exam)
        .filter(
            Exam.student_id == student_id,
            Exam.status == "upcoming",
            Exam.exam_date >= today,
        )
        .order_by(Exam.exam_date)
        .all()
    )


def _mastery_of(db: Session, student_id: str) -> dict[str, float]:
    rows = (
        db.query(MasteryScore)
        .filter(MasteryScore.student_id == student_id)
        .all()
    )
    out: dict[str, float] = {}
    for row in rows:
        if row.lesson_id:
            out[row.lesson_id] = row.score
        if row.topic:
            out[f"topic:{row.topic}"] = row.score
    return out


def _has_overdue(db: Session, student_id: str, lesson_id: str) -> bool:
    today = utcnow().date()
    return (
        db.query(Task)
        .filter(
            Task.student_id == student_id,
            Task.lesson_id == lesson_id,
            Task.status.in_(["pending", "in_progress"]),
            Task.scheduled_date.isnot(None),
            Task.scheduled_date < today,
        )
        .count()
        > 0
    )


def _prerequisites_ok(db: Session, student_id: str, lesson: Lesson, mastery: dict[str, float]) -> bool:
    for prereq in lesson.prerequisites or []:
        if mastery.get(prereq, 100) < 45:
            return False
    return True


def build_candidates(db: Session, student_id: str) -> list[Candidate]:
    subject_ids = _selected_subject_ids(db, student_id)
    if not subject_ids:
        return []
    mastery = _mastery_of(db, student_id)
    weak_topics = {w.topic for w in active_weak(db, student_id, 20)}
    lessons = (
        db.query(Lesson)
        .filter(Lesson.subject_id.in_(subject_ids))
        .order_by(Lesson.subject_id, Lesson.index)
        .all()
    )
    exams = _active_exams(db, student_id)
    exam_subjects = {e.subject_id for e in exams if e.subject_id}

    candidates: list[Candidate] = []
    subjects = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()}
    for lesson in lessons:
        score_value = mastery.get(lesson.id, 50.0)
        if score_value >= MASTERY_STRONG:
            continue
        subject = subjects.get(lesson.subject_id) or db.get(Subject, lesson.subject_id)
        if subject is None:
            continue
        weak = score_value < MASTERY_WEAK or bool(set(lesson.keywords or []) & weak_topics)
        candidates.append(
            Candidate(
                lesson=lesson,
                subject=subject,
                mastery=score_value,
                weak=weak,
                overdue=_has_overdue(db, student_id, lesson.id),
                exam_soon=lesson.subject_id in exam_subjects,
                prerequisites_ok=_prerequisites_ok(db, student_id, lesson, mastery),
            )
        )
    return candidates


def score_candidate(candidate: Candidate, *, exam_days: int | None, weak_count: int, backlog: int) -> Candidate:
    score = 0.0
    reasons: list[str] = []

    score += (100 - candidate.mastery) * 0.45
    if candidate.mastery < MASTERY_WEAK:
        reasons.append("موضوع ضعيف")

    if candidate.exam_soon and exam_days is not None:
        weight = 40 if exam_days <= 3 else (25 if exam_days <= URGENT_EXAM_DAYS else 12)
        score += weight
        reasons.append(f"امتحان بعد {exam_days} يوم")

    if candidate.weak:
        score += 15
        reasons.append("يحتاج تدريب")
    if candidate.overdue:
        score += 20
        reasons.append("متأخرة")
    if not candidate.prerequisites_ok:
        score -= 35
        reasons.append("يحتاج المسبق أولاً")
    if backlog >= 5:
        score += 5

    candidate.score = round(score, 2)
    candidate.reason = "، ".join(reasons) or "التالي في التسلسل"
    return candidate


def next_best(db: Session, student_id: str) -> Candidate | None:
    candidates = build_candidates(db, student_id)
    if not candidates:
        return None
    exams = _active_exams(db, student_id)
    exam_days = ((exams[0].exam_date - utcnow().date()).days if exams else None)
    weak_count = len(active_weak(db, student_id))
    backlog = _backlog_count(db, student_id)
    ranked = sorted(
        (score_candidate(c, exam_days=exam_days, weak_count=weak_count, backlog=backlog) for c in candidates),
        key=lambda c: c.score,
        reverse=True,
    )
    return ranked[0]


def _backlog_count(db: Session, student_id: str) -> int:
    today = utcnow().date()
    return (
        db.query(Task)
        .filter(
            Task.student_id == student_id,
            Task.status.in_(["pending", "in_progress"]),
            Task.scheduled_date.isnot(None),
            Task.scheduled_date < today,
        )
        .count()
    )


# --------------------------------------------------------------------------- #
# "ماذا أدرس الآن؟"
# --------------------------------------------------------------------------- #
def what_now(db: Session, student_id: str) -> dict[str, Any]:
    profile = db.get(StudentProfile, student_id)
    candidate = next_best(db, student_id)
    exams = _active_exams(db, student_id)
    backlog = _backlog_count(db, student_id)
    pressure = review_pressure(db, student_id)

    if candidate is None:
        remaining = (
            db.query(Lesson)
            .filter(Lesson.subject_id.in_(_selected_subject_ids(db, student_id) or [""]))
            .count()
        )
        if remaining:
            return {
                "available": False,
                "message": "خلصت كل دروس موادك المختارة — جرّب اختباراً أو أضف مادة جديدة.",
                "backlog": backlog,
                "all_mastered": True,
            }
        return {
            "available": False,
            "message": "ما عندك مهام حالياً — أضف موادك أو أنشئ خطة.",
            "backlog": backlog,
        }

    minutes = estimate_duration(db, student_id, candidate.lesson)
    exam_days = (exams[0].exam_date - utcnow().date()).days if exams else None

    # reviews outrank new material when they are already overdue
    if pressure["overdue"] >= 3:
        kind = "review"
        goal = f"مراجعة {pressure['overdue']} مواضيع متأخرة"
    else:
        kind = "study"
        goal = candidate.lesson.summary[:160] if candidate.lesson.summary else candidate.lesson.title

    now = utcnow()
    return {
        "available": True,
        "kind": kind,
        "subject": {"id": candidate.subject.id, "name_ar": candidate.subject.name_ar, "color": candidate.subject.color},
        "lesson": {"id": candidate.lesson.id, "title": candidate.lesson.title},
        "duration_minutes": minutes,
        "goal": goal,
        "reason": candidate.reason,
        "mastery_before": round(candidate.mastery, 1),
        "exam": {"title": exams[0].title, "days_left": exam_days} if exams else None,
        "backlog": backlog,
        "weak_topics": pressure["weak_topics"][:4],
        "suggested_start": now.isoformat(timespec="minutes"),
        "focus_mode": True,
    }


# --------------------------------------------------------------------------- #
# plan generation
# --------------------------------------------------------------------------- #
def _day_windows(profile: StudentProfile) -> list[tuple[time, time]]:
    windows: list[tuple[time, time]] = []
    if profile.free_windows:
        for item in profile.free_windows:
            try:
                start = time(int(str(item.get("start", "16:00")).split(":")[0]), int(str(item.get("start", "16:00")).split(":")[1]))
                end = time(int(str(item.get("end", "20:00")).split(":")[0]), int(str(item.get("end", "20:00")).split(":")[1]))
                windows.append((start, end))
            except (KeyError, ValueError, TypeError):
                continue
    if not windows:
        school_end = profile.school_end or time(14, 0)
        start_h = min(23, school_end.hour + 1)
        end_h = 21 if (profile.sleep_start is None or profile.sleep_start.hour >= 22) else max(start_h + 1, profile.sleep_start.hour - 1)
        if end_h <= start_h:
            end_h = min(23, start_h + 3)
        windows.append((time(start_h, 0), time(end_h, 0)))
    return windows


def _plan_study_days(profile: StudentProfile) -> list[int]:
    days = profile.study_days or [0, 1, 2, 3, 4]
    return sorted(days)


def generate_plan(
    db: Session,
    student_id: str,
    *,
    days: int = 7,
    kind: str = "regular",
    start: date | None = None,
    title: str = "",
    rationale: str = "",
) -> StudyPlan:
    profile = db.get(StudentProfile, student_id)
    if profile is None:
        raise ValueError("profile missing")

    start = start or utcnow().date()
    study_days = _plan_study_days(profile)
    daily_budget = max(30, profile.daily_study_minutes or 120)
    windows = _day_windows(profile)

    plan = StudyPlan(
        student_id=student_id,
        title=title or ("خطة الدراسة" if kind == "regular" else "خطة الاسترجاع"),
        kind=kind,
        generated_by="ai" if rationale else "manual",
        start_date=start,
        end_date=start + timedelta(days=max(0, days - 1)),
        rationale=rationale,
    )
    db.add(plan)
    db.flush()

    ranked = sorted(
        (
            score_candidate(
                c,
                exam_days=(
                    (_active_exams(db, student_id)[0].exam_date - start).days
                    if _active_exams(db, student_id)
                    else None
                ),
                weak_count=len(active_weak(db, student_id)),
                backlog=_backlog_count(db, student_id),
            )
            for c in build_candidates(db, student_id)
        ),
        key=lambda c: c.score,
        reverse=True,
    )
    pressure = review_pressure(db, student_id)

    cursor = 0
    for offset in range(max(days, 1)):
        day_date = start + timedelta(days=offset)
        weekday = day_date.weekday()
        is_study_day = weekday in study_days
        plan_day = PlanDay(
            plan_id=plan.id,
            date=day_date,
            label="",
            focus="",
            is_rest=not is_study_day,
        )
        db.add(plan_day)
        db.flush()

        if not is_study_day:
            plan_day.label = "راحة / مراجعة خفيفة"
            plan_day.focus = "راحة"
            if pressure["overdue"] and offset % 2 == 0:
                _add_task(
                    db,
                    plan,
                    plan_day,
                    student_id,
                    title=f"مراجعة سريعة ({pressure['overdue']} مواضيع متأخرة)",
                    type="review",
                    duration=min(25, daily_budget),
                    scheduled_start=_start_time(windows, 0),
                    day_date=day_date,
                    goal="تقليل المراجعات المتأخرة",
                )
            continue

        spent = 0
        slot = 0
        # 1) overdue reviews first
        if pressure["overdue"]:
            review_minutes = min(30, daily_budget // 3)
            _add_task(
                db,
                plan,
                plan_day,
                student_id,
                title=f"مراجعة المتأخرات ({pressure['overdue']})",
                type="review",
                duration=review_minutes,
                scheduled_start=_start_time(windows, slot),
                day_date=day_date,
                goal="تسوية المراجعات المتأخرة قبل إضافة الجديد",
            )
            spent += review_minutes
            slot += 1

        # 2) new material until the daily budget is spent
        while spent < daily_budget and cursor < len(ranked) and slot < MAX_TASKS_PER_DAY:
            candidate = ranked[cursor]
            cursor += 1
            minutes = estimate_duration(db, student_id, candidate.lesson)
            if spent + minutes > daily_budget and spent > 0:
                minutes = max(20, daily_budget - spent)
            _add_task(
                db,
                plan,
                plan_day,
                student_id,
                title=f"{candidate.subject.name_ar} — {candidate.lesson.title}",
                type="study",
                duration=minutes,
                scheduled_start=_start_time(windows, slot),
                day_date=day_date,
                subject_id=candidate.subject.id,
                lesson_id=candidate.lesson.id,
                goal=candidate.lesson.summary[:200] if candidate.lesson.summary else f"فهم {candidate.lesson.title}",
                rationale=candidate.reason,
                priority=1 if candidate.exam_soon else 2,
            )
            spent += minutes
            slot += 1

            if spent + 30 <= daily_budget and slot < MAX_TASKS_PER_DAY:
                _add_task(
                    db,
                    plan,
                    plan_day,
                    student_id,
                    title=f"اختبار قصير — {candidate.lesson.title}",
                    type="quiz",
                    duration=15,
                    scheduled_start=_start_time(windows, slot),
                    day_date=day_date,
                    subject_id=candidate.subject.id,
                    lesson_id=candidate.lesson.id,
                    goal="قياس الفهم بعد الشرح",
                )
                spent += 15
                slot += 1

        if slot == 0:
            _add_task(
                db,
                plan,
                plan_day,
                student_id,
                title="جلسة مراجعة عامة",
                type="review",
                duration=min(30, daily_budget),
                scheduled_start=_start_time(windows, 0),
                day_date=day_date,
                goal="تثبيت المكتسب",
            )

        plan_day.total_minutes = spent
        plan_day.label = f"{spent} دقيقة"
        plan_day.focus = ranked[0].subject.name_ar if ranked else "مراجعة"

    db.flush()
    _sync_calendar(db, student_id, plan)
    total_tasks = sum(len(d.tasks) for d in plan.days)
    bus.emit(
        db,
        student_id,
        EventType.PLAN_GENERATED,
        {
            "plan_id": plan.id,
            "kind": plan.kind,
            "days": len(plan.days),
            "tasks": total_tasks,
            "task_count": total_tasks,
            "completed_count": 0,
            "rationale": plan.rationale,
        },
    )
    return plan


def _start_time(windows: list[tuple[time, time]], slot: int) -> datetime:
    start, _ = windows[min(slot, len(windows) - 1)]
    today = utcnow().date()
    return datetime.combine(today, start)


def _add_task(
    db: Session,
    plan: StudyPlan,
    day: PlanDay,
    student_id: str,
    *,
    title: str,
    type: str,
    duration: int,
    scheduled_start: datetime | None,
    day_date: date,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    goal: str = "",
    rationale: str = "",
    priority: int = 2,
) -> Task:
    task = Task(
        student_id=student_id,
        plan_id=plan.id,
        day_id=day.id,
        subject_id=subject_id,
        lesson_id=lesson_id,
        title=title,
        type=type,
        priority=priority,
        scheduled_date=day_date,
        scheduled_start=scheduled_start,
        duration_minutes=max(5, duration),
        goal=goal,
        rationale=rationale,
    )
    db.add(task)
    db.flush()
    return task


def _sync_calendar(db: Session, student_id: str, plan: StudyPlan) -> None:
    """Mirror plan tasks onto the calendar so drag & drop has rows to move."""
    for day in plan.days:
        for task in day.tasks:
            start = task.scheduled_start or datetime.combine(
                day.date, time(16, 0)
            )
            if isinstance(start, datetime) and start.tzinfo is None:
                start = start.replace(tzinfo=utcnow().tzinfo)
            exists = (
                db.query(CalendarEvent)
                .filter(CalendarEvent.task_id == task.id)
                .first()
            )
            if exists:
                continue
            db.add(
                CalendarEvent(
                    student_id=student_id,
                    kind="task",
                    title=task.title,
                    start_at=start,
                    end_at=start + timedelta(minutes=task.duration_minutes),
                    task_id=task.id,
                    color="#2f8ff7" if task.type == "study" else "#f7a22f",
                )
            )
    db.flush()


# --------------------------------------------------------------------------- #
# recovery plan (§18)
# --------------------------------------------------------------------------- #
def recovery_plan(db: Session, student_id: str) -> dict[str, Any]:
    """When the student is behind: fewer tasks, redistributed, never stacked."""
    backlog = _backlog_count(db, student_id)
    overdue_tasks = (
        db.query(Task)
        .filter(
            Task.student_id == student_id,
            Task.status.in_(["pending", "in_progress"]),
            Task.scheduled_date < utcnow().date(),
        )
        .order_by(Task.scheduled_date)
        .all()
    )

    kept: list[Task] = []
    dropped = 0
    for index, task in enumerate(overdue_tasks):
        if index < 8 and task.type != "rest":
            kept.append(task)
        else:
            task.status = "skipped"
            task.rationale = task.rationale or "أعيد جدولتها ضمن خطة الاسترجاع"
            dropped += 1

    profile = db.get(StudentProfile, student_id)
    spread = max(2, min(5, (len(kept) + 3) // 4 or 2))
    start = utcnow().date()
    daily_budget = max(30, (profile.daily_study_minutes or 120) if profile else 90)

    for index, task in enumerate(kept):
        day_offset = index * spread // max(len(kept), 1)
        new_date = start + timedelta(days=min(day_offset, spread - 1))
        task.scheduled_date = new_date
        task.duration_minutes = min(task.duration_minutes, daily_budget // 2)
        task.status = "pending"
        task.rationale = "خطة استرجاع — أعد توزيع المهام المتأخرة"

    plan = generate_plan(
        db,
        student_id,
        days=spread,
        kind="recovery",
        start=start,
        title="خطة استرجاع",
        rationale=f"إعادة توزيع {len(kept)} مهمة متأخرة عبر {spread} أيام، وتجاهل {dropped} مهمة منخفضة الأهمية.",
    )
    db.flush()
    bus.emit(
        db,
        student_id,
        EventType.PLAN_RECOVERED,
        {"backlog": backlog, "kept": len(kept), "dropped": dropped, "plan_id": plan.id},
    )
    return {
        "plan_id": plan.id,
        "backlog": backlog,
        "kept": len(kept),
        "dropped": dropped,
        "spread_days": spread,
        "message": "عندنا شوية تراكم، خلينا نرتبه.",
    }


# --------------------------------------------------------------------------- #
# exam countdown (§61)
# --------------------------------------------------------------------------- #
def exam_countdown_plan(db: Session, student_id: str, exam_id: str) -> dict[str, Any]:
    exam = db.get(Exam, exam_id)
    if exam is None or exam.student_id != student_id:
        raise ValueError("exam not found")
    today = utcnow().date()
    days_left = max(1, (exam.exam_date - today).days)
    candidates = [c for c in build_candidates(db, student_id) if not exam.subject_id or c.subject.id == exam.subject_id]
    candidates.sort(key=lambda c: c.mastery)
    weak = active_weak(db, student_id)

    plan = generate_plan(
        db,
        student_id,
        days=days_left,
        kind="exam",
        start=today,
        title=f"خطة امتحان {exam.title}",
        rationale=f"{days_left} يوم متاحة، {len(candidates)} درس مرتبط بالمادة، {len(weak)} موضوع ضعيف.",
    )

    # tag the shape: concepts → practice → weak → revision → mock → rest
    phases = []
    phase_names = _phase_names(days_left)
    for index, day in enumerate(plan.days):
        phase = phase_names[min(index, len(phase_names) - 1)]
        day.focus = phase
        phases.append({"date": day.date.isoformat(), "phase": phase, "minutes": day.total_minutes})

    exam.plan_id = plan.id
    db.flush()
    return {
        "exam_id": exam.id,
        "days_left": days_left,
        "plan_id": plan.id,
        "phases": phases,
        "weak_topics": [w.topic for w in weak],
    }


def _phase_names(days_left: int) -> list[str]:
    if days_left <= 2:
        return ["مراجعة مكثفة", "محاكاة امتحان"]
    if days_left <= 5:
        return ["مفاهيم", "تدريب", "مواضيع ضعيفة", "مراجعة", "محاكاة"]
    if days_left <= 10:
        return ["مفاهيم", "مفاهيم", "تدريب", "مواضيع ضعيفة", "تدريب", "مراجعة", "مراجعة", "محاكاة", "راحة", "مراجعة خفيفة"]
    return ["مفاهيم", "تدريب", "مواضيع ضعيفة", "مراجعة", "محاكاة"] * ((days_left // 5) + 1)


# --------------------------------------------------------------------------- #
# task operations (calendar drag & drop)
# --------------------------------------------------------------------------- #
def complete_task(db: Session, student_id: str, task_id: str, *, seconds: int = 0) -> Task | None:
    task = db.get(Task, task_id)
    if task is None or task.student_id != student_id:
        return None
    task.status = "completed"
    task.completed_at = utcnow()
    task.actual_seconds = seconds or task.duration_minutes * 60
    db.flush()
    bus.emit(db, student_id, EventType.TASK_COMPLETED, {"task_id": task.id, "type": task.type})
    return task


def move_task(db: Session, student_id: str, task_id: str, *, new_date: date | None, new_start: datetime | None = None) -> Task | None:
    task = db.get(Task, task_id)
    if task is None or task.student_id != student_id:
        return None
    if new_date is not None:
        task.scheduled_date = new_date
    if new_start is not None:
        task.scheduled_start = new_start
        if new_start.tzinfo is None:
            task.scheduled_start = new_start.replace(tzinfo=utcnow().tzinfo)
    event = (
        db.query(CalendarEvent).filter(CalendarEvent.task_id == task.id).first()
    )
    if event and new_start is not None:
        event.start_at = new_start if new_start.tzinfo else new_start.replace(tzinfo=utcnow().tzinfo)
        event.end_at = event.start_at + timedelta(minutes=task.duration_minutes)
    db.flush()
    return task


def change_task_status(db: Session, student_id: str, task_id: str, status: str) -> Task | None:
    if status not in {"pending", "in_progress", "completed", "skipped", "postponed"}:
        return None
    task = db.get(Task, task_id)
    if task is None or task.student_id != student_id:
        return None
    task.status = status
    if status == "completed":
        task.completed_at = utcnow()
    db.flush()
    if status == "completed":
        bus.emit(db, student_id, EventType.TASK_COMPLETED, {"task_id": task.id})
    elif status == "postponed":
        bus.emit(db, student_id, EventType.TASK_POSTPONED, {"task_id": task.id})
    return task


def plan_payload(plan: StudyPlan) -> dict[str, Any]:
    days = []
    total = 0
    for day in sorted(plan.days, key=lambda d: d.date):
        tasks = []
        for task in sorted(
            day.tasks,
            key=lambda t: (t.scheduled_start.isoformat() if t.scheduled_start else "9999", t.title),
        ):
            tasks.append(task_payload(task))
            if task.status != "completed":
                total += task.duration_minutes or 0
        days.append(
            {
                "id": day.id,
                "date": day.date.isoformat(),
                "label": day.label,
                "focus": day.focus,
                "is_rest": day.is_rest,
                "total_minutes": day.total_minutes,
                "tasks": tasks,
            }
        )
    return {
        "id": plan.id,
        "title": plan.title,
        "kind": plan.kind,
        "start_date": plan.start_date.isoformat() if plan.start_date else None,
        "end_date": plan.end_date.isoformat() if plan.end_date else None,
        "rationale": plan.rationale,
        "days": days,
        "pending_minutes": total,
    }


def task_payload(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "type": task.type,
        "status": task.status,
        "priority": task.priority,
        "subject_id": task.subject_id,
        "lesson_id": task.lesson_id,
        "date": task.scheduled_date.isoformat() if task.scheduled_date else None,
        "start": task.scheduled_start.isoformat(timespec="minutes") if task.scheduled_start else None,
        "duration_minutes": task.duration_minutes,
        "goal": task.goal,
        "rationale": task.rationale,
        "mastery_before": task.mastery_before,
        "mastery_after": task.mastery_after,
    }


__all__ = [
    "estimate_duration",
    "build_candidates",
    "next_best",
    "what_now",
    "generate_plan",
    "recovery_plan",
    "exam_countdown_plan",
    "complete_task",
    "move_task",
    "change_task_status",
    "plan_payload",
    "task_payload",
    "Candidate",
]
