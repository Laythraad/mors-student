"""One command, one production build.

    python tools/build_release.py              # full protocol, then build + verify the artifact
    python tools/build_release.py --skip-verify  # reuse the current .next, still verify the artifact

What it does, in order:
  1. verification protocol — pytest, smoke_api, e2e, uat, routes, next build,
     e2e_browser (skipped with --skip-verify, except that a missing .next is rebuilt)
  2. assemble release/ from scratch — backend code + the production .next +
     a .env generated from prod.env.example. The development .env, mors.db,
     uploads/, node_modules and tools/ are never copied in.
  3. verify the artifact by booting it as a real production process:
       - /health reports env=production, demo_data=false, docs=false
       - /api/docs is closed
       - no demo accounts (fresh database, DEMO_DATA=false)
       - a rate limit is actually enforced (not 0 / unlimited)
       - a development SECRET_KEY is refused at boot

Exit code is non-zero if any step fails: a release that does not pass all
three stages is not a release.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
RELEASE = ROOT / "release"
TEMPLATE = ROOT / "prod.env.example"
ARTIFACT_PORT = 8010
ARTIFACT_BASE = f"http://127.0.0.1:{ARTIFACT_PORT}"

sys.path.insert(0, str(BACKEND))
from app.config import DEV_SECRET_KEYS  # noqa: E402  (single source of truth)

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))
    return ok


def run(name: str, cmd: list[str], cwd: Path | None = None) -> bool:
    print(f"\n=== {name} ===")
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(cmd, cwd=str(cwd or ROOT), env=env)
    return record(name, proc.returncode == 0, f"exit={proc.returncode}")


# --------------------------------------------------------------------- stage 1
PROTOCOL: list[tuple[str, list[str]]] = [
    ("pytest", [sys.executable, "-m", "pytest", "-q"]),
    ("smoke_api", [sys.executable, "tools/smoke_api.py"]),
    ("e2e_api", [sys.executable, "tools/e2e.py"]),
    ("uat", [sys.executable, "tools/uat.py"]),
    ("frontend routes", [sys.executable, "tools/check_frontend_routes.py"]),
]


def verify_protocol() -> bool:
    print("\n########## stage 1 — verification protocol ##########")
    ok = True
    for name, cmd in PROTOCOL:
        ok = run(name, cmd) and ok
    ok = run("next build", ["npm.cmd", "run", "build"], cwd=FRONTEND) and ok
    ok = run("e2e_browser", [sys.executable, "tools/e2e_browser.py"]) and ok
    return ok


# --------------------------------------------------------------------- stage 2
def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def production_env(dev: dict[str, str]) -> str:
    """prod.env.example, with the three values only a real build can supply."""
    secret = secrets.token_urlsafe(48)
    gemini_key = dev.get("GEMINI_API_KEY", "")
    out: list[str] = []
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        if line.startswith("SECRET_KEY="):
            line = f"SECRET_KEY={secret}"
        elif line.startswith("GEMINI_API_KEY=") and gemini_key:
            line = f"GEMINI_API_KEY={gemini_key}"
        elif line.startswith("DATABASE_URL="):
            line = f"DATABASE_URL=sqlite:///{(RELEASE / 'data' / 'mors.db').as_posix()}"
        elif line.startswith("UPLOAD_DIR="):
            line = f"UPLOAD_DIR={(RELEASE / 'data' / 'uploads').as_posix()}"
        out.append(line)
    if not gemini_key:
        out.append("# WARNING: no GEMINI_API_KEY found in the development .env — AI runs on the")
        out.append("#          fallback chain until you add one.")
    return "\n".join(out) + "\n"


def copy_tree(
    src: Path,
    dst: Path,
    skip: frozenset[str] = frozenset(),
    skip_files: frozenset[str] = frozenset(),
) -> int:
    files = 0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if rel.parts and rel.parts[0] in skip:
            continue
        if rel.as_posix() in skip_files:
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        files += 1
    return files


def assemble() -> dict[str, int]:
    print("\n########## stage 2 — assemble release/ ##########")
    if RELEASE.exists():
        shutil.rmtree(RELEASE)
        print("  removed the previous release/ (there is only one build)")
    RELEASE.mkdir(parents=True)

    # app/seed.py holds the demo curriculum and demo@mors.ai / admin@mors.ai —
    # FIX §4 says the shipped build carries no seed/sample dataset at all
    backend_files = copy_tree(
        BACKEND / "app",
        RELEASE / "backend" / "app",
        skip_files=frozenset({"seed.py"}),
    )
    shutil.copy2(BACKEND / "requirements.txt", RELEASE / "backend" / "requirements.txt")
    record(
        "demo dataset not shipped (app/seed.py)",
        not (RELEASE / "backend" / "app" / "seed.py").exists(),
    )

    build_id = FRONTEND / ".next" / "BUILD_ID"
    if not build_id.exists():
        raise SystemExit("frontend/.next is missing — run the protocol (or drop --skip-verify)")
    frontend_files = copy_tree(
        FRONTEND / ".next", RELEASE / "frontend" / ".next", skip=frozenset({"cache"})
    )
    for name in ("package.json", "next.config.mjs", "jsconfig.json"):
        src = FRONTEND / name
        if src.exists():
            shutil.copy2(src, RELEASE / "frontend" / name)

    # bootstrap tooling the target machine needs, and nothing else
    (RELEASE / "tools").mkdir(parents=True)
    shutil.copy2(ROOT / "tools" / "create_admin.py", RELEASE / "tools" / "create_admin.py")
    shutil.copy2(TEMPLATE, RELEASE / "prod.env.example")

    dev = read_env(ROOT / ".env")
    (RELEASE / ".env").write_text(production_env(dev), encoding="utf-8")

    size_mb = sum(f.stat().st_size for f in RELEASE.rglob("*") if f.is_file()) / (1024 * 1024)
    counts = {"backend": backend_files, "frontend": frontend_files}
    record("release/ assembled", size_mb < 400, f"{size_mb:.1f} MB, {counts}")

    shipped = read_env(RELEASE / ".env")
    generated_ok = (
        shipped.get("APP_ENV") == "production"
        and shipped.get("DEMO_DATA") == "false"
        and shipped.get("DEBUG") == "false"
        and shipped.get("RATE_LIMIT_PER_MINUTE") not in ("0", "")
        and shipped.get("AI_RATE_LIMIT_PER_MINUTE") not in ("0", "")
        and shipped.get("SECRET_KEY", "") not in DEV_SECRET_KEYS
        and len(shipped.get("SECRET_KEY", "")) >= 32
        and shipped.get("AI_PROVIDER") != "mock"
    )
    record(
        "release/.env is a production config, not the development one",
        generated_ok,
        f"APP_ENV={shipped.get('APP_ENV')} DEMO_DATA={shipped.get('DEMO_DATA')} "
        f"SECRET_KEY=<{len(shipped.get('SECRET_KEY', ''))} chars>",
    )
    # the development database, uploads and dependency tree must never ride along
    leaked = [p.name for p in ("mors.db", "uploads", "node_modules", "_verify") if (RELEASE / p).exists()]
    record("no dev database/uploads/node_modules in the artifact", not leaked, str(leaked))
    return counts


# --------------------------------------------------------------------- stage 3
def http(url: str, method: str = "GET", payload=None, token: str | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except Exception:  # noqa: BLE001
            return exc.code, {"raw": body}
    except Exception as exc:  # noqa: BLE001
        return 0, {"raw": str(exc)}


def wait_http(url: str, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _ = http(url)
        if status == 200:
            return True
        time.sleep(0.6)
    return False


def artifact_env(db_path: Path, uploads: Path) -> dict[str, str]:
    """The shipped release/.env, pointed at a throwaway database.

    The values come from the artifact itself (not from this shell), so the
    check can never be answered by an ambient APP_ENV/DEMO_DATA variable.
    """
    env = dict(os.environ)
    env.update(read_env(RELEASE / ".env"))
    env["PYTHONUTF8"] = "1"
    env["APP_ENV"] = "production"
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["UPLOAD_DIR"] = uploads.as_posix()
    # low, but not zero: proves the limiter is on rather than "0 = unlimited"
    env["RATE_LIMIT_PER_MINUTE"] = "3"
    env["AI_RATE_LIMIT_PER_MINUTE"] = "3"
    env["SCHEDULER_ENABLED"] = "false"
    return env


def _artifact_checks(db_path: Path, uploads: Path) -> bool:
    """Assertions made against the live production process."""
    ok = True

    status, health = http(f"{ARTIFACT_BASE}/health")
    ok &= record(
        "/health reports a production build",
        status == 200
        and health.get("env") == "production"
        and health.get("demo_data") is False
        and health.get("debug") is False
        and health.get("docs") is False
        and health.get("provider") != "mock",
        json.dumps(health, ensure_ascii=False),
    )

    status, _ = http(f"{ARTIFACT_BASE}/api/docs")
    ok &= record("OpenAPI docs closed in production", status == 404, f"status={status}")

    status, _body = http(
        f"{ARTIFACT_BASE}/api/auth/login",
        "POST",
        {"identifier": "demo@mors.ai", "password": "DemoPass123!"},
    )
    ok &= record("no demo accounts on a fresh database", status == 401, f"status={status}")

    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    subjects = conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
    conn.close()
    ok &= record(
        "demo seed did not run",
        users == 0 and subjects == 0,
        f"users={users} subjects={subjects}",
    )

    status, body = http(
        f"{ARTIFACT_BASE}/api/auth/register",
        "POST",
        {
            "full_name": "Release Check",
            "email": f"release-check-{int(time.time())}@example.com",
            "password": "ReleaseCheck1!",
        },
    )
    token = (body.get("tokens") or {}).get("access_token", "")
    ok &= record("can register against the artifact", status == 200 and bool(token), f"status={status}")
    if token:
        codes = [http(f"{ARTIFACT_BASE}/api/books", token=token)[0] for _ in range(6)]
        ok &= record("rate limiting is enforced (3/min)", 429 in codes, f"statuses={codes}")

    # the gate itself: a development secret key must be refused
    bad_env = dict(os.environ)
    bad_env.update(read_env(RELEASE / ".env"))
    bad_env.update(
        {
            "PYTHONUTF8": "1",
            "APP_ENV": "production",
            "DATABASE_URL": f"sqlite:///{(RELEASE / '_verify' / 'unused.db').as_posix()}",
            "SECRET_KEY": "dev-only-change-me",
        }
    )
    gate = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=str(RELEASE / "backend"),
        env=bad_env,
        capture_output=True,
        text=True,
    )
    output = (gate.stdout or "") + (gate.stderr or "")
    ok &= record(
        "development SECRET_KEY is refused at boot",
        gate.returncode != 0 and "Refusing to start" in output,
        f"exit={gate.returncode}",
    )
    return ok


def verify_artifact() -> bool:
    print("\n########## stage 3 — boot the artifact as production ##########")
    ok = True
    workdir = RELEASE / "_verify"
    workdir.mkdir(exist_ok=True)
    db_path = workdir / "verify.db"
    uploads = workdir / "uploads"
    if db_path.exists():
        db_path.unlink()

    log = open(workdir / "uvicorn.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(ARTIFACT_PORT)],
        cwd=str(RELEASE / "backend"),
        env=artifact_env(db_path, uploads),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        if wait_http(f"{ARTIFACT_BASE}/health"):
            record("production process boots", True)
            ok = _artifact_checks(db_path, uploads)
        else:
            log.flush()
            tail = (workdir / "uvicorn.log").read_text(encoding="utf-8", errors="replace")[-1500:]
            record("production process boots", False, tail)
            ok = False
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            proc.kill()
        if not log.closed:
            log.close()
        shutil.rmtree(workdir, ignore_errors=True)

    build_id_path = RELEASE / "frontend" / ".next" / "BUILD_ID"
    build_id = build_id_path.read_text(encoding="utf-8").strip() if build_id_path.exists() else ""
    ok &= record("single production frontend build present", bool(build_id), f"BUILD_ID={build_id}")
    # byte-for-byte: the artifact serves the very build the protocol just verified
    identical = True
    for rel in ("BUILD_ID", "prerender-manifest.json", "app-build-manifest.json"):
        source = FRONTEND / ".next" / rel
        shipped_file = RELEASE / "frontend" / ".next" / rel
        if not source.exists() or not shipped_file.exists() or source.read_bytes() != shipped_file.read_bytes():
            identical = False
    ok &= record("artifact .next is identical to the verified build", identical)
    return ok


# ------------------------------------------------------------------------ main
def main() -> int:
    parser = argparse.ArgumentParser(description="build and verify one production release")
    parser.add_argument("--skip-verify", action="store_true",
                        help="skip the test protocol (the artifact is still verified)")
    args = parser.parse_args()

    if not TEMPLATE.exists():
        print(f"missing {TEMPLATE}")
        return 2

    started = datetime.now(timezone.utc)
    ok = True
    if not args.skip_verify:
        ok = verify_protocol()
    else:
        print("\n########## stage 1 — verification protocol SKIPPED ##########")

    if not ok:
        print("\nRESULT: FAILED — no release was produced")
        return 1

    assemble()
    ok = verify_artifact()

    passed = sum(1 for _, good, _ in RESULTS if good)
    failed = [name for name, good, _ in RESULTS if not good]
    print("\n########## release summary ##########")
    print(f"  built at   : {started:%Y-%m-%d %H:%M:%SZ}")
    print(f"  location   : {RELEASE}")
    print(f"  checks     : {passed}/{len(RESULTS)}")
    if failed:
        print(f"  failed     : {failed}")
    print("  start with : cd release/backend && python -m uvicorn app.main:app --port 8000")
    print("               cd release/frontend && npm ci && npm start")
    print("  first boot : python tools/create_admin.py --email you@example.com --password '...'")
    print("  NOTE       : release/.env holds a generated SECRET_KEY and your AI key — do not share it")
    print(f"\nRESULT: {'PASS' if ok and not failed else 'FAIL'}")
    return 0 if ok and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
