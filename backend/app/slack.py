from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from app.config import Settings


@dataclass(frozen=True)
class SlackJob:
    rank: int
    company: str
    title: str
    source: str
    url: str
    tech_stack: list[str]
    fit_score: float
    application_value_score: float


def _job_blocks(recommendation_date: date, jobs: list[SlackJob]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"오늘의 추천 공고 · {recommendation_date.isoformat()}",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"활성 공고 중 적합도·지원가치를 함께 반영한 상위 {len(jobs)}개입니다.",
                }
            ],
        },
    ]
    for job in jobs[:20]:
        technology = ", ".join(job.tech_stack[:6]) or "기술 스택 미기재"
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{job.rank}. <{job.url}|{job.title}>*\n"
                        f"{job.company} · {job.source}\n"
                        f"적합 {job.fit_score:.1f} · 지원가치 "
                        f"{job.application_value_score:.1f} · {technology}"
                    ),
                },
            }
        )
    return blocks


async def send_daily_recommendations(
    settings: Settings,
    recommendation_date: date,
    jobs: list[SlackJob],
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    if not settings.slack_notify_enabled:
        return "disabled"
    if not jobs:
        return "empty"

    blocks = _job_blocks(recommendation_date, jobs)
    payload: dict[str, Any] = {
        "text": f"오늘의 추천 공고 {len(jobs)}개",
        "blocks": blocks,
    }
    headers: dict[str, str] = {}
    webhook = settings.slack_webhook_url
    if webhook and webhook.get_secret_value():
        url = webhook.get_secret_value()
    else:
        token = settings.slack_bot_token
        if token is None or settings.slack_channel_id is None:
            raise RuntimeError("Slack notification credentials are not configured")
        url = "https://slack.com/api/chat.postMessage"
        headers["Authorization"] = f"Bearer {token.get_secret_value()}"
        payload["channel"] = settings.slack_channel_id

    async with httpx.AsyncClient(timeout=15, transport=transport) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        if url == "https://slack.com/api/chat.postMessage":
            result = response.json()
            if not result.get("ok"):
                error = result.get("error", "unknown")
                raise RuntimeError(f"Slack API rejected the message: {error}")
    return "sent"
