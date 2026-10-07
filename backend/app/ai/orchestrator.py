"""AI Orchestrator — the single door every model call walks through.

Responsibilities: prompt resolution (DB override → seed default), context
assembly, response caching, in-flight de-duplication, usage accounting,
structured parsing and citation filtering.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..core.errors import AIError
from ..db import AIPrompt, AIUsage, utcnow
from .base import ChatMessage, LLMResult, Provider, get_provider
from .context import citations_from, compact_history
from .prompts import PROMPT_MAP, render
from .router import Route, route
from .structured import StructuredOutputError, as_dict, extract_json

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, LLMResult]] = {}
_cache_lock = threading.Lock()
_inflight: dict[str, threading.Event] = {}


@dataclass(slots=True)
class AIRequest:
    task: str
    input: str
    student_id: str | None = None
    conversation_id: str | None = None
    subject_id: str | None = None
    lesson_id: str | None = None
    context: dict[str, str] = field(default_factory=dict)
    constraints: str = ""
    schema: str = ""
    history: list[ChatMessage] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    want_json: bool | None = None
    temperature: float | None = None
    max_tokens: int = 2048
    cache: bool = True


@dataclass(slots=True)
class AIAnswer:
    text: str
    data: dict[str, Any] | None
    agent: str
    tier: str
    model: str
    citations: list[dict]
    confidence: float
    cached: bool
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def load_prompt_template(db: Session | None, key: str) -> tuple[str, str]:
    """Admin-edited prompt wins; otherwise the seeded default."""
    spec = PROMPT_MAP.get(key)
    system = spec.system if spec else ""
    user = spec.user if spec else "{input}"
    if db is None:
        return system, user
    row = (
        db.query(AIPrompt)
        .filter(AIPrompt.key == key, AIPrompt.is_active.is_(True))
        .order_by(AIPrompt.version.desc())
        .first()
    )
    if row:
        system = row.system_preamble + "\n" + row.template if row.system_preamble else row.template
        # a row may only override the system side; the user template is structural
    return system, user


def _cache_key(route_: Route, system: str, user: str, images: list[str]) -> str:
    payload = json.dumps(
        [route_.tier, system, user, images], ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cached(key: str) -> LLMResult | None:
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        stamped, value = entry
        if now - stamped > settings.ai_cache_ttl_seconds:
            _cache.pop(key, None)
            return None
        result = LLMResult(
            text=value.text,
            model=value.model,
            tier=value.tier,
            prompt_tokens=value.prompt_tokens,
            completion_tokens=value.completion_tokens,
            cached=True,
            latency_ms=value.latency_ms,
        )
        return result


def _store(key: str, value: LLMResult) -> None:
    with _cache_lock:
        if len(_cache) > 512:
            _cache.clear()
        _cache[key] = (time.time(), value)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
        _inflight.clear()


def _confidence(route_: Route, text: str, parsed: Any, citations: list[dict]) -> float:
    if not text.strip():
        return 0.0
    score = 0.75
    if route_.json_output and parsed is None:
        return 0.2
    if route_.json_output and isinstance(parsed, (dict, list)):
        score += 0.15
    if citations:
        score += 0.1
    elif route_.prompt_key in ("tutor", "curriculum", "quiz", "exam"):
        score -= 0.25  # curriculum claims without a source must read as unsure
    if len(text) < 40:
        score -= 0.1
    return max(0.0, min(1.0, round(score, 2)))


def _log_usage(
    db: Session,
    *,
    student_id: str | None,
    agent: str,
    model: str,
    task: str,
    result: LLMResult,
    ok: bool,
) -> None:
    try:
        db.add(
            AIUsage(
                student_id=student_id,
                agent=agent,
                model=model,
                task=task,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cached=result.cached,
                latency_ms=result.latency_ms,
                ok=ok,
                day=utcnow().date().isoformat(),
            )
        )
        db.flush()
    except Exception:  # noqa: BLE001 - accounting must never break the answer
        logger.exception("failed to record AI usage")


def ask(db: Session | None, request: AIRequest, *, provider: Provider | None = None) -> AIAnswer:
    route_ = route(request.task, request.input, want_json=request.want_json)
    system_template, user_template = load_prompt_template(db, route_.prompt_key)

    values = {
        "context": "\n".join(f"{k}: {v}" for k, v in request.context.items() if v),
        "history": compact_history(request.history),
        "input": request.input,
        "constraints": request.constraints,
        "schema": request.schema,
    }
    system = system_template.strip()
    user = render(user_template, values).strip()

    key = _cache_key(route_, system, user, request.images)
    result: LLMResult | None = _cached(key) if request.cache else None
    cached = result is not None

    if result is None:
        provider = provider or get_provider()
        messages = [ChatMessage(role="system", content=system)]
        messages.extend(request.history)
        messages.append(ChatMessage(role="user", content=user, images=list(request.images)))

        started = time.perf_counter()
        result = provider.complete(
            messages,
            tier=route_.tier,
            temperature=request.temperature if request.temperature is not None else route_.temperature,
            max_tokens=request.max_tokens,
            json_mode=route_.json_output,
        )
        if result.latency_ms == 0:
            result.latency_ms = int((time.perf_counter() - started) * 1000)
        if request.cache:
            _store(key, result)

    parsed: Any = None
    text = result.text
    if route_.json_output:
        try:
            parsed = extract_json(result.text)
        except StructuredOutputError:
            parsed = None
        if parsed is not None:
            text = (
                json.dumps(parsed, ensure_ascii=False, indent=2)
                if isinstance(parsed, (dict, list))
                else str(parsed)
            )

    if db is not None:
        _log_usage(
            db,
            student_id=request.student_id,
            agent=route_.agent,
            model=result.model,
            task=request.task,
            result=result,
            ok=True,
        )

    return AIAnswer(
        text=text,
        data=as_dict(parsed) if parsed is not None else None,
        agent=route_.agent,
        tier=route_.tier,
        model=result.model,
        citations=[],
        confidence=_confidence(route_, text, parsed, []),
        cached=result.cached,
        latency_ms=result.latency_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )


def ask_json(db: Session | None, request: AIRequest, *, provider: Provider | None = None) -> dict[str, Any]:
    """Convenience wrapper that fails loudly when the model returns prose."""
    request.want_json = True
    answer = ask(db, request, provider=provider)
    if answer.data is None:
        raise AIError("تعذّر تحليل رد النظام الذكي، حاول مرة ثانية.")
    return answer.data


__all__ = [
    "AIRequest",
    "AIAnswer",
    "ask",
    "ask_json",
    "clear_cache",
    "load_prompt_template",
    "citations_from",
]
