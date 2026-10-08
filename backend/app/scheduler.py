import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings, get_settings

LOGGER = logging.getLogger("get-job.scheduler")
TERMINAL_RUN_STATUSES = {"succeeded", "partial", "failed"}
AUTOMATIC_SOURCES = (
    "demoday",
    "groupby",
    "wanted",
    "remember",
    "jumpit",
    "rallit",
    "jobplanet",
    "greenhouse",
    "lever",
    "ashby",
    "greeting",
    "ninehire",
)


def next_scheduled_run(now: datetime, settings: Settings) -> datetime:
    timezone = ZoneInfo(settings.daily_digest_timezone)
    local_now = now.astimezone(timezone)
    candidates = []
    for value in settings.daily_digest_times:
        hour, minute = (int(part) for part in value.split(":"))
        target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target > local_now:
            candidates.append(target)
    if candidates:
        return min(candidates)
    first_hour, first_minute = (int(part) for part in settings.daily_digest_times[0].split(":"))
    return (local_now + timedelta(days=1)).replace(
        hour=first_hour,
        minute=first_minute,
        second=0,
        microsecond=0,
    )


def seconds_until_next_run(now: datetime, settings: Settings) -> float:
    local_now = now.astimezone(ZoneInfo(settings.daily_digest_timezone))
    target = next_scheduled_run(now, settings)
    return max(1.0, (target - local_now).total_seconds())


async def _wait_for_runs(
    client: httpx.AsyncClient,
    run_ids: set[int],
    timeout_seconds: float = 12 * 60 * 60,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while run_ids:
        if loop.time() >= deadline:
            raise TimeoutError("daily crawl did not finish within the scheduler timeout")
        response = await client.get("/api/crawl/runs", params={"limit": 200})
        response.raise_for_status()
        statuses = {int(run["id"]): str(run["status"]) for run in response.json()}
        run_ids = {
            run_id for run_id in run_ids if statuses.get(run_id) not in TERMINAL_RUN_STATUSES
        }
        if run_ids:
            await asyncio.sleep(10)


async def run_daily_cycle(settings: Settings) -> None:
    LOGGER.info("Starting automatic collection: %s", ", ".join(AUTOMATIC_SOURCES))
    async with httpx.AsyncClient(
        base_url=settings.daily_scheduler_api_url,
        timeout=httpx.Timeout(30, read=20 * 60),
    ) as client:
        # The API recovers orphaned rows here before checking for active collection.
        # Otherwise an old interrupted batch can return 409 and prevent a fresh crawl.
        recovery_response = await client.get("/api/crawl/runs", params={"limit": 200})
        recovery_response.raise_for_status()
        response = await client.post(
            "/api/crawl/all",
            json={"urls": [], "max_jobs": settings.daily_crawl_max_jobs, "headless": True},
        )
        if response.status_code == 409:
            runs_response = await client.get("/api/crawl/runs", params={"limit": 200})
            runs_response.raise_for_status()
            run_ids = {int(run["id"]) for run in runs_response.json() if run["status"] == "running"}
        else:
            response.raise_for_status()
            run_ids = {int(run["id"]) for run in response.json()}

        await _wait_for_runs(client, run_ids)
        deduplication_response = await client.post("/api/jobs/deduplicate")
        deduplication_response.raise_for_status()
        program_response = await client.post("/api/ecosystem/crawl")
        program_response.raise_for_status()
        company_response = await client.post("/api/companies/enrich")
        company_response.raise_for_status()
        recommendation_response = await client.post(
            "/api/daily-recommendations/generate",
            json={"notify_slack": settings.slack_notify_enabled},
        )
        recommendation_response.raise_for_status()


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not settings.daily_digest_enabled:
        LOGGER.info("Daily collection is disabled; scheduler is standing by")
        while True:
            await asyncio.sleep(3600)

    while True:
        now = datetime.now(ZoneInfo("UTC"))
        next_run = next_scheduled_run(now, settings)
        delay = seconds_until_next_run(now, settings)
        LOGGER.info(
            "Next automatic collection: %s (%s, in %.0f seconds)",
            next_run.isoformat(),
            settings.daily_digest_timezone,
            delay,
        )
        await asyncio.sleep(delay)
        try:
            await run_daily_cycle(settings)
            LOGGER.info("Daily collection and recommendation generation completed")
        except Exception as exc:
            LOGGER.error("Daily cycle failed (%s)", type(exc).__name__)


if __name__ == "__main__":
    asyncio.run(main())
