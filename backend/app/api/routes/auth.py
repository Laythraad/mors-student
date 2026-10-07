"""Authentication, profile and per-device settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, CurrentUser, DbSession
from ...services import auth as service

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "mors_access"


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str | None = None
    phone: str | None = None
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str


class ProfileIn(BaseModel):
    full_name: str | None = None
    stage_id: str | None = None
    branch_id: str | None = None
    school_name: str | None = None
    daily_study_minutes: int | None = Field(default=None, ge=20, le=600)
    study_days: list[int] | None = None
    free_windows: list[dict[str, str]] | None = None
    school_start: str | None = None
    school_end: str | None = None
    sleep_start: str | None = None
    sleep_end: str | None = None
    goals: str | None = None
    current_level: str | None = None
    goal_date: str | None = None


class SubjectsIn(BaseModel):
    subject_ids: list[str] = Field(min_length=1, max_length=20)


class PasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class AccountDeleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


def _set_cookie(response: Response, tokens: dict[str, str]) -> None:
    response.set_cookie(
        COOKIE_NAME,
        tokens["access_token"],
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
        path="/",
    )


@router.post("/register")
def register(payload: RegisterIn, db: DbSession, response: Response) -> dict[str, Any]:
    user = service.register(
        db,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        password=payload.password,
    )
    db.commit()
    tokens = service.issue_tokens(user)
    _set_cookie(response, tokens)
    return {"user": _user(user), "tokens": tokens, "welcome": service.welcome_payload(db, user)}


@router.post("/login")
def login(payload: LoginIn, db: DbSession, response: Response) -> dict[str, Any]:
    user = service.authenticate(db, payload.identifier, payload.password)
    db.commit()
    tokens = service.issue_tokens(user)
    _set_cookie(response, tokens)
    return {"user": _user(user), "tokens": tokens, "welcome": service.welcome_payload(db, user)}


@router.post("/refresh")
def refresh(payload: RefreshIn, db: DbSession, response: Response) -> dict[str, str]:
    tokens = service.refresh_access(payload.refresh_token)
    _set_cookie(response, tokens)
    return tokens


@router.post("/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return {
        "user": _user(user),
        "profile": {
            "id": profile.id,
            "stage_id": profile.stage_id,
            "branch_id": profile.branch_id,
            "school_name": profile.school_name,
            "daily_study_minutes": profile.daily_study_minutes,
            "study_days": profile.study_days,
            "free_windows": profile.free_windows,
            "goals": profile.goals,
            "current_level": profile.current_level,
            "onboarding_step": profile.onboarding_step,
            "diagnostic_done": profile.diagnostic_done,
            "goal_date": profile.goal_date.isoformat() if profile.goal_date else None,
        },
    }


@router.patch("/profile")
def update_profile(payload: ProfileIn, user: CurrentUser, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    service.update_profile(db, profile, payload.model_dump(exclude_none=True))
    if payload.full_name:
        user.full_name = payload.full_name
    db.commit()
    return {"ok": True, "profile_id": profile.id}


@router.put("/subjects")
def set_subjects(payload: SubjectsIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    rows = service.set_subjects(db, profile, payload.subject_ids)
    db.commit()
    return {"ok": True, "subject_ids": [r.subject_id for r in rows]}


class SettingsIn(BaseModel):
    theme: str | None = Field(default=None, pattern="^(light|dark|system)$")
    focus_mode: bool | None = None
    notification_freq: str | None = Field(default=None, pattern="^(off|quiet|normal|all)$")
    celebrate_enabled: bool | None = None
    mors_idle_enabled: bool | None = None
    mors_size: str | None = Field(default=None, pattern="^(small|normal|large)$")
    font_scale: float | None = Field(default=None, ge=0.8, le=1.6)
    high_contrast: bool | None = None
    reduce_motion: bool | None = None
    voice_enabled: bool | None = None
    tts_voice: str | None = Field(default=None, max_length=60)
    stt_provider: str | None = Field(default=None, pattern="^(browser|mock|openai)$")
    primary_color: str | None = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")


@router.get("/settings")
def get_settings(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    row = service.settings_payload(db, user)
    return {"settings": row}


@router.patch("/settings")
def patch_settings(payload: SettingsIn, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    row = service.update_settings(db, user, payload.model_dump(exclude_none=True))
    db.commit()
    return {"settings": row}


@router.get("/password-ok")
def password_policy() -> dict[str, Any]:
    return {
        "min_length": 8,
        "needs_letter": True,
        "needs_digit": True,
        "hint": "٨ أحرف على الأقل، مع حرف ورقم.",
    }


@router.post("/password")
def change_password(
    payload: PasswordIn, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    from ...core.security import hash_password, password_strength_ok

    if not password_strength_ok(payload.password):
        from ...core.errors import ValidationError

        raise ValidationError("كلمة المرور ضعيفة — تحتاج حرفاً ورقماً و٨ أحرف.")
    user.password_hash = hash_password(payload.password)
    db.commit()
    return {"ok": True}


@router.delete("/account")
def delete_account(
    payload: AccountDeleteIn, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    """§128 — حذف الحساب وكل البيانات الشخصية نهائياً."""
    from ...services import account as account_service

    result = account_service.delete_account(db, user.id, payload.password)
    db.commit()
    return result


def _user(user) -> dict[str, Any]:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "locale": user.locale,
    }


__all__ = ["router"]
