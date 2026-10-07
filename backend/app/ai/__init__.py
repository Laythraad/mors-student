"""AI layer: provider abstraction, routing, prompts and orchestrator."""

from .base import (
    ChatMessage,
    LLMResult,
    MockProvider,
    Provider,
    Tier,
    get_provider,
    reset_provider,
    resolve_model,
    set_provider,
)
from .context import (
    chunks_to_context,
    citations_from,
    compact_history,
    history_messages,
    lesson_context,
    mastery_context,
    retrieve,
    student_context,
)
from .orchestrator import AIAnswer, AIRequest, ask, ask_json, clear_cache, load_prompt_template
from .prompts import PROMPTS, PROMPT_MAP, PromptSpec, get_prompt
from .router import ROUTES, Route, route, route_name
from .structured import StructuredOutputError, extract_json

__all__ = [
    "ChatMessage",
    "LLMResult",
    "Provider",
    "Tier",
    "MockProvider",
    "get_provider",
    "set_provider",
    "reset_provider",
    "resolve_model",
    "AIRequest",
    "AIAnswer",
    "ask",
    "ask_json",
    "clear_cache",
    "load_prompt_template",
    "PROMPTS",
    "PROMPT_MAP",
    "PromptSpec",
    "get_prompt",
    "ROUTES",
    "Route",
    "route",
    "route_name",
    "student_context",
    "lesson_context",
    "mastery_context",
    "retrieve",
    "chunks_to_context",
    "citations_from",
    "history_messages",
    "compact_history",
    "extract_json",
    "StructuredOutputError",
]
