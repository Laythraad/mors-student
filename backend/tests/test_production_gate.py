"""Production gates — what a shipped build refuses to boot with (FIX §4).

The rule these encode: a developer default (public signing key, switched-off
rate limiter) must stop the process, while a leftover (demo seed, debug flag,
mock AI) must boot but never silently.
"""

from __future__ import annotations

import logging

import pytest

from app.config import DEV_SECRET_KEYS, Settings, TEST_RATE_LIMIT
from app.main import _enforce_production_policy

A_REAL_KEY = "a-real-release-key-nothing-shared-0123456789"


def prod(**overrides) -> Settings:
    base: dict = {
        "_env_file": None,
        "app_env": "production",
        "secret_key": A_REAL_KEY,
        "rate_limit_per_minute": 120,
        "ai_rate_limit_per_minute": 30,
        "demo_data": False,
        "debug": False,
        "ai_provider": "gemini",
    }
    base.update(overrides)
    return Settings(**base)


def test_demo_data_and_debug_default_to_off():
    # a build that forgets to configure anything must stay empty
    assert Settings.model_fields["demo_data"].default is False
    assert Settings.model_fields["debug"].default is False


def test_non_production_environments_are_never_blocked():
    assert Settings(app_env="development", _env_file=None).production_blockers() == []
    assert Settings(app_env="development", _env_file=None).production_warnings() == []
    assert Settings(app_env="test", _env_file=None).production_blockers() == []


@pytest.mark.parametrize("secret", sorted(DEV_SECRET_KEYS))
def test_development_secret_keys_are_refused(secret: str):
    blockers = prod(secret_key=secret).production_blockers()
    assert any("SECRET_KEY" in problem for problem in blockers), blockers


def test_switched_off_rate_limits_are_refused():
    assert any("RATE_LIMIT" in p for p in prod(rate_limit_per_minute=0).production_blockers())
    assert any("AI_RATE_LIMIT" in p for p in prod(ai_rate_limit_per_minute=0).production_blockers())


def test_a_clean_production_configuration_passes():
    assert prod(rate_limit_per_minute=TEST_RATE_LIMIT - 1).production_blockers() == []


def test_leftovers_are_warnings_not_blockers():
    cfg = prod(
        demo_data=True,
        debug=True,
        ai_provider="mock",
        rate_limit_per_minute=TEST_RATE_LIMIT + 100,
        cors_origins="*",
    )
    assert cfg.production_blockers() == []
    text = "\n".join(cfg.production_warnings())
    for needle in ("DEMO_DATA", "DEBUG", "mock", "RATE_LIMIT", "*"):
        assert needle in text, (needle, text)


def test_openapi_stays_open_in_development_and_closes_in_production():
    assert Settings(app_env="development", debug=False, _env_file=None).docs_enabled is True
    assert Settings(app_env="test", debug=False, _env_file=None).docs_enabled is True
    assert prod(debug=False).docs_enabled is False
    # the debug escape hatch keeps docs for a production process running in debug
    assert prod(debug=True).docs_enabled is True


def test_startup_gate_rejects_a_blocked_configuration():
    with pytest.raises(RuntimeError, match="Refusing to start"):
        _enforce_production_policy(prod(secret_key="dev-only-change-me"))
    with pytest.raises(RuntimeError, match="Refusing to start"):
        _enforce_production_policy(prod(rate_limit_per_minute=0))


def test_startup_gate_accepts_a_clean_configuration():
    _enforce_production_policy(prod())


def test_startup_gate_logs_leftovers(caplog):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _enforce_production_policy(prod(demo_data=True, ai_provider="mock"))
    assert "production leftover" in caplog.text
    assert "DEMO_DATA" in caplog.text


def test_health_reports_the_flags_a_release_needs_to_check(client):
    # conftest runs with APP_ENV=test and demo seed on, so docs stay open here;
    # tools/build_release.py asserts the production values on a real artifact
    for path in ("/health", "/api/health"):
        body = client.get(path).json()
        assert body["status"] == "ok"
        assert isinstance(body["demo_data"], bool)
        assert isinstance(body["debug"], bool)
        assert isinstance(body["docs"], bool)
