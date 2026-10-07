"""Create the first administrator on a database that has no demo seed.

Production ships with DEMO_DATA=false (backend/app/config.py), so a fresh
release contains no accounts at all. This is the supported bootstrap — the
inline `python -c` one-liner used to live in docs/DEPLOYMENT.md §1.

    python tools/create_admin.py --email admin@example.com --password 'Str0ngPass!'

Idempotent: an existing account with that email is reported, never overwritten.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.core.errors import AppError  # noqa: E402
from app.db import SessionLocal, User  # noqa: E402
from app.services import auth  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="create an administrator account")
    parser.add_argument("--email", required=True, help="login address")
    parser.add_argument("--password", required=True, help="8+ chars (register rule)")
    parser.add_argument("--name", default="Administrator", help="display name")
    args = parser.parse_args()

    email = args.email.strip().lower()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).one_or_none()
        if existing is not None:
            if existing.role == "admin":
                print(f"OK (already an admin): {email}")
                return 0
            print(f"REFUSED: {email} exists as role={existing.role}")
            return 1

        user = auth.register(
            db,
            full_name=args.name.strip() or "Administrator",
            email=email,
            password=args.password,
            role="admin",
        )
        db.commit()
    except AppError as exc:
        print(f"FAILED: {exc.message}")
        return 1
    finally:
        db.close()

    print(f"OK: created admin {email} (id={user.id})")
    print("next: sign in, then publish real curriculum from /admin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
