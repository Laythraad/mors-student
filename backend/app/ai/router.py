"""AI Router — decides *who* answers and *how much* model it needs.

Routing is a pure lookup (no model call), so switching models never costs a
request, and a cheap task never reaches the expensive tier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .base import Tier
from .prompts import PROMPT_MAP, PromptSpec

DEFAULT_PROMPT = "tutor"


@dataclass(frozen=True)
class Route:
    agent: str
    prompt_key: str
    tier: Tier
    json_output: bool = False
    temperature: float = 0.4

    @property
    def prompt(self) -> PromptSpec:
        return PROMPT_MAP[self.prompt_key]


# task name -> route
ROUTES: dict[str, Route] = {
    "chat": Route("tutor", "tutor", "fast"),
    "explain": Route("tutor", "tutor", "primary"),
    "answer": Route("tutor", "tutor", "primary"),
    "socratic_hint": Route("tutor", "tutor", "primary", temperature=0.5),
    "curriculum": Route("curriculum", "curriculum", "fast"),
    "plan": Route("planner", "planner", "reasoning", json_output=True, temperature=0.3),
    "plan_recovery": Route("planner", "planner", "reasoning", json_output=True, temperature=0.3),
    "exam_plan": Route("exam", "exam", "reasoning", json_output=True, temperature=0.3),
    "quiz": Route("quiz", "quiz", "primary", json_output=True, temperature=0.6),
    "summarize": Route("summarizer", "summarizer", "fast", json_output=True, temperature=0.3),
    "coach": Route("coach", "coach", "fast", json_output=True, temperature=0.4),
    "paper": Route("paper", "paper", "primary", json_output=True, temperature=0.5),
    "vision": Route("vision", "vision", "vision", json_output=True, temperature=0.2),
    "title": Route("title", "title", "fast", temperature=0.2),
}

# cheap-task detection keeps simple turns on the fast tier
_FAST_PATTERNS = re.compile(
    r"^(مرحبا|هلا|السلام|صباح|مساء|شكرا|شكراً|من انت|مين انت|شلونك|هاي)\b", re.U
)


def route(task: str, user_input: str = "", *, want_json: bool | None = None) -> Route:
    """Resolve the route for `task`, downgrading to `fast` for chit-chat."""
    base = ROUTES.get(task) or ROUTES[DEFAULT_PROMPT]
    tier = base.tier
    if task in ("chat", "explain", "answer") and user_input:
        if len(user_input) < 24 and _FAST_PATTERNS.search(user_input.strip()):
            tier = "fast"
    json_output = base.json_output if want_json is None else want_json
    return Route(base.agent, base.prompt_key, tier, json_output, base.temperature)


def route_name(task: str) -> str:
    return (ROUTES.get(task) or ROUTES[DEFAULT_PROMPT]).agent


__all__ = ["Route", "ROUTES", "route", "route_name", "DEFAULT_PROMPT"]
