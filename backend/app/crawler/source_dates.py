"""Parse explicit source timestamps; never infer publication from observation."""

import json
import re
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

KOREA = ZoneInfo("Asia/Seoul")


def korean_source_datetime(value: object, *, end_of_day: bool = False) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if len(value.strip()) == 10 and end_of_day:
            parsed = datetime.combine(parsed.date(), time.max)
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=KOREA)).astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def jumpit_position(soup: BeautifulSoup, url: str) -> dict:
    match = re.search(r"/position/(\d+)(?:[/?#]|$)", url)
    if not match:
        return {}
    expected_id = match.group(1)
    budget = 20_000

    def find(value, depth=0):
        nonlocal budget
        budget -= 1
        if depth > 24 or budget <= 0:
            return None
        if isinstance(value, dict):
            if str(value.get("id")) == expected_id and (
                "publishedAt" in value or "closedAt" in value
            ):
                return value
            children = value.values()
        elif isinstance(value, list):
            children = value
        elif isinstance(value, str) and value.startswith(("{", "[")):
            try:
                return find(json.loads(value), depth + 1)
            except (ValueError, RecursionError):
                return None
        else:
            return None
        for child in children:
            found = find(child, depth + 1)
            if found is not None:
                return found
        return None

    decoder = json.JSONDecoder()
    for script in soup.find_all("script"):
        text = script.string or ""
        if script.get("id") == "__NEXT_DATA__":
            try:
                found = find(json.loads(text))
                if found is not None:
                    return found
            except (ValueError, RecursionError):
                pass
        for push in re.finditer(r"self\.__next_f\.push\(", text):
            try:
                packet, _ = decoder.raw_decode(text[push.end() :])
            except (ValueError, RecursionError):
                continue
            if not isinstance(packet, list) or len(packet) < 2 or not isinstance(packet[1], str):
                continue
            for line in packet[1].splitlines():
                payload = line.partition(":")[2]
                if not payload.startswith(("[", "{")):
                    continue
                try:
                    found = find(json.loads(payload))
                    if found is not None:
                        return found
                except (ValueError, RecursionError):
                    continue
    return {}


def jobposting_dates(soup: BeautifulSoup, url: str) -> tuple[datetime | None, datetime | None]:
    """Read source JobPosting JSON-LD, excluding other jobs linked on the page."""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or "")
        except (ValueError, RecursionError):
            continue
        nodes = payload if isinstance(payload, list) else [payload]
        for node in list(nodes):
            if isinstance(node, dict) and isinstance(node.get("@graph"), list):
                nodes.extend(node["@graph"])
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = node.get("@type")
            if kind != "JobPosting" and not (isinstance(kind, list) and "JobPosting" in kind):
                continue
            source_url = node.get("url")
            if isinstance(source_url, str) and source_url.rstrip("/") != url.rstrip("/"):
                continue
            return (
                korean_source_datetime(node.get("datePosted")),
                korean_source_datetime(node.get("validThrough"), end_of_day=True),
            )
    return None, None
