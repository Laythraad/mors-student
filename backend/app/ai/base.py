"""AI provider abstraction.

Model names exist **only** here. Every other module asks for a *tier*
(`fast` | `primary` | `reasoning` | `vision`) and gets whatever the current
configuration resolves it to, so the vendor/model can be swapped from `.env`
without touching a single feature file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from ..config import settings
from ..core.errors import AIError

logger = logging.getLogger(__name__)

Tier = Literal["fast", "primary", "reasoning", "vision"]


def resolve_model(tier: Tier) -> str:
    return {
        "fast": settings.ai_fast_model,
        "primary": settings.ai_model,
        "reasoning": settings.ai_reasoning_model,
        "vision": settings.ai_vision_model,
    }.get(tier, settings.ai_model)


@dataclass(slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str
    images: list[str] = field(default_factory=list)  # base64 data URLs


@dataclass(slots=True)
class LLMResult:
    text: str
    model: str
    tier: Tier
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tier: Tier = "primary",
        temperature: float = 0.4,
        max_tokens: int = 2048,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> LLMResult: ...

    @property
    @abstractmethod
    def available(self) -> bool: ...


# --------------------------------------------------------------------------- #
# Gemini (REST — no heavyweight SDK, so a provider swap stays cheap)
# --------------------------------------------------------------------------- #
class GeminiProvider(Provider):
    name = "gemini"
    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str):
        self._key = api_key
        self._client = httpx.Client(timeout=settings.ai_timeout_seconds)

    @property
    def available(self) -> bool:
        return bool(self._key)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tier: Tier = "primary",
        temperature: float = 0.4,
        max_tokens: int = 2048,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> LLMResult:
        if not self.available:
            raise AIError("مفتاح Gemini غير مكوّن — أضف GEMINI_API_KEY.")

        model = resolve_model(tier)
        system_parts = [m.content for m in messages if m.role == "system"]
        contents: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue
            parts: list[dict[str, Any]] = [{"text": m.content}]
            for image in m.images:
                if "," in image:
                    header, data = image.split(",", 1)
                    mime = header.split(":", 1)[-1].split(";")[0] or "image/png"
                    parts.append(
                        {
                            "inline_data": {"mime_type": mime, "data": data},
                        }
                    )
            contents.append({"role": "model" if m.role == "assistant" else "user", "parts": parts})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        started = time.perf_counter()
        url = self.ENDPOINT.format(model=model)
        data = self._post(url, payload, timeout)

        text, finish_reason = self._extract(data)
        if not text.strip():
            # A thinking model can burn maxOutputTokens on thoughts and return an
            # empty body (finishReason=MAX_TOKENS). One forced retry without
            # thinking sends the whole budget to visible text.
            cfg = payload["generationConfig"]
            cfg["thinkingConfig"] = {"thinkingBudget": 0}
            cfg["maxOutputTokens"] = max(max_tokens, 2048)
            data = self._post(url, payload, timeout)
            text, finish_reason = self._extract(data)
        if not text.strip():
            logger.warning("gemini empty text model=%s finish=%s", model, finish_reason)
            raise AIError(
                "رد المساعد فارغ — جرّب سؤالاً أقصر أو أعد المحاولة.",
                details={"finish_reason": finish_reason},
            )

        usage = data.get("usageMetadata", {}) or {}
        return LLMResult(
            text=text,
            model=model,
            tier=tier,
            prompt_tokens=int(usage.get("promptTokenCount", 0) or 0),
            completion_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw={"finishReason": finish_reason},
        )

    RETRYABLE = frozenset({429, 500, 502, 503, 504})
    BACKOFF = (2.0, 4.0, 8.0, 12.0)
    DEADLINE_SECONDS = 100.0

    def _post(self, url: str, payload: dict[str, Any], timeout: float | None) -> dict[str, Any]:
        """POST with backoff on transient upstream failures (429/5xx/network)."""
        deadline = time.perf_counter() + self.DEADLINE_SECONDS
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.post(
                    url,
                    params={"key": self._key},
                    json=payload,
                    timeout=timeout or settings.ai_timeout_seconds,
                )
            except httpx.HTTPError as exc:
                logger.warning("gemini transport error (attempt %d): %s", attempt, exc)
                if attempt > len(self.BACKOFF) or time.perf_counter() >= deadline:
                    raise AIError(f"تعذّر الاتصال بخدمة الذكاء الاصطناعي: {exc}") from exc
                time.sleep(self.BACKOFF[attempt - 1])
                continue

            if response.status_code < 400:
                try:
                    data = response.json()
                except ValueError as exc:
                    raise AIError("رد غير متوقع من خدمة الذكاء الاصطناعي.") from exc
                if not isinstance(data, dict):
                    raise AIError("رد غير متوقع من خدمة الذكاء الاصطناعي.")
                return data

            detail = response.text[:300]
            logger.warning("gemini error %s (attempt %d): %s", response.status_code, attempt, detail)
            can_retry = attempt <= len(self.BACKOFF) and time.perf_counter() < deadline
            if response.status_code in self.RETRYABLE and can_retry:
                time.sleep(self._retry_delay(response, attempt))
                continue
            if response.status_code == 400 and payload.get("generationConfig", {}).get("thinkingConfig"):
                # This model may not accept thinkingConfig — drop it and retry plain.
                payload["generationConfig"].pop("thinkingConfig", None)
                continue
            raise AIError(
                f"خدمة الذكاء الاصطناعي رفضت الطلب ({response.status_code}).",
                details={"status": response.status_code},
            )

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        delay = self.BACKOFF[attempt - 1]
        if response.status_code == 429:
            delay *= 2.0  # quota windows are longer than overload hiccups
        header = response.headers.get("retry-after")
        if header:
            try:
                delay = min(max(float(header), delay), 60.0)
            except ValueError:
                pass
        return min(delay, 60.0)

    @staticmethod
    def _extract(data: dict[str, Any]) -> tuple[str, str | None]:
        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback") or {}
            raise AIError("لم يُرجع النموذج إجابة لهذا السؤال.", details=feedback or None)
        first = candidates[0]
        parts = (first.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        return text, first.get("finishReason")


# --------------------------------------------------------------------------- #
# Shared retry for the OpenAI-compatible providers (Groq, OpenRouter, Ollama)
# --------------------------------------------------------------------------- #
_RETRYABLE = frozenset({429, 500, 502, 503, 504})
_BACKOFF = (2.0, 4.0, 8.0, 12.0)
_DEADLINE_SECONDS = 100.0


def _post_json(
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    label: str = "ai",
) -> dict[str, Any]:
    """POST JSON with the same backoff policy as the Gemini provider."""
    deadline = time.perf_counter() + _DEADLINE_SECONDS
    attempt = 0
    while True:
        attempt += 1
        try:
            response = client.post(
                url,
                json=payload,
                headers=headers or {},
                timeout=timeout or settings.ai_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            logger.warning("%s transport error (attempt %d): %s", label, attempt, exc)
            if attempt > len(_BACKOFF) or time.perf_counter() >= deadline:
                raise AIError(f"تعذّر الاتصال بخدمة {label}: {exc}") from exc
            time.sleep(_BACKOFF[attempt - 1])
            continue

        if response.status_code < 400:
            try:
                data = response.json()
            except ValueError as exc:
                raise AIError(f"رد غير متوقع من {label}.") from exc
            if not isinstance(data, dict):
                raise AIError(f"رد غير متوقع من {label}.")
            return data

        detail = response.text[:300]
        logger.warning("%s error %s (attempt %d): %s", label, response.status_code, attempt, detail)
        can_retry = attempt <= len(_BACKOFF) and time.perf_counter() < deadline
        if response.status_code in _RETRYABLE and can_retry:
            delay = _BACKOFF[attempt - 1]
            if response.status_code == 429:
                delay *= 2.0  # quota windows are longer than overload hiccups
            time.sleep(min(delay, 60.0))
            continue
        raise AIError(
            f"خدمة {label} رفضت الطلب ({response.status_code}).",
            details={"status": response.status_code},
        )


# --------------------------------------------------------------------------- #
# OpenAI-compatible endpoints (Groq, OpenRouter, vLLM, …)
# --------------------------------------------------------------------------- #
class OpenAICompatProvider(Provider):
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
    ):
        self.name = name
        self._base = (base_url or "").rstrip("/")
        self._key = api_key
        self.model = model
        self._client = client or httpx.Client(timeout=settings.ai_timeout_seconds)

    @property
    def available(self) -> bool:
        return bool(self._base and self._key and self.model)

    @staticmethod
    def _content(m: ChatMessage) -> Any:
        if not m.images:
            return m.content
        parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
        parts.extend({"type": "image_url", "image_url": {"url": img}} for img in m.images)
        return parts

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tier: Tier = "primary",
        temperature: float = 0.4,
        max_tokens: int = 2048,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": self._content(m)} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        data = _post_json(
            self._client,
            f"{self._base}/chat/completions",
            payload,
            headers={"Authorization": f"Bearer {self._key}"},
            timeout=timeout,
            label=self.name,
        )
        try:
            choice = data["choices"][0]
            text = (choice.get("message") or {}).get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(f"رد غير متوقع من {self.name}.") from exc
        if not text.strip():
            raise AIError(
                f"رد فارغ من {self.name}.",
                details={"finish_reason": choice.get("finish_reason")},
            )
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            model=str(data.get("model") or self.model),
            tier=tier,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw={"finishReason": choice.get("finish_reason")},
        )


# --------------------------------------------------------------------------- #
# Ollama — local daemon (native /api/chat keeps think/num_ctx control)
# --------------------------------------------------------------------------- #
class OllamaProvider(Provider):
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        num_ctx: int = 8192,
        client: httpx.Client | None = None,
    ):
        self._base = (base_url or "").rstrip("/")
        self.model = model
        self._num_ctx = num_ctx
        self._client = client or httpx.Client(timeout=settings.ai_timeout_seconds)

    @property
    def available(self) -> bool:
        return bool(self._base and self.model)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tier: Tier = "primary",
        temperature: float = 0.4,
        max_tokens: int = 2048,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> LLMResult:
        out_messages: list[dict[str, Any]] = []
        for m in messages:
            if m.images:
                # local model is text-only — never send it image payloads
                logger.warning("ollama: dropping %d image(s) (text-only model)", len(m.images))
            out_messages.append({"role": m.role, "content": m.content})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": out_messages,
            "stream": False,
            "think": False,  # qwen3-style thinking models answer directly
            "options": {"num_ctx": self._num_ctx, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"

        started = time.perf_counter()
        data = _post_json(
            self._client,
            f"{self._base}/api/chat",
            payload,
            timeout=timeout,
            label=self.name,
        )
        text = ((data.get("message") or {}).get("content")) or ""
        if not text.strip():
            raise AIError("رد فارغ من ollama.")
        return LLMResult(
            text=text,
            model=str(data.get("model") or self.model),
            tier=tier,
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw={"finishReason": data.get("done_reason")},
        )


# --------------------------------------------------------------------------- #
# Fallback chain — tries each available provider until one answers
# --------------------------------------------------------------------------- #
class FallbackProvider(Provider):
    name = "fallback"

    def __init__(self, providers: list[Provider]):
        self.providers = [p for p in providers if p.available]

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tier: Tier = "primary",
        temperature: float = 0.4,
        max_tokens: int = 2048,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> LLMResult:
        errors: list[str] = []
        for provider in self.providers:
            try:
                result = provider.complete(
                    messages,
                    tier=tier,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    timeout=timeout,
                )
            except AIError as exc:
                logger.warning("provider %s failed, falling back: %s", provider.name, exc.message)
                errors.append(f"{provider.name}: {exc.message}")
                continue
            if provider is not self.providers[0]:
                logger.info("served by fallback provider %s", provider.name)
            # attribution: usage logs show which provider actually answered
            result.model = f"{provider.name}/{result.model}"
            return result
        raise AIError(
            "تعذّر الحصول على رد من أي مصدر ذكي حالياً — أعد المحاولة بعد قليل.",
            details=errors or None,
        )


# --------------------------------------------------------------------------- #
# Mock — deterministic, offline. Used in tests, demos and when no key exists.
# --------------------------------------------------------------------------- #
class MockProvider(Provider):
    name = "mock"

    @property
    def available(self) -> bool:
        return True

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tier: Tier = "primary",
        temperature: float = 0.4,
        max_tokens: int = 2048,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> LLMResult:
        started = time.perf_counter()
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        digest = hashlib.sha256(f"{tier}|{last_user}".encode()).hexdigest()

        if json_mode:
            text = json.dumps(
                {"echo": last_user[:160], "mock": True, "seed": digest[:8]},
                ensure_ascii=False,
            )
        else:
            text = (
                "هذه إجابة تجريبية من وضع المحاكاة (MOEM). "
                "اربط GEMINI_API_KEY في ملف .env للحصول على ردود حقيقية.\n\n"
                f"فهمت سؤالك: {last_user[:220]}"
            )
        return LLMResult(
            text=text,
            model="mock",
            tier=tier,
            prompt_tokens=len(last_user) // 4,
            completion_tokens=len(text) // 4,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


# --------------------------------------------------------------------------- #
_provider: Provider | None = None


def _build_provider(name: str) -> Provider | None:
    if name == "gemini":
        return GeminiProvider(settings.gemini_api_key) if settings.gemini_api_key else None
    if name == "groq":
        return OpenAICompatProvider("groq", settings.groq_base_url, settings.groq_api_key, settings.groq_model)
    if name == "openrouter":
        return OpenAICompatProvider(
            "openrouter", settings.openrouter_base_url, settings.openrouter_api_key, settings.openrouter_model
        )
    if name == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model, settings.ollama_num_ctx)
    logger.warning("unknown ai provider %r in AI_PROVIDERS", name)
    return None


def get_provider() -> Provider:
    global _provider
    if _provider is None:
        if settings.ai_provider == "mock":
            _provider = MockProvider()
        else:
            names = [n.strip().lower() for n in settings.ai_providers.split(",") if n.strip()]
            chain = [p for p in (_build_provider(n) for n in names) if p is not None and p.available]
            if chain:
                _provider = FallbackProvider(chain)
            else:
                logger.info("no AI provider configured — using mock")
                _provider = MockProvider()
    return _provider


def set_provider(provider: Provider | None) -> None:
    """Test seam — lets the suite inject a recording stub."""
    global _provider
    _provider = provider


def reset_provider() -> None:
    global _provider
    _provider = None


__all__ = [
    "Tier",
    "ChatMessage",
    "LLMResult",
    "Provider",
    "GeminiProvider",
    "MockProvider",
    "OpenAICompatProvider",
    "OllamaProvider",
    "FallbackProvider",
    "get_provider",
    "set_provider",
    "reset_provider",
    "resolve_model",
]
