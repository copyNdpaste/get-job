import asyncio
import json
from datetime import date

import httpx

from app.config import Settings
from app.slack import SlackJob, send_daily_recommendations


def test_slack_payload_contains_only_public_job_summary() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["host"] = request.url.host
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, text="ok")

    settings = Settings(
        ai_enabled=False,
        slack_notify_enabled=True,
        slack_webhook_url="https://hooks.slack.com" + "/services/T000/B000/SECRET",
    )
    result = asyncio.run(
        send_daily_recommendations(
            settings,
            date(2026, 7, 14),
            [
                SlackJob(
                    rank=1,
                    company="공개 회사",
                    title="Backend Engineer",
                    source="jumpit",
                    url="https://example.com/job/1",
                    tech_stack=["Python", "Django"],
                    fit_score=91,
                    application_value_score=88,
                )
            ],
            transport=httpx.MockTransport(handler),
        )
    )

    serialized = json.dumps(captured["payload"], ensure_ascii=False)
    assert result == "sent"
    assert captured["host"] == "hooks.slack.com"
    assert "Backend Engineer" in serialized
    assert "적합 91" in serialized
    assert "resume" not in serialized.casefold()
    assert "candidate" not in serialized.casefold()
    assert "profile_evidence" not in serialized


def test_disabled_slack_never_makes_a_request() -> None:
    called = False

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    result = asyncio.run(
        send_daily_recommendations(
            Settings(ai_enabled=False, slack_notify_enabled=False),
            date(2026, 7, 14),
            [],
            transport=httpx.MockTransport(handler),
        )
    )

    assert result == "disabled"
    assert called is False
