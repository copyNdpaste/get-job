import asyncio
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx

from app.crawler.domain import CollectedJob
from app.crawler.normalization import normalize_text
from app.crawler.relevance import assess_relevance, extract_tech_stack

ProgressCallback = Callable[[int, int, int], None]

SARAMIN_API_URL = "https://oapi.saramin.co.kr/job-search"
SARAMIN_SEARCH_TERMS = (
    "Python",
    "Node.js",
    "TypeScript",
    "Golang",
    "Backend Engineer",
    "Product Engineer",
    "백엔드",
    "프로덕트 엔지니어",
)


def _nested_name(value: object) -> str:
    if isinstance(value, dict):
        return normalize_text(str(value.get("name") or ""))
    return normalize_text(str(value or ""))


def _timestamp(value: object) -> datetime | None:
    if value in {None, ""}:
        return None
    try:
        return datetime.fromtimestamp(int(str(value)), tz=UTC)
    except (OSError, TypeError, ValueError):
        return None


def validate_saramin_job_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or parts.hostname != "www.saramin.co.kr"
        or parts.username
        or parts.password
        or parts.port not in {None, 443, 80}
        or parts.path != "/zf_user/jobs/relay/view"
    ):
        raise ValueError("사람인 API 공고 URL은 공식 상세 경로만 사용할 수 있습니다")
    rec_idx = parse_qs(parts.query).get("rec_idx", [])
    if len(rec_idx) != 1 or not rec_idx[0].isdigit():
        raise ValueError("사람인 API 공고 URL에 유효한 공고 번호가 없습니다")
    return urlunsplit(("https", "www.saramin.co.kr", parts.path, parts.query, ""))


def parse_saramin_job(payload: dict[str, Any]) -> CollectedJob:
    external_id = normalize_text(str(payload.get("id") or ""))
    company = payload.get("company")
    company_detail = company.get("detail") if isinstance(company, dict) else None
    company_name = _nested_name(company_detail or company)
    position = payload.get("position")
    if not isinstance(position, dict):
        raise ValueError("사람인 API 응답에 포지션 정보가 없습니다")
    title = normalize_text(str(position.get("title") or ""))
    url = validate_saramin_job_url(str(payload.get("url") or ""))
    if not external_id or not company_name or not title:
        raise ValueError("사람인 API 응답에 공고 번호, 회사명 또는 제목이 없습니다")

    keyword = normalize_text(str(payload.get("keyword") or ""))
    job_code = _nested_name(position.get("job-code"))
    job_mid_code = _nested_name(position.get("job-mid-code"))
    industry = _nested_name(position.get("industry"))
    description_text = normalize_text(
        " ".join(part for part in (title, job_mid_code, job_code, industry, keyword) if part)
    )
    close_type = position.get("close-type") or payload.get("close-type")
    close_code = str(close_type.get("code") or "") if isinstance(close_type, dict) else ""
    deadline = _timestamp(payload.get("expiration-timestamp")) if close_code == "1" else None

    experience = _nested_name(position.get("experience-level")) or None
    employment_type = _nested_name(position.get("job-type")) or None
    location = _nested_name(position.get("location")) or None
    salary = _nested_name(payload.get("salary")) or None
    public_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return CollectedJob(
        source_name="saramin",
        external_job_id=external_id,
        company_name=company_name,
        title=title,
        url=url,
        description_raw=public_payload,
        description_text=description_text,
        tech_stack=extract_tech_stack(description_text),
        experience_text=experience,
        location=location,
        employment_type=employment_type,
        salary_text=salary,
        posted_at=_timestamp(payload.get("posting-timestamp")),
        deadline_at=deadline,
    )


def _payload_jobs(payload: object) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), dict):
        raise ValueError("사람인 공식 API가 예상하지 못한 응답을 반환했습니다")
    jobs = payload["jobs"]
    rows = jobs.get("job", [])
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise ValueError("사람인 공식 API 공고 목록 형식이 올바르지 않습니다")
    return [row for row in rows if isinstance(row, dict)], int(jobs.get("total") or 0)


async def collect_saramin_api(
    access_key: str,
    *,
    max_jobs: int,
    delay_min_seconds: float,
    user_agent: str,
    on_progress: ProgressCallback | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[CollectedJob]:
    """Collect only metadata returned by Saramin's approved official API."""
    if not access_key.strip():
        raise ValueError("SARAMIN_API_KEY가 설정되지 않았습니다")

    results: list[CollectedJob] = []
    seen_ids: set[str] = set()
    visited = 0
    failed = 0
    page_size = 110
    pages_per_term = max(1, min(5, math.ceil(max_jobs / page_size)))
    headers = {"Accept": "application/json", "User-Agent": user_agent}
    async with httpx.AsyncClient(
        headers=headers,
        timeout=30,
        follow_redirects=False,
        transport=transport,
    ) as client:
        for term in SARAMIN_SEARCH_TERMS:
            for page in range(pages_per_term):
                try:
                    response = await client.get(
                        SARAMIN_API_URL,
                        params={
                            "access-key": access_key,
                            "keywords": term,
                            "sr": "directhire",
                            "fields": "posting-date expiration-date keyword-code",
                            "sort": "ud",
                            "start": page,
                            "count": page_size,
                        },
                    )
                    if response.status_code != 200:
                        raise RuntimeError("사람인 공식 API 호출이 실패했습니다")
                    payload = response.json()
                    if isinstance(payload, dict) and "code" in payload:
                        raise RuntimeError("사람인 공식 API가 키 또는 요청을 거부했습니다")
                    rows, total = _payload_jobs(payload)
                except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError):
                    raise RuntimeError("사람인 공식 API 응답을 처리하지 못했습니다") from None

                for row in rows:
                    visited += 1
                    external_id = normalize_text(str(row.get("id") or ""))
                    if (
                        not external_id
                        or external_id in seen_ids
                        or int(row.get("active") or 0) != 1
                    ):
                        continue
                    seen_ids.add(external_id)
                    try:
                        job = parse_saramin_job(row)
                        if assess_relevance(
                            job.title,
                            job.description_text,
                            job.experience_text,
                            job.employment_type,
                        ).included:
                            results.append(job)
                    except (TypeError, ValueError):
                        failed += 1
                    if on_progress:
                        on_progress(visited, len(seen_ids), failed)
                    if len(results) >= max_jobs:
                        return results

                if not rows or (page + 1) * page_size >= total:
                    break
                if delay_min_seconds > 0:
                    await asyncio.sleep(delay_min_seconds)
            if delay_min_seconds > 0:
                await asyncio.sleep(delay_min_seconds)
    return results
