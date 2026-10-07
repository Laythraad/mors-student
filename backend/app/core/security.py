"""Password hashing and token issuing.

Deliberately dependency-free: PBKDF2-HMAC-SHA256 from the standard library for
passwords, and hand-rolled HS256 JWTs. No secret ever appears in source — all
material comes from `settings`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from ..config import settings
from .errors import AuthenticationError

_ALGO = "pbkdf2_sha256"


# --------------------------------------------------------------------------- #
# passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, settings.pbkdf2_iterations
    )
    return f"{_ALGO}${settings.pbkdf2_iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != _ALGO:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def password_strength_ok(password: str) -> bool:
    return len(password) >= 8 and not password.isspace()


# --------------------------------------------------------------------------- #
# jwt (HS256)
# --------------------------------------------------------------------------- #
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign(payload: dict[str, Any]) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    message = f"{header}.{body}".encode("ascii")
    signature = hmac.new(settings.secret_key.encode("utf-8"), message, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(signature)}"


def create_token(
    subject: str,
    *,
    token_type: str = "access",
    ttl_seconds: int | None = None,
    claims: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else settings.access_token_ttl_minutes * 60
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_hex(8),
    }
    if token_type == "refresh":
        payload["exp"] = now + (ttl or settings.refresh_token_ttl_days * 86400)
    if claims:
        payload.update(claims)
    return _sign(payload)


def decode_token(token: str, *, expected_type: str = "access") -> dict[str, Any]:
    try:
        header_b64, body_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise AuthenticationError("الرمز غير صالح.") from exc

    message = f"{header_b64}.{body_b64}".encode("ascii")
    expected = hmac.new(settings.secret_key.encode("utf-8"), message, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64url_decode(signature_b64)):
        raise AuthenticationError("الرمز غير صالح.")

    try:
        payload = json.loads(_b64url_decode(body_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationError("الرمز غير صالح.") from exc

    if payload.get("typ") != expected_type:
        raise AuthenticationError("نوع الرمز غير صالح.")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise AuthenticationError("انتهت صلاحية الجلسة، سجّل الدخول مجدداً.")
    return payload


def random_secret(nbytes: int = 32) -> str:
    return secrets.token_hex(nbytes)


__all__ = [
    "hash_password",
    "verify_password",
    "password_strength_ok",
    "create_token",
    "decode_token",
    "random_secret",
]
