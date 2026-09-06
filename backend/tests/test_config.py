import pytest

from app.config import Settings


def test_comma_separated_cors_origins_are_parsed() -> None:
    settings = Settings(
        backend_cors_origins="http://localhost:5173, https://example.com"  # type: ignore[arg-type]
    )

    assert settings.backend_cors_origins == [
        "http://localhost:5173",
        "https://example.com",
    ]


def test_local_ai_is_the_only_enabled_default() -> None:
    settings = Settings()

    assert settings.ai_enabled is True
    assert settings.ai_provider == "openai-compatible"
    assert settings.ai_base_url == "http://host.docker.internal:1234"
    assert settings.ai_model == "auto"
    assert settings.ai_allow_remote is False


def test_crawler_concurrency_is_bounded_for_local_docker() -> None:
    assert Settings.model_fields["crawler_max_concurrency"].default == 2

    with pytest.raises(ValueError):
        Settings(ai_enabled=False, crawler_max_concurrency=0)

    with pytest.raises(ValueError):
        Settings(ai_enabled=False, crawler_max_concurrency=5)


def test_remote_ai_is_blocked_without_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="Remote AI endpoints are blocked"):
        Settings(ai_provider="openai-compatible", ai_base_url="https://api.example.com/v1")


def test_remote_ai_can_only_be_enabled_explicitly() -> None:
    settings = Settings(
        ai_provider="openai-compatible",
        ai_base_url="https://api.example.com/v1",
        ai_allow_remote=True,
    )

    assert settings.ai_allow_remote is True


def test_codex_gpt_requires_explicit_remote_consent() -> None:
    with pytest.raises(ValueError, match="Codex GPT uses the user's ChatGPT account"):
        Settings(
            ai_provider="codex",
            ai_base_url="http://codex-bridge:48765",
            ai_model="gpt-5.6-sol",
        )


def test_codex_gpt_can_be_enabled_after_explicit_consent() -> None:
    settings = Settings(
        ai_provider="codex",
        ai_base_url="http://codex-bridge:48765",
        ai_model="gpt-5.6-sol",
        ai_allow_remote=True,
    )

    assert settings.ai_provider == "codex"
    assert settings.ai_allow_remote is True


def test_comma_separated_cors_origins_are_parsed_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "http://localhost:5173,https://app.example.com")

    assert Settings().backend_cors_origins == [
        "http://localhost:5173",
        "https://app.example.com",
    ]


def test_slack_notifications_are_disabled_by_default() -> None:
    settings = Settings(ai_enabled=False)

    assert settings.slack_notify_enabled is False
    assert settings.slack_webhook_url is None


def test_slack_notifications_require_explicit_local_credentials() -> None:
    with pytest.raises(ValueError, match="Slack notifications require"):
        Settings(ai_enabled=False, slack_notify_enabled=True)


def test_slack_webhook_is_restricted_to_slack_host() -> None:
    with pytest.raises(ValueError, match="hooks.slack.com"):
        Settings(
            ai_enabled=False,
            slack_notify_enabled=True,
            slack_webhook_url="https://example.com/services/T/B/C",
        )


def test_slack_bot_requires_channel_and_accepts_fixed_channel_id() -> None:
    settings = Settings(
        ai_enabled=False,
        slack_notify_enabled=True,
        slack_bot_token="local-secret",
        slack_channel_id="C0123456789",
    )

    assert settings.slack_notify_enabled is True
    assert settings.slack_channel_id == "C0123456789"


def test_daily_scheduler_requires_a_valid_timezone() -> None:
    with pytest.raises(ValueError, match="valid IANA timezone"):
        Settings(ai_enabled=False, daily_digest_timezone="Invalid/Local-Time")


@pytest.mark.parametrize("value", ["", "11", "24:00", "16:60"])
def test_daily_scheduler_rejects_invalid_run_times(value: str) -> None:
    with pytest.raises(ValueError, match="DAILY_DIGEST_TIMES"):
        Settings(ai_enabled=False, daily_digest_times=value)  # type: ignore[arg-type]


def test_dart_key_is_optional_but_must_match_the_issued_format() -> None:
    assert Settings(ai_enabled=False).dart_api_key is None
    with pytest.raises(ValueError, match="DART_API_KEY"):
        Settings(ai_enabled=False, dart_api_key="short-key")
    settings = Settings(ai_enabled=False, dart_api_key="a" * 40)
    assert settings.dart_api_key is not None


def test_saramin_official_api_key_is_optional_and_kept_secret() -> None:
    assert Settings(ai_enabled=False).saramin_api_key is None
    settings = Settings(ai_enabled=False, saramin_api_key=" issued-locally ")

    assert settings.saramin_api_key is not None
    assert settings.saramin_api_key.get_secret_value() == "issued-locally"
    assert "issued-locally" not in repr(settings)
