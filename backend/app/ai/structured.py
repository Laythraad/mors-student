"""Structured-output helpers.

The model is asked for JSON; we never trust that it delivers perfect JSON.
Extraction is tolerant (fenced blocks, trailing commas, leading prose) and
every schema gets explicit defaults so a partial answer still parses.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


class StructuredOutputError(ValueError):
    pass


def extract_json(text: str) -> Any:
    """Pull the first JSON value out of a model response."""
    if not text or not text.strip():
        raise StructuredOutputError("empty response")

    candidate = text.strip()
    fence = _FENCE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()

    for attempt in (candidate, _TRAILING_COMMA.sub(r"\1", candidate)):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue

    # find the outermost object/array in a response with prose around it
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end > start:
            chunk = candidate[start : end + 1]
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                try:
                    return json.loads(_TRAILING_COMMA.sub(r"\1", chunk))
                except json.JSONDecodeError:
                    continue
    raise StructuredOutputError("no JSON found in response")


def as_dict(value: Any, *, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = dict(defaults or {})
    if isinstance(value, dict):
        out.update(value)
    elif isinstance(value, list):
        out["items"] = value
    elif value is not None:
        out["value"] = value
    return out


def as_list(value: Any, key: str = "items") -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for candidate in (key, "items", "results", "questions", "tasks", "days", "blocks"):
            if isinstance(value.get(candidate), list):
                return value[candidate]
        return list(value.values()) and [] or []
    return []


def coerce_int(value: Any, default: int = 0, *, lo: int | None = None, hi: int | None = None) -> int:
    try:
        out = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def coerce_float(value: Any, default: float = 0.0, *, lo: float | None = None, hi: float | None = None) -> float:
    try:
        out = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


__all__ = [
    "StructuredOutputError",
    "extract_json",
    "as_dict",
    "as_list",
    "coerce_int",
    "coerce_float",
]
