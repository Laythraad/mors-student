"""Mors character package: state machine, personality engine, event bus."""

from .bus import EventBus, bus
from .engine import MorsReaction, PersonalityContext, decide, idle_reaction, react
from .events import CRITICAL_IN_FOCUS, EventType, PERSISTED_EVENTS
from .messages import assert_tone, safe, templates
from .models_helper import (
    current_state,
    queue_message,
    react_and_persist,
    record_state,
)
from .states import MorsState, SPECS, all_states, spec, sprite_for

__all__ = [
    "bus",
    "EventBus",
    "react",
    "decide",
    "idle_reaction",
    "PersonalityContext",
    "MorsReaction",
    "EventType",
    "CRITICAL_IN_FOCUS",
    "PERSISTED_EVENTS",
    "MorsState",
    "SPECS",
    "spec",
    "sprite_for",
    "all_states",
    "assert_tone",
    "safe",
    "templates",
    "current_state",
    "record_state",
    "queue_message",
    "react_and_persist",
]
