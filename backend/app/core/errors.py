"""Error taxonomy.

Every failure the API can return is one of these, so the frontend never has to
parse a string to decide what happened.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "طلب غير صالح."

    def __init__(self, message: str | None = None, *, details: Any = None, code: str | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details
        if code:
            self.code = code

    def to_dict(self) -> dict:
        payload: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            payload["error"]["details"] = self.details
        return payload


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "البيانات غير مكتملة."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "العنصر غير موجود."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "يوجد سجل مماثل."


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "يجب تسجيل الدخول."


class PermissionError_(AppError):
    status_code = 403
    code = "forbidden"
    message = "ليس لديك صلاحية لهذا الإجراء."


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "طلبات كثيرة جداً، حاول بعد قليل."


class AIError(AppError):
    status_code = 502
    code = "ai_error"
    message = "تعذر الحصول على رد من المساعد الذكي."


class NoSourceError(AppError):
    status_code = 200
    code = "no_source_found"
    message = "ما لقيت مصدراً موثوقاً يغطي هذا السؤال."


class UnsupportedFeatureError(AppError):
    status_code = 501
    code = "unsupported"
    message = "هذا الخاصية غير مفعّلة في هذه البيئة."


__all__ = [
    "AppError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "AuthenticationError",
    "PermissionError_",
    "RateLimitError",
    "AIError",
    "NoSourceError",
    "UnsupportedFeatureError",
]
