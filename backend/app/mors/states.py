"""Mors state machine — the canonical list of states and their official sprite.

Sprites come from `frontend/public/mors/<sprite>.png`, produced by
`tools/slice_character_sheet.py` from the official Ai.Mors character sheet.

`ANGRY` exists in the artwork but is intentionally **never** selected by the
personality engine: the product rule is motivation, not emotional
manipulation. It stays in the gallery so the art remains complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MorsState(StrEnum):
    IDLE = "idle"
    HAPPY = "happy"
    EXCITED = "excited"
    PROUD = "proud"
    CURIOUS = "curious"
    THINKING = "thinking"
    CONFUSED = "confused"
    CONCERNED = "concerned"
    SAD = "sad"
    DISAPPOINTED = "disappointed"
    ENCOURAGING = "encouraging"
    CELEBRATING = "celebrating"
    SURPRISED = "surprised"
    FOCUSED = "focused"
    SLEEPY = "sleepy"
    STUDYING = "studying"
    OVERWHELMED = "overwhelmed"
    WELCOMING = "welcoming"
    PLAYFUL = "playful"


@dataclass(frozen=True)
class StateSpec:
    key: MorsState
    sprite: str
    tone: str
    animation: str
    priority: int
    chatter: bool  # may Mors raise this on its own, unprompted?

    @property
    def sprite_file(self) -> str:
        return f"/mors/{self.sprite}.png"


SPECS: dict[MorsState, StateSpec] = {
    MorsState.IDLE: StateSpec(MorsState.IDLE, "neutral", "calm", "float", 1, True),
    MorsState.HAPPY: StateSpec(MorsState.HAPPY, "happy", "warm", "pop", 6, True),
    MorsState.EXCITED: StateSpec(MorsState.EXCITED, "excited", "energetic", "bounce", 8, True),
    MorsState.PROUD: StateSpec(MorsState.PROUD, "smug", "proud", "pop", 7, True),
    MorsState.CURIOUS: StateSpec(MorsState.CURIOUS, "wink", "curious", "tilt", 5, False),
    MorsState.THINKING: StateSpec(MorsState.THINKING, "thinking", "thoughtful", "pulse", 4, False),
    MorsState.CONFUSED: StateSpec(MorsState.CONFUSED, "confused", "puzzled", "shake", 4, False),
    MorsState.CONCERNED: StateSpec(MorsState.CONCERNED, "sad", "caring", "lean", 7, True),
    MorsState.SAD: StateSpec(MorsState.SAD, "crying", "gentle", "droop", 6, False),
    MorsState.DISAPPOINTED: StateSpec(MorsState.DISAPPOINTED, "sad", "soft", "droop", 6, False),
    MorsState.ENCOURAGING: StateSpec(MorsState.ENCOURAGING, "peaceful", "supportive", "sway", 6, True),
    MorsState.CELEBRATING: StateSpec(MorsState.CELEBRATING, "hype", "joyful", "confetti", 9, True),
    MorsState.SURPRISED: StateSpec(MorsState.SURPRISED, "shocked", "amazed", "jump", 7, False),
    MorsState.FOCUSED: StateSpec(MorsState.FOCUSED, "cool", "determined", "lock", 8, False),
    MorsState.SLEEPY: StateSpec(MorsState.SLEEPY, "tired", "sleepy", "yawn", 3, True),
    MorsState.STUDYING: StateSpec(MorsState.STUDYING, "neutral", "quiet", "still", 5, False),
    MorsState.OVERWHELMED: StateSpec(MorsState.OVERWHELMED, "overwhelmed", "overwhelmed", "wobble", 8, False),
    MorsState.WELCOMING: StateSpec(MorsState.WELCOMING, "love", "affectionate", "wave", 7, True),
    MorsState.PLAYFUL: StateSpec(MorsState.PLAYFUL, "mischievous", "playful", "wiggle", 3, True),
}


def spec(state: MorsState) -> StateSpec:
    return SPECS[state]


def sprite_for(state: MorsState | str) -> str:
    resolved = MorsState(state) if not isinstance(state, MorsState) else state
    return SPECS[resolved].sprite_file


def all_states() -> list[MorsState]:
    return list(MorsState)


__all__ = ["MorsState", "StateSpec", "SPECS", "spec", "sprite_for", "all_states"]
