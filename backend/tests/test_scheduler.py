from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.scheduler import AUTOMATIC_SOURCES, next_scheduled_run, seconds_until_next_run


def test_scheduler_targets_next_configured_local_time() -> None:
    settings = Settings(
        ai_enabled=False,
        daily_digest_times=["11:00", "16:00"],
        daily_digest_timezone="Asia/Seoul",
    )

    before_first = datetime(2026, 7, 14, 10, 30, tzinfo=ZoneInfo("Asia/Seoul"))
    between_runs = datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    after_last = datetime(2026, 7, 14, 17, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    assert seconds_until_next_run(before_first, settings) == 30 * 60
    assert seconds_until_next_run(between_runs, settings) == 4 * 60 * 60
    assert seconds_until_next_run(after_last, settings) == 18 * 60 * 60
    assert next_scheduled_run(between_runs, settings).hour == 16


def test_scheduler_defaults_to_the_requested_three_daily_runs() -> None:
    # A local ignored .env may intentionally override these values during development.
    assert Settings.model_fields["daily_digest_times"].default == ["10:00", "13:00", "17:00"]


def test_scheduler_accepts_comma_separated_times_and_sorts_them() -> None:
    settings = Settings(ai_enabled=False, daily_digest_times="16:00, 11:00")  # type: ignore[arg-type]

    assert settings.daily_digest_times == ["11:00", "16:00"]


def test_scheduler_includes_public_direct_ats_sources() -> None:
    assert {"greenhouse", "lever", "ashby", "greeting", "ninehire"}.issubset(
        AUTOMATIC_SOURCES
    )
