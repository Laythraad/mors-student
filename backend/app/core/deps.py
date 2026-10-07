"""Shared FastAPI dependencies: authentication, roles, student context."""

from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from ..db import StudentProfile, StudentSettings, User, get_db
from .errors import AuthenticationError, PermissionError_
from .rate_limit import enforce
from .security import decode_token

ROLE_RANK = {"student": 1, "content_manager": 2, "admin": 3}

DbSession = Annotated[Session, Depends(get_db)]


def _extract_bearer(request: Request, authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    cookie = request.cookies.get("mors_access")
    if cookie:
        return cookie
    raise AuthenticationError("يجب تسجيل الدخول.")


def get_current_user(
    request: Request,
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = _extract_bearer(request, authorization)
    payload = decode_token(token, expected_type="access")
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise AuthenticationError("الحساب غير موجود أو معطّل.")
    enforce(f"user:{user.id}")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_optional_user(
    request: Request,
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    if not authorization and not request.cookies.get("mors_access"):
        return None
    try:
        return get_current_user(request, db, authorization)
    except AuthenticationError:
        return None


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def get_profile(db: DbSession, user: CurrentUser) -> StudentProfile:
    profile = (
        db.query(StudentProfile).filter(StudentProfile.user_id == user.id).one_or_none()
    )
    if profile is None:
        raise AuthenticationError("أكمل ملفك التعليمي أولاً.")
    return profile


CurrentProfile = Annotated[StudentProfile, Depends(get_profile)]


def require_role(minimum: str):
    def checker(user: CurrentUser) -> User:
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK.get(minimum, 99):
            raise PermissionError_(f"هذا الإجراء يتطلب صلاحية {minimum}.")
        return user

    return checker


AdminUser = Annotated[User, Depends(require_role("admin"))]
ManagerUser = Annotated[User, Depends(require_role("content_manager"))]


def get_settings_row(db: DbSession, user: CurrentUser) -> StudentSettings | None:
    return (
        db.query(StudentSettings).filter(StudentSettings.user_id == user.id).one_or_none()
    )


__all__ = [
    "DbSession",
    "CurrentUser",
    "OptionalUser",
    "CurrentProfile",
    "AdminUser",
    "ManagerUser",
    "get_current_user",
    "get_optional_user",
    "get_profile",
    "get_settings_row",
    "require_role",
    "ROLE_RANK",
]
