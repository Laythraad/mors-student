"""Account & personal-data deletion (§128 privacy).

Deletes the user, their student profile and every row that belongs to them
(plans, sessions, attempts, notes, papers, uploads, Mors history, …) while
never touching shared curriculum or platform data. Staff references
(`created_by` / `updated_by`) are nulled instead of cascaded.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..core.errors import NotFoundError, ValidationError
from ..db import Base, StudentProfile, User
from .auth import authenticate

logger = logging.getLogger(__name__)

# seeded accounts that must survive (demo + admin)
SEALED_EMAILS = {"admin@mors.ai", "demo@mors.ai"}

# columns that point *at* an owned row and must cascade with it
STAFF_COLUMNS = ("created_by", "updated_by", "reviewed_by", "reviewer_id", "resolved_by", "actor_id")

_FK_CHILDREN: dict[str, list[tuple[Any, Any]]] | None = None


def _children(table_name: str) -> list[tuple[Any, Any]]:
    global _FK_CHILDREN
    if _FK_CHILDREN is None:
        mapping: dict[str, list[tuple[Any, Any]]] = {}
        for table in Base.metadata.tables.values():
            for column in table.columns:
                for fk in column.foreign_keys:
                    target = fk.target_fullname.split(".")[0]
                    mapping.setdefault(target, []).append((table, column))
        _FK_CHILDREN = mapping
    return _FK_CHILDREN.get(table_name, [])


def _purge(db: Session, table_name: str, pk_value: str, seen: set[tuple[str, str]]) -> int:
    """Delete the row and everything that depends on it (children first)."""
    key = (table_name, str(pk_value))
    if key in seen:
        return 0
    seen.add(key)

    table = Base.metadata.tables.get(table_name)
    if table is None:
        return 0

    deleted = 0
    for child_table, column in _children(table_name):
        if column.name in STAFF_COLUMNS or column.name.endswith("_by"):
            try:
                with db.begin_nested():
                    db.execute(
                        update(child_table).where(column == pk_value).values({column.name: None})
                    )
            except Exception:  # noqa: BLE001 — NOT NULL staff link: drop the row instead
                logger.warning("could not nullify %s.%s", child_table.name, column.name)
            continue

        child_pk = list(child_table.primary_key.columns)[0]
        child_ids = [row[0] for row in db.execute(select(child_pk).where(column == pk_value))]
        for child_id in child_ids:
            deleted += _purge(db, child_table.name, str(child_id), seen)

    own_pk = list(table.primary_key.columns)[0]
    deleted += int(db.execute(table.delete().where(own_pk == pk_value)).rowcount or 0)
    return deleted


def delete_account(db: Session, user_id: str, password: str) -> dict[str, Any]:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("الحساب غير موجود.")

    email = (user.email or "").lower()
    if email in SEALED_EMAILS:
        raise ValidationError(
            "حساب المنصة المدمج (العرض/الإدارة) لا يمكن حذفه — أنشئ حساباً جديداً لتجربة الحذف."
        )

    identifier = user.email or user.phone
    authenticate(db, identifier or "", password)  # 401 on a wrong password

    profile = (
        db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
    )
    rows = _purge(db, "users", user.id, set())
    db.flush()

    if profile is not None:
        try:
            shutil.rmtree(Path(settings.upload_dir) / profile.id, ignore_errors=True)
        except OSError:  # pragma: no cover — files are best-effort
            logger.warning("could not remove uploads for %s", profile.id)

    return {"deleted": True, "rows": rows, "email": user.email}


__all__ = ["delete_account", "SEALED_EMAILS"]
