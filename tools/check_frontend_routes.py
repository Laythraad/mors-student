"""Cross-check every /api/... path used by the frontend against the FastAPI routes."""

from __future__ import annotations

import glob
import io
import re
import sys

sys.path.insert(0, "backend")

from fastapi.routing import APIRoute  # noqa: E402

from app.main import create_app  # noqa: E402


def backend_routes() -> set[str]:
    app = create_app()
    out: set[str] = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                if method in ("HEAD", "OPTIONS"):
                    continue
                out.add(f"{method} {route.path}")
    return out


def frontend_calls() -> dict[str, list[str]]:
    files = (
        glob.glob("frontend/app/**/*.jsx", recursive=True)
        + glob.glob("frontend/components/*.jsx")
        + glob.glob("frontend/lib/*.js")
    )
    calls: dict[str, list[str]] = {}
    for path in files:
        src = io.open(path, encoding="utf-8").read()
        src = re.sub(r"\$\{[^}]*\}", "*", src)  # template placeholders -> *
        name = path.replace("\\", "/")
        for match in re.finditer(r"(api|fetch)\(\s*[\"'`](/api/[^\"'`]+)[\"'`]", src):
            url = match.group(2).split("?")[0]
            calls.setdefault(url, []).append(name)
    return calls


def _segments(path: str) -> list[str]:
    """Split a path into segments with `{...}` and `*` treated as wildcards."""
    out: list[str] = []
    for seg in path.split("/"):
        if not seg:
            continue
        out.append("*" if seg == "*" or (seg.startswith("{") and seg.endswith("}")) else seg)
    return out


def matches(path_template: str, url: str) -> bool:
    left, right = _segments(path_template), _segments(url)
    return len(left) == len(right) and all(
        a == b or a == "*" or b == "*" for a, b in zip(left, right)
    )


def main() -> int:
    routes = backend_routes()
    paths = {r.split(" ", 1)[1] for r in routes}
    calls = frontend_calls()
    missing: list[str] = []
    for url, where in sorted(calls.items()):
        if not any(matches(p, url) for p in paths):
            missing.append(f"{url}  <- {sorted(set(where))}")
    print(f"backend routes: {len(routes)}   frontend api() calls: {len(calls)}")
    if missing:
        print("UNMATCHED:")
        for line in missing:
            print("  " + line)
        return 1
    print("all frontend api() paths resolve to a backend route")
    return 0


if __name__ == "__main__":
    sys.exit(main())
