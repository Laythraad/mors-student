"""Mors Personality Engine.

Input  : student event + progress + current context
Output : {expression, tone, message, animation, priority}

The engine is deliberately **contextual** rather than threshold-based. The
product rule is:

    score > 90                 is NOT the same as
    score > 90 after a jump    is NOT the same as
    score > 90 with a broken foundation

so `90 / previous 32` celebrates, while `90 / fundamentals still broken`
expresses concern. Likewise `60` after `30` is a win, not a failure.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .events import CRITICAL_IN_FOCUS, EventType
from .messages import assert_tone, templates
from .states import MorsState, spec

# --------------------------------------------------------------------------- #
# context
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class PersonalityContext:
    event: str = ""
    student_name: str = ""
    subject: str = ""
    lesson: str = ""
    score: float | None = None
    previous_score: float | None = None
    foundation_weak: bool = False
    mastery_before: float | None = None
    mastery_after: float | None = None
    days_absent: int = 0
    streak: int = 0
    streak_broken: bool = False
    backlog: int = 0
    consecutive_errors: int = 0
    minutes: int = 0
    task_count: int = 0
    completed_count: int = 0
    days_to_exam: int | None = None
    time_of_day: str = ""  # morning | afternoon | evening | night
    focus_mode: bool = False
    new_record: bool = False
    effort: bool = True
    value: str = ""
    exam_passed: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MorsReaction:
    state: MorsState
    expression: str
    tone: str
    message: str
    animation: str
    priority: int
    category: str
    scenario: str
    suppressed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "expression": self.expression,
            "sprite": f"/mors/{self.expression}.png",
            "tone": self.tone,
            "message": self.message,
            "animation": self.animation,
            "priority": self.priority,
            "category": self.category,
            "scenario": self.scenario,
            "suppressed": self.suppressed,
        }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _variant(seed: str, options: tuple[str, ...]) -> str:
    """Deterministic per-student variant choice so text doesn't flicker."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return options[digest[0] % len(options)]


def _delta(ctx: PersonalityContext) -> float | None:
    if ctx.mastery_before is None or ctx.mastery_after is None:
        return None
    return ctx.mastery_after - ctx.mastery_before


class _Lenient(dict[str, Any]):
    """A missing placeholder stays visible instead of killing the message."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _fill(template: str, values: dict[str, Any]) -> str:
    try:
        return template.format_map(_Lenient(values))
    except (IndexError, ValueError, KeyError):
        return template


def _eval_score(ctx: PersonalityContext) -> tuple[MorsState, str]:
    """Score interpretation — the rule from the spec, made explicit."""
    score = ctx.score if ctx.score is not None else 0.0
    prev = ctx.previous_score
    improvement = (score - prev) if prev is not None else None

    if ctx.foundation_weak and score >= 80:
        return MorsState.CONCERNED, "high_score_but_weak_foundation"
    if improvement is not None and improvement >= 20:
        return (MorsState.CELEBRATING if score >= 75 else MorsState.PROUD), "improvement_from_low"
    if score >= 85:
        return MorsState.CELEBRATING, "high_score"
    if score >= 70:
        return MorsState.PROUD, "high_score"
    if score >= 55:
        return MorsState.ENCOURAGING, "mid_score"
    if ctx.effort:
        return MorsState.ENCOURAGING, "low_score_with_effort"
    return MorsState.CONCERNED, "low_score"


# --------------------------------------------------------------------------- #
# decision table
# --------------------------------------------------------------------------- #
def decide(ctx: PersonalityContext) -> tuple[MorsState, str]:
    event = ctx.event

    # --- focus mode: stay quiet unless something genuinely matters ---------
    if ctx.focus_mode and event:
        try:
            if EventType(event) not in CRITICAL_IN_FOCUS:
                return MorsState.FOCUSED, "focus_enter"
        except ValueError:
            pass

    # --- explicit outcomes -------------------------------------------------
    if event in (EventType.EXAM_PASSED, EventType.EXAM_FAILED, "quiz_completed", "score"):
        state, scenario = _eval_score(ctx)
        if event == EventType.EXAM_FAILED and state is not MorsState.CONCERNED:
            state, scenario = MorsState.CONCERNED, "low_score"
        return state, scenario

    if event == EventType.STUDY_STARTED:
        return (MorsState.FOCUSED if ctx.focus_mode else MorsState.HAPPY), "study_started"

    if event == EventType.STUDY_COMPLETED:
        delta = _delta(ctx)
        if delta is not None and delta >= 15:
            return MorsState.SURPRISED, "improvement_from_low"
        if ctx.minutes >= 30:
            return MorsState.PROUD, "session_completed"
        return MorsState.PROUD, "session_completed_short"

    if event in (EventType.STUDY_INTERRUPTED, "study_interrupted"):
        return MorsState.CONCERNED, "session_interrupted"

    if event == EventType.TASK_MISSED or event == EventType.BACKLOG_DETECTED:
        if ctx.backlog >= 5:
            return MorsState.OVERWHELMED, "backlog_detected"
        if ctx.days_absent >= 3:
            return MorsState.WELCOMING, "return_after_absence"
        return MorsState.CONCERNED, "task_missed"

    if event == EventType.RETURNED_AFTER_ABSENCE:
        return MorsState.WELCOMING, "return_after_absence"

    if event == EventType.STREAK_CREATED:
        return MorsState.EXCITED, "streak_created"

    if event == EventType.STREAK_BROKEN:
        return MorsState.ENCOURAGING, "streak_broken"

    if event == EventType.NEW_RECORD:
        return MorsState.EXCITED, "new_record"

    if event == EventType.LESSON_MASTERED:
        return MorsState.CELEBRATING, "mastery"

    if event == EventType.WEAK_TOPIC_DETECTED:
        return MorsState.THINKING, "weak_topic"

    if event == EventType.IMPROVEMENT_DETECTED:
        return MorsState.SURPRISED, "progress_seen"

    if event == EventType.QUIZ_QUESTION_MISSED:
        if ctx.consecutive_errors >= 2:
            return MorsState.ENCOURAGING, "repeated_mistake"
        return MorsState.THINKING, "hint"

    if event == EventType.QUIZ_QUESTION_CORRECT:
        return MorsState.ENCOURAGING, "quick_review_done"

    if event == EventType.EXAM_SCHEDULED:
        if ctx.days_to_exam is not None and ctx.days_to_exam <= 7:
            return MorsState.FOCUSED, "exam_upcoming"
        return MorsState.CONCERNED, "exam_upcoming"

    if event == EventType.HELP_REQUESTED:
        return MorsState.THINKING, "explain_request"

    if event == EventType.PLAN_GENERATED or event == EventType.PLAN_RECOVERED:
        return MorsState.PROUD, "plan_ready"

    if event == EventType.GOAL_REACHED:
        return MorsState.CELEBRATING, "goal_reached"

    if event == EventType.BREAK_STARTED:
        return MorsState.SLEEPY, "break_time"

    if event == EventType.FOCUS_ENTERED:
        return MorsState.FOCUSED, "focus_enter"

    if event == EventType.REVIEW_DUE:
        return MorsState.CURIOUS, "idle_hint"

    if event == EventType.USER_REGISTERED:
        return MorsState.HAPPY, "welcome_first_run"

    if event == EventType.DIAGNOSTIC_COMPLETED:
        return MorsState.CURIOUS, "diagnostic_invite"

    if event == EventType.PAPER_CREATED:
        return MorsState.PROUD, "paper_saved"

    if event == EventType.VIDEO_COMPLETED:
        return MorsState.CURIOUS, "video_key_idea"

    if event == EventType.FEEDBACK_SUBMITTED:
        return MorsState.CURIOUS, "feedback_ask"

    # --- contextual free-form (chat) --------------------------------------
    if event in (EventType.CHAT_MESSAGE, "chat"):
        if ctx.consecutive_errors >= 2:
            return MorsState.ENCOURAGING, "repeated_mistake"
        return MorsState.THINKING, "explain_request"

    # --- time of day -------------------------------------------------------
    if ctx.time_of_day == "morning":
        return MorsState.HAPPY, "morning_briefing"
    if ctx.time_of_day == "night":
        return MorsState.SLEEPY, "night_review"

    return MorsState.IDLE, "idle"


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def react(
    ctx: PersonalityContext,
    *,
    seed: str = "",
    state_override: MorsState | None = None,
) -> MorsReaction:
    state, scenario = decide(ctx)
    if state_override is not None:
        state = state_override

    info = spec(state)
    options = templates(scenario)
    message = _variant(f"{seed}|{scenario}|{state.value}", options)

    fmt: dict[str, Any] = {
        "name": ctx.student_name or "صديقي",
        "subject": ctx.subject or "المادة",
        "lesson": ctx.lesson or "الدرس",
        "score": int(ctx.score) if ctx.score is not None else 0,
        "before": int(ctx.previous_score) if ctx.previous_score is not None else 0,
        "minutes": ctx.minutes,
        "days": ctx.days_to_exam if ctx.days_to_exam is not None else max(ctx.streak, 1),
        "tasks": ctx.task_count,
        "done": ctx.completed_count,
        "topic": ctx.extra.get("topic", ctx.lesson or "هذا الموضوع"),
        "page": ctx.extra.get("page", 1),
        "value": ctx.value or str(ctx.streak),
        "step": ctx.extra.get("step", "اللي بعده"),
        "exam": ctx.extra.get("exam", ""),
        "goal": ctx.extra.get("goal", ctx.lesson or "هدفك"),
        "after": int(ctx.mastery_after)
        if ctx.mastery_after is not None
        else int(ctx.score or 0),
    }
    message = _fill(message, fmt)

    assert_tone(message)

    suppressed = bool(ctx.focus_mode) and state is MorsState.FOCUSED and not ctx.event
    return MorsReaction(
        state=state,
        expression=info.sprite,
        tone=info.tone,
        message=message,
        animation=info.animation,
        priority=info.priority,
        category=scenario,
        scenario=scenario,
        suppressed=suppressed,
    )


def idle_reaction(seed: str = "", *, quiet: bool = False) -> MorsReaction:
    ctx = PersonalityContext(event="", time_of_day="")
    reaction = react(ctx, seed=seed)
    if quiet:
        reaction.message = ""
        reaction.suppressed = True
    return reaction


__all__ = ["PersonalityContext", "MorsReaction", "decide", "react", "idle_reaction"]
