"""Application configuration, loaded from environment / .env.

All settings are environment-driven so no secret is ever hard-coded. Field
names map to upper-case env vars case-insensitively (e.g. ``app_secret_key``
← ``APP_SECRET_KEY``).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_env: str = "development"
    app_secret_key: str = "dev-insecure-change-me"
    app_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    auto_create_tables: bool = True

    # Admin bootstrap (single user)
    admin_username: str = "admin"
    admin_password: str | None = None
    admin_totp_enabled: bool = False

    # Database
    database_url: str = "sqlite+pysqlite:///./lifeos.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Session / security
    session_ttl_seconds: int = 86400
    session_cookie_name: str = "lifeos_session"
    session_cookie_secure: bool = False
    login_rate_limit_per_minute: int = 5

    # Display
    display_timezone: str = "UTC"

    # Weather (Open-Meteo — free, no API key). Defaults to Tashkent.
    weather_city: str = "Toshkent"
    weather_latitude: float = 41.3111
    weather_longitude: float = 69.2797

    # GitHub monitoring (read-only)
    github_token: str | None = None
    github_api_base: str = "https://api.github.com"
    github_poll_interval_seconds: int = 120
    # Optional: your own GitHub login, to distinguish "my" activity in analytics.
    github_owner_login: str | None = None
    enable_scheduler: bool = True

    # Telegram notifications (to YOU only — never to contacts)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # AI provider (Claude). Two ways to connect:
    #  1) ANTHROPIC_API_KEY  -> Claude API (official, pay-as-you-go). Recommended.
    #  2) Subscription via Claude Agent SDK (CLAUDE_CODE_OAUTH_TOKEN or a local
    #     `claude` login). See README for the policy caveat.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    # Subscription path (opt-in):
    use_claude_subscription: bool = False
    claude_code_oauth_token: str | None = None
    claude_agent_model: str = "sonnet"
    # Reasoning effort for the CLI provider: low | medium | high | xhigh | max.
    # medium is a good balance for a chat/planner and uses less of your Pro limit.
    claude_effort: str = "medium"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
