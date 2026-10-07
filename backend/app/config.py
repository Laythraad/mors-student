"""Application configuration.

Every tunable lives here so nothing else in the codebase reads ``os.environ``
directly, and so model names / providers can be swapped without touching a
single feature module.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent

# shipped as-is these two sign every token with a publicly known key
DEV_SECRET_KEYS = frozenset({"", "dev-only-change-me", "change-me-before-production"})
# above this a per-minute bucket is a development/test allowance, not a production one
TEST_RATE_LIMIT = 300


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------- app
    app_name: str = "Mors.ai"
    app_env: str = "development"  # development | test | production
    debug: bool = False
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ------------------------------------------------------------- storage
    database_url: str = f"sqlite:///{BACKEND_DIR / 'mors.db'}"
    upload_dir: Path = BACKEND_DIR / "uploads"
    max_upload_mb: int = 25
    allowed_upload_types: str = "pdf,png,jpg,jpeg,webp,txt,md"

    # ------------------------------------------------------------ security
    secret_key: str = "dev-only-change-me"
    access_token_ttl_minutes: int = 60 * 12
    refresh_token_ttl_days: int = 30
    pbkdf2_iterations: int = 260_000
    rate_limit_per_minute: int = 120
    ai_rate_limit_per_minute: int = 30

    # ----------------------------------------------------------------- ai
    ai_provider: str = "mock"  # gemini | mock (displayed in health/admin)
    ai_providers: str = "gemini"  # comma-ordered fallback chain, e.g. gemini,groq,openrouter,ollama
    ai_model: str = "gemini-flash-latest"
    ai_fast_model: str = "gemini-flash-latest"
    ai_reasoning_model: str = "gemini-flash-latest"
    ai_vision_model: str = "gemini-flash-latest"
    gemini_api_key: str = ""
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-4-31b-it:free"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_num_ctx: int = 8192
    ai_daily_token_budget: int = 400_000
    ai_cache_ttl_seconds: int = 600
    ai_timeout_seconds: int = 45
    ai_max_history_messages: int = 12

    # -------------------------------------------------------------- voice
    # §15/§70/§71 — swappable providers; voice is never a hard requirement
    ai_tts_provider: str = "browser"  # browser | mock (later: openai | elevenlabs)
    ai_stt_provider: str = "browser"  # browser | mock (later: openai)
    ai_tts_voice: str = "system"
    ai_voice_max_chars: int = 800

    # ---------------------------------------------------------- scheduling
    # §121/§126/§132 — background jobs (auto-publish, housekeeping)
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 30

    # ---------------------------------------------------------------- rag
    rag_chunk_size: int = 900
    rag_chunk_overlap: int = 150
    rag_top_k: int = 6
    rag_min_score: float = 0.12

    # --------------------------------------------------------------- misc
    default_timezone: str = "Asia/Baghdad"
    default_language: str = "ar"
    # demo seed is opt-in: a build that forgets to say so must stay empty
    demo_data: bool = False

    # ---------------------------------------------------------- properties
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_types(self) -> set[str]:
        return {t.strip().lower() for t in self.allowed_upload_types.split(",") if t.strip()}

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def docs_enabled(self) -> bool:
        """OpenAPI is a dev affordance; production closes it (docs/DEPLOYMENT.md §6)."""
        return not (self.is_production and not self.debug)

    # ----------------------------------------------------- production gates
    def production_blockers(self) -> list[str]:
        """Configuration that must never reach a production process."""
        if not self.is_production:
            return []
        problems: list[str] = []
        if self.secret_key.strip() in DEV_SECRET_KEYS:
            problems.append("SECRET_KEY is still the development default")
        if self.rate_limit_per_minute <= 0:
            problems.append("RATE_LIMIT_PER_MINUTE=0 switches rate limiting off")
        if self.ai_rate_limit_per_minute <= 0:
            problems.append("AI_RATE_LIMIT_PER_MINUTE=0 switches AI rate limiting off")
        return problems

    def production_warnings(self) -> list[str]:
        """Developer leftovers: allowed to boot, loud, and never silent."""
        if not self.is_production:
            return []
        warnings: list[str] = []
        if self.demo_data:
            warnings.append("DEMO_DATA=true would seed the demo curriculum and demo@mors.ai")
        if self.debug:
            warnings.append("DEBUG=true")
        if self.ai_provider == "mock":
            warnings.append("AI_PROVIDER=mock — answers are canned text, not a real model")
        if self.rate_limit_per_minute > TEST_RATE_LIMIT:
            warnings.append(
                f"RATE_LIMIT_PER_MINUTE={self.rate_limit_per_minute} is a development allowance"
            )
        if "*" in self.cors_origins:
            warnings.append("CORS_ORIGINS contains *")
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
