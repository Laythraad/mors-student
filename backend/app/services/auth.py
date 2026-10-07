"""Registration, login, token refresh and profile onboarding."""

from __future__ import annotations

from datetime import datetime, timedelta, time
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..core.errors import AuthenticationError, ConflictError, ValidationError
from ..core.security import create_token, decode_token, hash_password, password_strength_ok, verify_password
from ..db import (
    Branch,
    LearningProfile,
    Stage,
    StudentProfile,
    StudentSettings,
    StudentSubject,
    StudyStreak,
    Subject,
    User,
    utcnow,
)

LOGIN_LOCK_THRESHOLD = 8
LOGIN_LOCK_MINUTES = 15


def _has_identifier(email: str | None, phone: str | None) -> bool:
    return bool(email or phone)


def register(
    db: Session,
    *,
    full_name: str,
    email: str | None = None,
    phone: str | None = None,
    password: str,
    role: str = "student",
) -> User:
    full_name = (full_name or "").strip()
    if not full_name:
        raise ValidationError("الاسم مطلوب.")
    if not _has_identifier(email, phone):
        raise ValidationError("أدخل بريداً إلكترونياً أو رقم هاتف.")
    if not password_strength_ok(password):
        raise ValidationError("كلمة المرور يجب أن تكون 8 أحرف على الأقل.")

    email = (email or "").strip().lower() or None
    phone = (phone or "").strip() or None

    q = db.query(User)
    conds = []
    if email:
        conds.append(User.email == email)
    if phone:
        conds.append(User.phone == phone)
    if conds and q.filter(or_(*conds)).first():
        raise ConflictError("يوجد حساب مسجّل بهذه البيانات.")

    user = User(
        full_name=full_name,
        email=email,
        phone=phone,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.flush()

    profile = StudentProfile(user_id=user.id)
    db.add(profile)
    db.add(StudentSettings(user_id=user.id))
    db.flush()
    db.add(LearningProfile(student_id=profile.id))
    db.flush()
    return user


def authenticate(db: Session, identifier: str, password: str) -> User:
    identifier = (identifier or "").strip().lower()
    if not identifier:
        raise ValidationError("أدخل البريد أو رقم الهاتف.")

    user = (
        db.query(User)
        .filter(or_(User.email == identifier, User.phone == identifier))
        .one_or_none()
    )
    if user is None:
        raise AuthenticationError("بيانات الدخول غير صحيحة.")

    if user.locked_until and user.locked_until > utcnow():
        raise AuthenticationError("الحساب موقوف مؤقتاً بعد محاولات كثيرة. حاول لاحقاً.")

    if not verify_password(password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= LOGIN_LOCK_THRESHOLD:
            user.locked_until = utcnow() + timedelta(minutes=LOGIN_LOCK_MINUTES)
            user.failed_logins = 0
        db.flush()
        raise AuthenticationError("بيانات الدخول غير صحيحة.")

    if not user.is_active:
        raise AuthenticationError("الحساب معطّل.")

    user.failed_logins = 0
    user.locked_until = None
    user.last_seen_at = utcnow()
    db.flush()
    return user


def issue_tokens(user: User) -> dict[str, str]:
    access = create_token(user.id, token_type="access", claims={"role": user.role})
    refresh = create_token(
        user.id,
        token_type="refresh",
        ttl_seconds=settings.refresh_token_ttl_days * 86400,
    )
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


def refresh_access(refresh_token: str) -> dict[str, str]:
    payload = decode_token(refresh_token, expected_type="refresh")
    user_id = payload["sub"]
    return {
        "access_token": create_token(user_id, token_type="access"),
        "token_type": "bearer",
    }


# --------------------------------------------------------------------------- #
# onboarding
# --------------------------------------------------------------------------- #
def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        hour, minute = value.split(":")
        return time(int(hour) % 24, int(minute) % 60)
    except (ValueError, AttributeError) as exc:
        raise ValidationError("وقت غير صالح.") from exc


def update_profile(db: Session, profile: StudentProfile, data: dict[str, Any]) -> StudentProfile:
    if "stage_id" in data and data["stage_id"]:
        stage = db.get(Stage, data["stage_id"])
        if stage is None:
            raise ValidationError("المرحلة غير موجودة.")
        profile.stage_id = stage.id
        if "branch_id" in data:
            branch = db.get(Branch, data["branch_id"]) if data["branch_id"] else None
            if data["branch_id"] and branch is None:
                raise ValidationError("الفرع غير موجود.")
            if branch and branch.stage_id != stage.id:
                raise ValidationError("الفرع لا ينتمي للمرحلة المختارة.")
            profile.branch_id = branch.id if branch else None

    if "school_name" in data:
        profile.school_name = str(data["school_name"])[:160]
    if "school_start" in data:
        profile.school_start = _parse_time(data["school_start"])
    if "school_end" in data:
        profile.school_end = _parse_time(data["school_end"])
    if "sleep_start" in data:
        profile.sleep_start = _parse_time(data["sleep_start"])
    if "sleep_end" in data:
        profile.sleep_end = _parse_time(data["sleep_end"])
    if "daily_study_minutes" in data:
        profile.daily_study_minutes = max(20, min(600, int(data["daily_study_minutes"])))
    if "study_days" in data and isinstance(data["study_days"], list):
        days = [int(d) for d in data["study_days"] if 0 <= int(d) <= 6]
        profile.study_days = sorted(set(days)) or [0, 1, 2, 3, 4]
    if "free_windows" in data and isinstance(data["free_windows"], list):
        profile.free_windows = data["free_windows"]
    if "goals" in data:
        profile.goals = str(data["goals"])[:2000]
    if "current_level" in data:
        profile.current_level = str(data["current_level"])[:20]
    if "diagnostic_done" in data:
        profile.diagnostic_done = bool(data["diagnostic_done"])
    if "onboarding_step" in data:
        profile.onboarding_step = max(0, min(20, int(data["onboarding_step"])))

    db.flush()
    return profile


def set_subjects(db: Session, profile: StudentProfile, subject_ids: list[str]) -> list[StudentSubject]:
    if not subject_ids:
        raise ValidationError("اختر مادة واحدة على الأقل.")
    valid = {row.id for row in db.query(Subject).filter(Subject.id.in_(subject_ids))}
    missing = [s for s in subject_ids if s not in valid]
    if missing:
        raise ValidationError("بعض المواد غير موجودة في منهجك.")

    db.query(StudentSubject).filter(StudentSubject.profile_id == profile.id).delete(
        synchronize_session=False
    )
    rows = [
        StudentSubject(profile_id=profile.id, subject_id=sid, priority=2) for sid in subject_ids
    ]
    db.add_all(rows)
    db.flush()
    return rows


def ensure_learning_profile(db: Session, student_id: str) -> LearningProfile:
    row = db.query(LearningProfile).filter(LearningProfile.student_id == student_id).one_or_none()
    if row is None:
        row = LearningProfile(student_id=student_id)
        db.add(row)
        db.flush()
    return row


def ensure_streak(db: Session, student_id: str) -> StudyStreak:
    row = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).one_or_none()
    if row is None:
        row = StudyStreak(student_id=student_id)
        db.add(row)
        db.flush()
    return row


SETTINGS_FIELDS = (
    "theme",
    "primary_color",
    "accent_color",
    "font_scale",
    "card_style",
    "reduce_motion",
    "high_contrast",
    "mors_size",
    "mors_idle_enabled",
    "focus_mode",
    "notification_freq",
    "celebrate_enabled",
    "voice_enabled",
    "tts_voice",
    "stt_provider",
)


def _ensure_settings(db: Session, user: User) -> StudentSettings:
    row = db.query(StudentSettings).filter(StudentSettings.user_id == user.id).one_or_none()
    if row is None:
        row = StudentSettings(user_id=user.id)
        db.add(row)
        db.flush()
    return row


def settings_payload(db: Session, user: User) -> dict[str, Any]:
    row = _ensure_settings(db, user)
    return {field: getattr(row, field) for field in SETTINGS_FIELDS}


def update_settings(db: Session, user: User, data: dict[str, Any]) -> dict[str, Any]:
    row = _ensure_settings(db, user)
    for field, value in data.items():
        if field in SETTINGS_FIELDS and value is not None:
            setattr(row, field, value)
    db.flush()
    return settings_payload(db, user)


def welcome_payload(db: Session, user: User) -> dict[str, Any]:
    profile = (
        db.query(StudentProfile).filter(StudentProfile.user_id == user.id).one_or_none()
    )
    return {
        "user": {"id": user.id, "full_name": user.full_name, "role": user.role},
        "profile_id": profile.id if profile else None,
        "onboarding_step": profile.onboarding_step if profile else 0,
        "has_stage": bool(profile and profile.stage_id),
    }


__all__ = [
    "register",
    "authenticate",
    "issue_tokens",
    "refresh_access",
    "update_profile",
    "set_subjects",
    "ensure_learning_profile",
    "ensure_streak",
    "settings_payload",
    "update_settings",
    "welcome_payload",
]
