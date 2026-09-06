import asyncio
import hashlib
import random
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx


class RobotsDeniedError(RuntimeError):
    pass


class CachedHttpClient:
    def __init__(
        self,
        *,
        cache_dir: str | Path,
        user_agent: str,
        delay_min_seconds: float = 2.0,
        delay_max_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep=asyncio.sleep,
        cache_ttl_seconds: int = 21_600,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent
        self.delay_min_seconds = delay_min_seconds
        self.delay_max_seconds = delay_max_seconds
        self.sleep = sleep
        self.cache_ttl_seconds = cache_ttl_seconds
        self.client = httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            follow_redirects=False,
            timeout=30,
            transport=transport,
        )
        self._robots: dict[str, RobotFileParser] = {}
        self._has_requested = False

    async def __aenter__(self) -> "CachedHttpClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()

    async def get(
        self,
        url: str,
        *,
        check_robots: bool = True,
        force_refresh: bool = False,
        expected_host: str | None = None,
    ) -> str:
        if expected_host:
            _assert_expected_host(url, expected_host)
        cache_path = self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.html"
        cache_is_fresh = (
            cache_path.exists()
            and time.time() - cache_path.stat().st_mtime <= self.cache_ttl_seconds
        )
        if cache_is_fresh and not force_refresh:
            return cache_path.read_text(encoding="utf-8")
        if check_robots and not await self._allowed(url):
            raise RobotsDeniedError(f"robots.txt denied collection: {url}")
        if self._has_requested:
            await self.sleep(random.uniform(self.delay_min_seconds, self.delay_max_seconds))
        try:
            response = await self._get_with_safe_redirects(url, expected_host)
            self._has_requested = True
            response.raise_for_status()
        except httpx.HTTPError:
            if cache_path.exists():
                return cache_path.read_text(encoding="utf-8")
            raise
        cache_path.write_text(response.text, encoding="utf-8")
        return response.text

    async def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robots_url = f"{origin}/robots.txt"
            parser = RobotFileParser(robots_url)
            try:
                response = await self._get_with_safe_redirects(
                    robots_url, parts.hostname or ""
                )
                response.raise_for_status()
            except httpx.HTTPError:
                return False
            lines = response.text.splitlines()
            if not any(line.strip() for line in lines):
                lines = ["User-agent: *", "Allow: /"]
            parser.parse(lines)
            self._robots[origin] = parser
        return self._robots[origin].can_fetch(self.user_agent, url)

    async def _get_with_safe_redirects(
        self, url: str, expected_host: str | None
    ) -> httpx.Response:
        current_url = url
        for _ in range(6):
            if expected_host:
                _assert_expected_host(current_url, expected_host)
            response = await self.client.get(current_url)
            if not response.is_redirect:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            current_url = urljoin(current_url, location)
            if expected_host:
                _assert_expected_host(current_url, expected_host)
        raise httpx.TooManyRedirects(
            "Exceeded maximum allowed redirects.", request=response.request
        )


def _assert_expected_host(url: str, expected_host: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != expected_host:
        raise ValueError(f"redirected outside allowed host: {expected_host}")
    if parts.username or parts.password or parts.port not in {None, 443}:
        raise ValueError(f"unsafe URL for allowed host: {expected_host}")
