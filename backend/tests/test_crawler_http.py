import asyncio
import hashlib

import httpx
import pytest

from app.crawler.http import CachedHttpClient, RobotsDeniedError


def test_cached_page_is_not_requested_twice(tmp_path) -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text="<html>job</html>")

    async def exercise() -> tuple[str, str]:
        async with CachedHttpClient(
            cache_dir=tmp_path,
            user_agent="test-agent",
            delay_min_seconds=0,
            delay_max_seconds=0,
            transport=httpx.MockTransport(handler),
        ) as client:
            first = await client.get("https://example.com/jobs/1")
            second = await client.get("https://example.com/jobs/1")
            return first, second

    first, second = asyncio.run(exercise())

    assert first == second
    assert calls.count("https://example.com/jobs/1") == 1


def test_robots_disallow_is_respected(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /jobs")
        return httpx.Response(200, text="must not be fetched")

    async def exercise() -> None:
        async with CachedHttpClient(
            cache_dir=tmp_path,
            user_agent="test-agent",
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.get("https://example.com/jobs/1")

    with pytest.raises(RobotsDeniedError):
        asyncio.run(exercise())


def test_force_refresh_bypasses_a_fresh_cached_page(tmp_path) -> None:
    page_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal page_calls
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        page_calls += 1
        return httpx.Response(200, text=f"version {page_calls}")

    async def exercise() -> tuple[str, str]:
        async with CachedHttpClient(
            cache_dir=tmp_path,
            user_agent="test-agent",
            delay_min_seconds=0,
            delay_max_seconds=0,
            transport=httpx.MockTransport(handler),
        ) as client:
            first = await client.get("https://example.com/sitemap.xml")
            refreshed = await client.get(
                "https://example.com/sitemap.xml", force_refresh=True
            )
            return first, refreshed

    assert asyncio.run(exercise()) == ("version 1", "version 2")
    assert page_calls == 2


def test_empty_robots_file_allows_public_page(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="" if request.url.path == "/robots.txt" else "ok")

    async def exercise() -> str:
        async with CachedHttpClient(
            cache_dir=tmp_path,
            user_agent="test-agent",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.get("https://example.com/jobs/1")

    assert asyncio.run(exercise()) == "ok"


def test_redirect_to_another_host_is_rejected(tmp_path) -> None:
    requested_hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(
            302,
            headers={"Location": "https://127.0.0.1/internal"},
        )

    async def exercise() -> None:
        async with CachedHttpClient(
            cache_dir=tmp_path,
            user_agent="test-agent",
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.get(
                "https://example.com/jobs/1", expected_host="example.com"
            )

    with pytest.raises(ValueError, match="redirected outside allowed host"):
        asyncio.run(exercise())
    assert "127.0.0.1" not in requested_hosts


def test_force_refresh_uses_stale_cache_when_server_fails(tmp_path) -> None:
    url = "https://example.com/jobs/1"
    cache_path = tmp_path / f"{hashlib.sha256(url.encode()).hexdigest()}.html"
    cache_path.write_text("stale public job page", encoding="utf-8")

    async def exercise() -> str:
        async with CachedHttpClient(
            cache_dir=tmp_path,
            user_agent="test-agent",
            delay_min_seconds=0,
            delay_max_seconds=0,
            transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
        ) as client:
            return await client.get(
                url,
                check_robots=False,
                force_refresh=True,
                expected_host="example.com",
            )

    assert asyncio.run(exercise()) == "stale public job page"
