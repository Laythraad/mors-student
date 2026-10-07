"""Domain events emitted across the platform.

Events are the backbone of the system: one event fans out to independent
handlers (progress → mastery → review → streak → Mors → feedback →
notification) instead of every concern living inside one route handler.
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    # lifecycle
    USER_REGISTERED = "user_registered"
    ONBOARDING_COMPLETED = "onboarding_completed"
    DIAGNOSTIC_COMPLETED = "diagnostic_completed"
    PLAN_GENERATED = "plan_generated"
    # study
    STUDY_STARTED = "study_started"
    STUDY_COMPLETED = "study_completed"
    STUDY_INTERRUPTED = "study_interrupted"
    BREAK_STARTED = "break_started"
    FEEDBACK_SUBMITTED = "feedback_submitted"
    # tasks / plan
    TASK_COMPLETED = "task_completed"
    TASK_MISSED = "task_missed"
    TASK_POSTPONED = "task_postponed"
    BACKLOG_DETECTED = "backlog_detected"
    PLAN_RECOVERED = "plan_recovered"
    # assessment
    QUIZ_STARTED = "quiz_started"
    QUIZ_COMPLETED = "quiz_completed"
    EXAM_PASSED = "exam_passed"
    EXAM_FAILED = "exam_failed"
    EXAM_SCHEDULED = "exam_scheduled"
    QUIZ_QUESTION_MISSED = "quiz_question_missed"
    QUIZ_QUESTION_CORRECT = "quiz_question_correct"
    # learning
    LESSON_MASTERED = "lesson_mastered"
    WEAK_TOPIC_DETECTED = "weak_topic_detected"
    IMPROVEMENT_DETECTED = "improvement_detected"
    NEW_RECORD = "new_record"
    REVIEW_COMPLETED = "review_completed"
    REVIEW_DUE = "review_due"
    # habits
    STREAK_CREATED = "streak_created"
    STREAK_BROKEN = "streak_broken"
    RETURNED_AFTER_ABSENCE = "returned_after_absence"
    GOAL_REACHED = "goal_reached"
    ACHIEVEMENT_EARNED = "achievement_earned"
    # content
    PAPER_CREATED = "paper_created"
    SUMMARY_CREATED = "summary_created"
    UPLOAD_INDEXED = "upload_indexed"
    VIDEO_COMPLETED = "video_completed"
    # interaction
    CHAT_MESSAGE = "chat_message"
    HELP_REQUESTED = "help_requested"
    FOCUS_ENTERED = "focus_entered"
    FOCUS_EXITED = "focus_exited"
    SESSION_EXPIRED = "session_expired"


#: events that may interrupt a student in Focus Mode
CRITICAL_IN_FOCUS = {
    EventType.STUDY_STARTED,
    EventType.STUDY_COMPLETED,
    EventType.QUIZ_QUESTION_MISSED,
    EventType.EXAM_FAILED,
    EventType.HELP_REQUESTED,
    EventType.NEW_RECORD,
}


#: events worth persisting even when no handler claims them
PERSISTED_EVENTS = {
    EventType.STUDY_STARTED,
    EventType.STUDY_COMPLETED,
    EventType.STUDY_INTERRUPTED,
    EventType.TASK_MISSED,
    EventType.BACKLOG_DETECTED,
    EventType.QUIZ_COMPLETED,
    EventType.EXAM_PASSED,
    EventType.EXAM_FAILED,
    EventType.LESSON_MASTERED,
    EventType.WEAK_TOPIC_DETECTED,
    EventType.IMPROVEMENT_DETECTED,
    EventType.STREAK_CREATED,
    EventType.STREAK_BROKEN,
    EventType.RETURNED_AFTER_ABSENCE,
    EventType.NEW_RECORD,
    EventType.GOAL_REACHED,
    EventType.ACHIEVEMENT_EARNED,
    EventType.PLAN_GENERATED,
    EventType.PLAN_RECOVERED,
}


__all__ = ["EventType", "CRITICAL_IN_FOCUS", "PERSISTED_EVENTS"]
