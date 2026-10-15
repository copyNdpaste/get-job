import re
from functools import lru_cache
from ipaddress import ip_address
from typing import Annotated
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "get-job"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://jobapp:local-development-only@localhost:5432/jobdb"
    backend_cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:41739",
        "http://127.0.0.1:41739",
    ]
    resume_directory: str = "/data/generated-resumes.local"
    ai_enabled: bool = True
    ai_provider: str = "openai-compatible"
    ai_base_url: str = "http://host.docker.internal:1234"
    ai_model: str = "auto"
    ai_api_key: SecretStr | None = None
    ai_allow_remote: bool = False
    ai_timeout_seconds: float = 120.0
    # Economy routing is separate from the interactive model picker.
    ai_analysis_fast_model: str = Field(default="auto", min_length=1, max_length=120)
    ai_analysis_review_model: str = Field(default="", max_length=120)
    ai_analysis_max_output_tokens: int = Field(default=1200, ge=256, le=4096)
    ai_analysis_prompt_bytes: int = Field(default=12000, ge=4000, le=24000)
    ai_analysis_daily_budget: int = Field(default=100000, ge=0, le=10_000_000)
    ai_analysis_daily_reviews: int = Field(default=5, ge=0, le=100)
    ai_analysis_batch_size: int = Field(default=10, ge=1, le=50)
    ai_analysis_batch_reviews: int = Field(default=2, ge=0, le=10)
    ai_analysis_min_fit: float = Field(default=60, ge=0, le=100)
    ai_analysis_after_crawl: bool = False
    ai_preference_scoring: bool = False
    ai_preferences_path: str = "/data/job-preferences.local.json"
    ai_preference_batch_size: int = Field(default=2, ge=1, le=5)
    ai_preference_poll_seconds: int = Field(default=30, ge=5, le=3600)
    crawler_respect_robots: bool = True
    crawler_cache_dir: str = ".cache/crawler"
    crawler_delay_min_seconds: float = 2.0
    crawler_delay_max_seconds: float = 5.0
    crawler_max_concurrency: int = Field(default=2, ge=1, le=4)
    crawler_user_agent: str = "get-job/0.1 (+local personal job search)"
    saramin_api_key: SecretStr | None = None
    direct_ats_board_path: str = "/data/ats-boards.local.json"
    company_enrichment_max_groupby: int = Field(default=25, ge=0, le=500)
    company_enrichment_max_dart: int = Field(default=50, ge=0, le=500)
    company_facts_refresh_days: int = Field(default=7, ge=1, le=90)
    dart_api_key: SecretStr | None = None
    dart_cache_dir: str = ".cache/dart"
    daily_digest_enabled: bool = True
    daily_digest_times: Annotated[list[str], NoDecode] = ["10:00", "13:00", "17:00"]
    daily_digest_timezone: str = "Asia/Seoul"
    daily_scheduler_api_url: str = "http://backend:8000"
    daily_crawl_max_jobs: int = Field(default=5000, ge=1, le=5000)
    daily_recommendation_prefer_established: bool = False
    daily_recommendation_limit: int = Field(default=10, ge=1, le=20)
    daily_recommendation_min_fit: float = Field(default=70, ge=0, le=100)
    daily_recommendation_min_value: float = Field(default=70, ge=0, le=100)
    daily_recommendation_cooldown_days: int = Field(default=14, ge=0, le=90)
    slack_notify_enabled: bool = False
    slack_webhook_url: SecretStr | None = None
    slack_bot_token: SecretStr | None = None
    slack_channel_id: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("ai_analysis_fast_model", "ai_analysis_review_model")
    @classmethod
    def normalize_analysis_model(cls, value: str, info) -> str:
        value = value.strip()
        if info.field_name == "ai_analysis_fast_model" and not value:
            raise ValueError("AI_ANALYSIS_FAST_MODEL must not be empty")
        if info.field_name == "ai_analysis_review_model" and value == "auto":
            raise ValueError("AI_ANALYSIS_REVIEW_MODEL must name a specific model or be empty")
        return value

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("daily_digest_times", mode="before")
    @classmethod
    def parse_daily_digest_times(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("daily_digest_times")
    @classmethod
    def validate_daily_digest_times(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("DAILY_DIGEST_TIMES must contain at least one HH:MM value")
        normalized: set[str] = set()
        for value in values:
            match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
            if match is None:
                raise ValueError("DAILY_DIGEST_TIMES must use comma-separated HH:MM values")
            hour, minute = (int(part) for part in match.groups())
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError("DAILY_DIGEST_TIMES contains an invalid local time")
            normalized.add(f"{hour:02d}:{minute:02d}")
        return sorted(normalized)

    @field_validator("slack_webhook_url")
    @classmethod
    def validate_slack_webhook(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value():
            return None
        parts = urlsplit(value.get_secret_value())
        if (
            parts.scheme != "https"
            or parts.hostname != "hooks.slack.com"
            or not parts.path.startswith("/services/")
            or len([part for part in parts.path.split("/") if part]) != 4
        ):
            raise ValueError("SLACK_WEBHOOK_URL must be an exact hooks.slack.com HTTPS webhook")
        return value

    @field_validator("dart_api_key")
    @classmethod
    def validate_dart_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        normalized = value.get_secret_value().strip()
        if not re.fullmatch(r"[A-Za-z0-9]{40}", normalized):
            raise ValueError("DART_API_KEY must be the 40-character key issued by OpenDART")
        return SecretStr(normalized)

    @field_validator("saramin_api_key")
    @classmethod
    def normalize_saramin_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        return SecretStr(value.get_secret_value().strip())

    @field_validator("slack_channel_id")
    @classmethod
    def validate_slack_channel(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{2,80}", normalized):
            raise ValueError("SLACK_CHANNEL_ID contains unsupported characters")
        return normalized

    @field_validator("daily_scheduler_api_url")
    @classmethod
    def validate_scheduler_api_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "http" or parts.hostname not in {"backend", "localhost", "127.0.0.1"}:
            raise ValueError("DAILY_SCHEDULER_API_URL must point to the local backend service")
        return value.rstrip("/")

    @field_validator("daily_digest_timezone")
    @classmethod
    def validate_daily_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("DAILY_DIGEST_TIMEZONE must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def enforce_local_ai_by_default(self) -> "Settings":
        providers = {"codex", "disabled", "ollama", "openai-compatible"}
        if self.ai_provider not in providers:
            raise ValueError(f"AI_PROVIDER must be one of: {', '.join(sorted(providers))}")
        if self.ai_enabled and self.ai_provider != "disabled":
            if self.ai_provider == "codex" and not self.ai_allow_remote:
                raise ValueError(
                    "Codex GPT uses the user's ChatGPT account and sends prompt data to OpenAI. "
                    "Set AI_ALLOW_REMOTE=true only after explicit user consent."
                )
            if not self.ai_allow_remote and not _is_local_ai_url(self.ai_base_url):
                raise ValueError(
                    "Remote AI endpoints are blocked by default. "
                    "Set AI_ALLOW_REMOTE=true only after explicitly accepting possible API charges."
                )
        webhook_configured = bool(
            self.slack_webhook_url and self.slack_webhook_url.get_secret_value()
        )
        bot_configured = bool(
            self.slack_bot_token
            and self.slack_bot_token.get_secret_value()
            and self.slack_channel_id
        )
        if self.slack_notify_enabled and not (webhook_configured or bot_configured):
            raise ValueError(
                "Slack notifications require SLACK_WEBHOOK_URL or both "
                "SLACK_BOT_TOKEN and SLACK_CHANNEL_ID"
            )
        return self

def _is_local_ai_url(value: str) -> bool:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    hostname = parts.hostname.casefold()
    if hostname in {
        "localhost",
        "host.docker.internal",
        "ollama",
        "lmstudio",
        "vllm",
        "codex-bridge",
    }:
        return True
    try:
        address = ip_address(hostname)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


@lru_cache
def get_settings() -> Settings:
    return Settings()
