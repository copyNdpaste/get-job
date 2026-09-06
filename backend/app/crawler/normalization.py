import hashlib
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_QUERY_PREFIXES = ("utm_", "fbclid", "gclid", "ref", "source")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_name(value: str) -> str:
    normalized = normalize_text(value).casefold()
    return re.sub(r"[^0-9a-z가-힣]+", "", normalized)


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith(TRACKING_QUERY_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), path, urlencode(query), "")
    )


def content_hash(structured_content: dict[str, object]) -> str:
    stable = json.dumps(structured_content, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(stable.encode()).hexdigest()


def stable_external_id(source_name: str, url: str, title: str, company_name: str) -> str:
    for pattern in (
        r"/(?:wd|position|positions|jobs|recruits)/(\d+)",
        r"[?&](?:id|jobId)=(\d+)",
    ):
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raw = "|".join(
        [source_name, canonicalize_url(url), normalize_name(company_name), normalize_name(title)]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
