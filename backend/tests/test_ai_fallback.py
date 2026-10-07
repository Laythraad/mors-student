"""AI provider chain: fallback order, OpenAI-compatible and Ollama parsing."""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai.base import (
    ChatMessage,
    FallbackProvider,
    LLMResult,
    OllamaProvider,
    OpenAICompatProvider,
    Provider,
)
from app.core.errors import AIError


class FailProvider(Provider):
    name = "down"

    @property
    def available(self) -> bool:
        return True

    def complete(self, messages, *, tier="primary", temperature=0.4, max_tokens=2048, json_mode=False, timeout=None):
        raise AIError("مصدر معطّل.")


class OkProvider(Provider):
    name = "ok"

    @property
    def available(self) -> bool:
        return True

    def complete(self, messages, *, tier="primary", temperature=0.4, max_tokens=2048, json_mode=False, timeout=None):
        return LLMResult(text="مرحبا", model="m1", tier=tier)


class NeverProvider(Provider):
    name = "never"

    @property
    def available(self) -> bool:
        return False

    def complete(self, messages, **kwargs):
        raise AssertionError("unavailable providers must be skipped")


MSG = [ChatMessage(role="user", content="مرحبا")]


def test_fallback_serves_first_healthy_provider() -> None:
    result = FallbackProvider([FailProvider(), OkProvider()]).complete(MSG)
    assert result.text == "مرحبا"
    assert result.model == "ok/m1"  # attribution shows who actually answered


def test_fallback_all_failed_raises_with_details() -> None:
    chain = FallbackProvider([FailProvider(), FailProvider()])
    with pytest.raises(AIError) as exc:
        chain.complete(MSG)
    assert exc.value.details and "down:" in str(exc.value.details)


def test_fallback_skips_unavailable_providers() -> None:
    result = FallbackProvider([NeverProvider(), OkProvider()]).complete(MSG)
    assert result.text == "مرحبا"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_compat_parses_response() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"role": "assistant", "content": "جواب"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 5},
            },
        )

    provider = OpenAICompatProvider("t", "https://x.test", "key-1", "m", client=_client(handler))
    result = provider.complete(MSG, tier="fast")
    assert provider.available
    assert result.text == "جواب"
    assert (result.prompt_tokens, result.completion_tokens) == (3, 5)
    assert result.tier == "fast"
    assert seen["auth"] == "Bearer key-1"
    assert seen["body"]["model"] == "m"


def test_openai_compat_empty_content_is_ai_error() -> None:
    provider = OpenAICompatProvider(
        "t",
        "https://x.test",
        "key-1",
        "m",
        client=_client(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})),
    )
    with pytest.raises(AIError):
        provider.complete(MSG)


def test_ollama_native_request_and_parsing() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "message": {"role": "assistant", "content": "اهلا"},
                "done_reason": "stop",
                "prompt_eval_count": 7,
                "eval_count": 4,
            },
        )

    provider = OllamaProvider("http://127.0.0.1:11434", "qwen3:8b", num_ctx=4096, client=_client(handler))
    assert provider.available
    result = provider.complete(MSG, max_tokens=123)
    assert result.text == "اهلا"
    assert result.model == "qwen3:8b"
    assert (result.prompt_tokens, result.completion_tokens) == (7, 4)
    assert seen["body"]["think"] is False
    assert seen["body"]["stream"] is False
    assert seen["body"]["options"]["num_predict"] == 123
    assert seen["body"]["options"]["num_ctx"] == 4096


def test_ollama_empty_response_is_ai_error() -> None:
    provider = OllamaProvider(
        "http://127.0.0.1:11434",
        "qwen3:8b",
        client=_client(lambda r: httpx.Response(200, json={"message": {"content": ""}})),
    )
    with pytest.raises(AIError):
        provider.complete(MSG)
