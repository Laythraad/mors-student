"""Event handlers: the fan-out half of the bus.

A handler never decides *whether* an event happened — it only reacts to one.
Registering is explicit (`register_handlers()` at app start) so tests can run
the bus bare, and each handler failure is isolated by the bus itself.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from ..db import (
    Lesson,
    Notification,
    StudentProfile,
    StudentSettings,
    StudyStreak,
    Subject,
    Task,
    User,
    utcnow,
)
from .bus import bus
from .engine import PersonalityContext
from .events import CRITICAL_IN_FOCUS, EventType
from .models_helper import react_and_persist

Handler = Callable[[Session, str, dict[str, Any]], dict[str, Any] | None]

#: every event that should move Mors' face / queue a line of dialogue
MORS_EVENTS: tuple[EventType, ...] = (
    EventType.USER_REGISTERED,
    EventType.ONBOARDING_COMPLETED,
    EventType.DIAGNOSTIC_COMPLETED,
    EventType.PLAN_GENERATED,
    EventType.PLAN_RECOVERED,
    EventType.STUDY_STARTED,
    EventType.STUDY_COMPLETED,
    EventType.STUDY_INTERRUPTED,
    EventType.BREAK_STARTED,
    EventType.FEEDBACK_SUBMITTED,
    EventType.TASK_COMPLETED,
    EventType.TASK_MISSED,
    EventType.TASK_POSTPONED,
    EventType.BACKLOG_DETECTED,
    EventType.QUIZ_STARTED,
    EventType.QUIZ_COMPLETED,
    EventType.EXAM_PASSED,
    EventType.EXAM_FAILED,
    EventType.EXAM_SCHEDULED,
    EventType.QUIZ_QUESTION_CORRECT,
    EventType.QUIZ_QUESTION_MISSED,
    EventType.LESSON_MASTERED,
    EventType.WEAK_TOPIC_DETECTED,
    EventType.IMPROVEMENT_DETECTED,
    EventType.NEW_RECORD,
    EventType.REVIEW_COMPLETED,
    EventType.REVIEW_DUE,
    EventType.STREAK_CREATED,
    EventType.STREAK_BROKEN,
    EventType.RETURNED_AFTER_ABSENCE,
    EventType.GOAL_REACHED,
    EventType.ACHIEVEMENT_EARNED,
    EventType.PAPER_CREATED,
    EventType.SUMMARY_CREATED,
    EventType.VIDEO_COMPLETED,
    EventType.CHAT_MESSAGE,
    EventType.HELP_REQUESTED,
    EventType.FOCUS_ENTERED,
    EventType.FOCUS_EXITED,
)

#: events that also deserve an inbox notification, with its Arabic copy
NOTIFICATIONS: dict[EventType, dict[str, str]] = {
    EventType.STREAK_CREATED: {"kind": "streak", "title": "سلسلة جديدة"},
    EventType.RETURNED_AFTER_ABSENCE: {"kind": "streak", "title": "أهلاً برجعتك"},
    EventType.STREAK_BROKEN: {"kind": "streak", "title": "رجعنا نبدأ من جديد"},
    EventType.ACHIEVEMENT_EARNED: {"kind": "achievement", "title": "وسام جديد"},
    EventType.EXAM_PASSED: {"kind": "exam", "title": "اختبار متقدم بنجاح"},
    EventType.EXAM_FAILED: {"kind": "exam", "title": "تحتاج مراجعة"},
    EventType.PLAN_GENERATED: {"kind": "plan", "title": "خطتك جاهزة"},
    EventType.PLAN_RECOVERED: {"kind": "plan", "title": "الخطة تمت إعادة ضبطها"},
    EventType.NEW_RECORD: {"kind": "record", "title": "رقم قياسي جديد"},
    EventType.REVIEW_DUE: {"kind": "review", "title": "مراجعة مستحقة"},
    EventType.LESSON_MASTERED: {"kind": "mastery", "title": "أتقنتم الدرس"},
    EventType.GOAL_REACHED: {"kind": "goal", "title": "وصلت لهدفك"},
}


# --------------------------------------------------------------------------- #
# context
# --------------------------------------------------------------------------- #
def _time_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _is_focus_mode(db: Session, user_id: str | None) -> bool:
    if not user_id:
        return False
    row = db.query(StudentSettings).filter(StudentSettings.user_id == user_id).first()
    return bool(row and row.focus_mode)


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


def build_context(
    db: Session,
    student_id: str,
    event: EventType | str,
    payload: dict[str, Any],
) -> PersonalityContext:
    profile = db.get(StudentProfile, student_id)
    user = db.get(User, profile.user_id) if profile else None
    streak_row = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).first()
    now = utcnow()

    subject = db.get(Subject, payload["subject_id"]) if payload.get("subject_id") else None
    lesson = db.get(Lesson, payload["lesson_id"]) if payload.get("lesson_id") else None

    ctx = PersonalityContext(
        event=str(event),
        student_name=(user.full_name.split()[0] if user and user.full_name else ""),
        subject=payload.get("subject") or (subject.name_ar if subject else ""),
        lesson=payload.get("lesson") or (lesson.title if lesson else ""),
        focus_mode=_is_focus_mode(db, profile.user_id if profile else None),
        streak=int(payload.get("streak") or (streak_row.current if streak_row else 0)),
        time_of_day=_time_of_day(now.hour),
        minutes=int(payload.get("minutes") or 0),
        days_absent=int(payload.get("days_absent") or 0),
        consecutive_errors=int(payload.get("consecutive_errors") or 0),
        backlog=int(payload.get("backlog") or _backlog_count(db, student_id)),
        task_count=int(payload.get("task_count") or 0),
        completed_count=int(payload.get("completed_count") or 0),
        mastery_before=_as_float(payload.get("mastery_before")),
        mastery_after=_as_float(payload.get("mastery_after")),
        foundation_weak=bool(payload.get("foundation_weak")),
        new_record=bool(payload.get("new_record")),
        effort=True,
        value=str(payload.get("value") or ""),
    )

    if payload.get("score") is not None:
        ctx.score = _as_float(payload.get("score"))
    if payload.get("previous") is not None:
        ctx.previous_score = _as_float(payload.get("previous"))
    if payload.get("previous_score") is not None:
        ctx.previous_score = _as_float(payload.get("previous_score"))
    if payload.get("days_left") is not None:
        ctx.days_to_exam = int(payload["days_left"])
    if payload.get("exam_passed") is not None:
        ctx.exam_passed = bool(payload["exam_passed"])
    if streak_row and not payload.get("streak"):
        ctx.streak = int(streak_row.current or 0)
    if payload.get("streak_broken"):
        ctx.streak_broken = True
    if payload.get("topic"):
        ctx.extra["topic"] = payload["topic"]
    return ctx


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# mors
# --------------------------------------------------------------------------- #
def make_mors_handler(event: EventType) -> Handler:
    def handler(db: Session, student_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        ctx = build_context(db, student_id, event, payload)
        reaction = react_and_persist(
            db,
            student_id,
            ctx,
            seed=f"{student_id}|{event}",
            reason=str(payload.get("reason", "")),
        )
        return reaction.as_dict()

    handler.__name__ = f"mors_{event}"
    return handler


# --------------------------------------------------------------------------- #
# notifications
# --------------------------------------------------------------------------- #
def _notification_body(event: EventType, payload: dict[str, Any]) -> str:
    if event == EventType.STREAK_CREATED:
        return f"درست {payload.get('streak', 1)} يوم متتالية — كمّل."
    if event == EventType.RETURNED_AFTER_ABSENCE:
        return "رجعنا نكمل من حيث وقفنا."
    if event == EventType.STREAK_BROKEN:
        return "يوم واحد يكفي عشان نرجع للمسار."
    if event == EventType.ACHIEVEMENT_EARNED:
        return payload.get("description", "وسام جديد في حسابك.")
    if event == EventType.EXAM_PASSED:
        return f"درجتك {int(payload.get('score', 0))}% — استمر على نفس الخطة."
    if event == EventType.EXAM_FAILED:
        return (
            f"درجتك {int(payload.get('score', 0))}%. "
            + "خطة مراجعة جاهزة لمواضيعك الضعيفة."
            if payload.get("weak_topics")
            else f"درجتك {int(payload.get('score', 0))}%. راجع المحاولة."
        )
    if event == EventType.PLAN_GENERATED:
        return f"{payload.get('tasks', 0)} مهمة موزعة على {payload.get('days', 0)} أيام."
    if event == EventType.PLAN_RECOVERED:
        return "أعدنا ترتيب أيامك على حسب ما فاتك."
    if event == EventType.NEW_RECORD:
        return "أفضل نتيجة لك حتى الآن."
    if event == EventType.REVIEW_DUE:
        return f"عندك {payload.get('due', 1)} مواضيع تحتاج مراجعة اليوم."
    if event == EventType.LESSON_MASTERED:
        return f"أتقننت {payload.get('lesson', 'الدرس')} — {int(payload.get('score', 0))}%."
    if event == EventType.GOAL_REACHED:
        return "حققت الهدف اللي حددته."
    return payload.get("message", "")


def make_notify_handler(event: EventType, spec: dict[str, str]) -> Handler:
    def handler(db: Session, student_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        profile = db.get(StudentProfile, student_id)
        focus = _is_focus_mode(db, profile.user_id if profile else None)
        deferred = focus and event not in CRITICAL_IN_FOCUS
        row = Notification(
            student_id=student_id,
            kind=spec["kind"],
            title=spec["title"],
            body=_notification_body(event, payload),
            link=payload.get("link", ""),
            meta={"event": str(event), "deferred": deferred, "payload": _safe(payload)},
        )
        db.add(row)
        db.flush()
        return {"notification": row.id, "deferred": deferred}

    handler.__name__ = f"notify_{event}"
    return handler


def _safe(payload: dict[str, Any]) -> dict[str, Any]:
    """Notification meta must stay JSON-serialisable."""
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, (list, tuple)):
            clean[key] = [str(v) for v in value][:12]
        else:
            clean[key] = str(value)
    return clean


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
_registered = False


def register_handlers() -> None:
    global _registered
    if _registered:
        return
    for event in MORS_EVENTS:
        bus.on(event, "mors")(make_mors_handler(event))
    for event, spec in NOTIFICATIONS.items():
        bus.on(event, "notify")(make_notify_handler(event, spec))
    _registered = True


def reset_handlers() -> None:
    """Test helper: drop everything so a fresh registration can be asserted."""
    global _registered
    bus._handlers.clear()  # noqa: SLF001
    _registered = False


__all__ = [
    "MORS_EVENTS",
    "NOTIFICATIONS",
    "build_context",
    "make_mors_handler",
    "make_notify_handler",
    "register_handlers",
    "reset_handlers",
    "_time_of_day",
]
