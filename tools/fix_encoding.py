"""Detect (and repair) double-encoded Arabic in project source files.

Run:  python -X utf8 tools/fix_encoding.py [--apply]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")

EXTS = {".py", ".md", ".json", ".txt", ".csv", ".html", ".css"}


def looks_mojibake(text: str) -> bool:
    if not any("؀" <= ch <= "ۿ" for ch in text):
        return False
    # real Arabic never contains these tell-tale cp1256-as-utf8 artefacts
    artefacts = ("ط§", "ط§ظ", "ظ„", "ظ†", "ط©", "ظˆ", "ظ‰", "ط°", "ط´", "â€", "\x00")
    if any(a in text for a in artefacts):
        return True
    return False


def repair(text: str) -> str | None:
    try:
        fixed = text.encode("cp1256").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if not any("؀" <= ch <= "ۿ" for ch in fixed):
        return None
    if fixed.count("ط") > text.count("ط") * 0.5:
        return None
    return fixed


def main() -> int:
    apply_fix = "--apply" in sys.argv
    changed = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix.lower() not in EXTS or path.name == Path(__file__).name:
            continue
        if any(p in {".git", "node_modules", "__pycache__"} for p in path.parts):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not looks_mojibake(original):
            continue
        fixed = repair(original)
        if fixed is None:
            print(f"[skip] {path.relative_to(ROOT)} (looks odd, manual review)")
            continue
        changed.append(path.relative_to(ROOT))
        if apply_fix:
            path.write_text(fixed, encoding="utf-8", newline="")
    for rel in changed:
        print(("[fixed] " if apply_fix else "[found] ") + str(rel))
    print(f"{len(changed)} file(s)" + ("" if apply_fix else " — pass --apply to rewrite"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
