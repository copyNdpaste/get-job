import asyncio

from app.api import crawl
from app.config import Settings


def test_collections_respect_the_configured_concurrency_limit(monkeypatch) -> None:
    active = 0
    peak = 0

    async def fake_collection(*_args, **_kwargs) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1

    monkeypatch.setattr(crawl, "_run_collection", fake_collection)
    monkeypatch.setattr(crawl, "_collection_slots", None)
    monkeypatch.setattr(crawl, "_collection_slots_loop", None)
    monkeypatch.setattr(crawl, "_collection_slots_limit", None)
    settings = Settings(ai_enabled=False, crawler_max_concurrency=2)
    payload = crawl.CrawlRequest()

    async def run_collections() -> None:
        await asyncio.gather(
            *(
                crawl._run_collection_limited(index, "source", payload, settings)
                for index in range(6)
            )
        )

    asyncio.run(run_collections())

    assert peak == 2
