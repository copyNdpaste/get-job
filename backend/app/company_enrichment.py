import asyncio
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.company_facts import groupby_company_facts, merge_company_facts
from app.config import Settings
from app.crawler.normalization import normalize_name
from app.models import Company, JobPosting, JobSource

GROUPBY_API_BASE = "https://api.groupby.kr"
GROUPBY_PUBLIC_ORIGIN = "https://groupby.kr"
DART_API_BASE = "https://opendart.fss.or.kr/api"
DART_SOURCE_URL = "https://dart.fss.or.kr/"


async def enrich_company_facts(session: Session, settings: Settings) -> dict[str, object]:
    groupby = await enrich_groupby_companies(session, settings)
    dart = await enrich_dart_companies(session, settings)
    session.commit()
    return {"groupby": groupby, "dart": dart}


async def enrich_groupby_companies(session: Session, settings: Settings) -> dict[str, object]:
    rows = session.execute(
        select(JobPosting.description_raw, Company)
        .join(Company, Company.id == JobPosting.company_id)
        .join(JobSource, JobSource.id == JobPosting.source_id)
        .where(JobSource.name == "groupby")
        .order_by(JobPosting.last_seen_at.desc())
    ).all()
    cutoff = datetime.now(UTC) - timedelta(days=settings.company_facts_refresh_days)
    detail_targets: dict[int, tuple[Company, int]] = {}
    seen_companies: set[int] = set()
    for raw, company in rows:
        if company.id in seen_companies:
            continue
        try:
            payload = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        startup = payload.get("startup")
        if not isinstance(startup, dict):
            continue
        startup_id = startup.get("id")
        if not isinstance(startup_id, int) or startup_id <= 0:
            continue
        seen_companies.add(company.id)
        needs_detail = (
            company.groupby_profile_updated_at is None
            or company.groupby_profile_updated_at < cutoff
        )
        merge_company_facts(company, groupby_company_facts(startup))
        if needs_detail and len(detail_targets) < settings.company_enrichment_max_groupby:
            detail_targets[company.id] = (company, startup_id)

    enriched = 0
    failed = 0
    if detail_targets:
        headers = {
            "Accept": "application/json",
            "Origin": GROUPBY_PUBLIC_ORIGIN,
            "Referer": f"{GROUPBY_PUBLIC_ORIGIN}/",
            "User-Agent": settings.crawler_user_agent,
        }
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=False,
            timeout=httpx.Timeout(30),
        ) as client:
            for index, (company, startup_id) in enumerate(detail_targets.values()):
                try:
                    response = await client.get(f"{GROUPBY_API_BASE}/startups/{startup_id}")
                    response.raise_for_status()
                    envelope = response.json()
                    data = envelope.get("data") if isinstance(envelope, dict) else None
                    profile = data.get("curr") if isinstance(data, dict) else None
                    if not isinstance(profile, dict):
                        raise ValueError("GroupBy company profile is missing")
                    merge_company_facts(
                        company,
                        groupby_company_facts(profile, startup_profile=profile),
                    )
                    company.groupby_profile_updated_at = datetime.now(UTC)
                    enriched += 1
                except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
                    failed += 1
                if index + 1 < len(detail_targets):
                    await asyncio.sleep(settings.crawler_delay_min_seconds)
    return {
        "available": True,
        "backfilled": len(seen_companies),
        "detailed": enriched,
        "failed": failed,
    }


async def enrich_dart_companies(session: Session, settings: Settings) -> dict[str, object]:
    if settings.dart_api_key is None:
        return {
            "available": False,
            "enriched": 0,
            "message": "DART_API_KEY가 없어 재무정보는 비공개·미확인으로 표시됩니다.",
        }
    api_key = settings.dart_api_key.get_secret_value()
    corp_index = await _load_dart_corp_index(api_key, Path(settings.dart_cache_dir))
    cutoff = datetime.now(UTC) - timedelta(days=settings.company_facts_refresh_days)
    companies = session.scalars(
        select(Company)
        .join(JobPosting, JobPosting.company_id == Company.id)
        .where(JobPosting.is_active.is_(True))
        .distinct()
        .order_by(Company.id)
    ).all()
    targets: list[tuple[Company, str]] = []
    for company in companies:
        if (
            company.financial_history
            and company.facts_updated_at
            and company.facts_updated_at >= cutoff
        ):
            continue
        corp_code = company.dart_corp_code or _match_dart_corp(company.name, corp_index)
        if corp_code:
            targets.append((company, corp_code))
        if len(targets) >= settings.company_enrichment_max_dart:
            break
    if not targets:
        return {"available": True, "matched": 0, "enriched": 0, "failed": 0}

    semaphore = asyncio.Semaphore(4)
    current_year = datetime.now(UTC).year
    async with httpx.AsyncClient(timeout=httpx.Timeout(30), follow_redirects=False) as client:

        async def fetch(corp_code: str) -> tuple[list[dict[str, object]], int | None, str | None]:
            async with semaphore:
                financials: list[dict[str, object]] = []
                employee_count: int | None = None
                employee_as_of: str | None = None
                for year in range(current_year - 1, current_year - 4, -1):
                    financial = await _fetch_dart_financial(client, api_key, corp_code, year)
                    if financial:
                        financials.append(financial)
                    if employee_count is None:
                        employee_count, employee_as_of = await _fetch_dart_employees(
                            client, api_key, corp_code, year
                        )
                return financials, employee_count, employee_as_of

        results = await asyncio.gather(
            *(fetch(corp_code) for _company, corp_code in targets), return_exceptions=True
        )

    enriched = 0
    failed = 0
    for (company, corp_code), result in zip(targets, results, strict=True):
        if isinstance(result, BaseException):
            failed += 1
            continue
        financials, employee_count, employee_as_of = result
        merge_company_facts(
            company,
            _dart_company_facts(
                corp_code,
                financials,
                employee_count=employee_count,
                employee_as_of=employee_as_of,
            ),
        )
        if financials or employee_count is not None:
            enriched += 1
    return {
        "available": True,
        "matched": len(targets),
        "enriched": enriched,
        "failed": failed,
    }


def _dart_company_facts(
    corp_code: str,
    financials: list[dict[str, object]],
    *,
    employee_count: int | None,
    employee_as_of: str | None,
):
    from app.crawler.domain import CollectedCompanyFacts

    return CollectedCompanyFacts(
        employee_count=employee_count,
        employee_count_source="OpenDART" if employee_count is not None else None,
        employee_count_as_of=employee_as_of,
        financial_history=financials,
        source_urls=[DART_SOURCE_URL],
        dart_corp_code=corp_code,
    )


async def _load_dart_corp_index(api_key: str, cache_dir: Path) -> dict[str, list[str]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "corp-codes.xml"
    cache_is_fresh = cache_path.exists() and (
        datetime.now().timestamp() - cache_path.stat().st_mtime < 7 * 24 * 60 * 60
    )
    if not cache_is_fresh:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60), follow_redirects=False) as client:
            response = await client.get(
                f"{DART_API_BASE}/corpCode.xml", params={"crtfc_key": api_key}
            )
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
                if not xml_names:
                    raise ValueError("OpenDART corp-code archive contains no XML")
                cache_path.write_bytes(archive.read(xml_names[0]))
    root = ElementTree.fromstring(cache_path.read_bytes())
    index: dict[str, list[str]] = defaultdict(list)
    for item in root.findall("list"):
        name = item.findtext("corp_name") or ""
        code = item.findtext("corp_code") or ""
        alias = _corp_alias(name)
        if alias and re.fullmatch(r"\d{8}", code):
            index[alias].append(code)
    return dict(index)


def _corp_alias(value: str) -> str:
    cleaned = re.sub(r"^\s*(?:\(주\)|㈜|주식회사|유한회사)\s*", "", value)
    cleaned = re.sub(r"\s*(?:\(주\)|㈜|주식회사|유한회사)\s*$", "", cleaned)
    return normalize_name(cleaned)


def _match_dart_corp(name: str, index: dict[str, list[str]]) -> str | None:
    matches = index.get(_corp_alias(name), [])
    return matches[0] if len(matches) == 1 else None


async def _fetch_dart_financial(
    client: httpx.AsyncClient,
    api_key: str,
    corp_code: str,
    year: int,
) -> dict[str, object] | None:
    for fs_div, basis in (("CFS", "연결"), ("OFS", "별도")):
        response = await client.get(
            f"{DART_API_BASE}/fnlttSinglAcntAll.json",
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": "11011",
                "fs_div": fs_div,
            },
        )
        response.raise_for_status()
        payload = response.json()
        parsed = parse_dart_financial(payload, year=year, basis=basis)
        if parsed:
            return parsed
        if isinstance(payload, dict) and payload.get("status") not in {"000", "013"}:
            raise ValueError("OpenDART financial request failed")
    return None


async def _fetch_dart_employees(
    client: httpx.AsyncClient,
    api_key: str,
    corp_code: str,
    year: int,
) -> tuple[int | None, str | None]:
    response = await client.get(
        f"{DART_API_BASE}/empSttus.json",
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": "11011",
        },
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("status") not in {"000", "013"}:
        raise ValueError("OpenDART employee request failed")
    return parse_dart_employees(payload)


def parse_dart_financial(
    payload: dict[str, object], *, year: int, basis: str
) -> dict[str, object] | None:
    rows = payload.get("list")
    if not isinstance(rows, list):
        return None
    revenue = _find_account_amount(
        rows,
        account_ids=("ifrs-full_Revenue",),
        names=("매출액", "수익(매출액)", "영업수익"),
    )
    operating_profit = _find_account_amount(
        rows,
        account_ids=("dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"),
        names=("영업이익", "영업이익(손실)", "영업손익"),
    )
    net_income = _find_account_amount(
        rows,
        account_ids=("ifrs-full_ProfitLoss",),
        names=("당기순이익", "당기순이익(손실)", "당기순손익"),
    )
    if revenue is None and operating_profit is None and net_income is None:
        return None
    return {
        "year": year,
        "revenue": revenue,
        "operating_profit": operating_profit,
        "net_income": net_income,
        "currency": "KRW",
        "basis": basis,
        "source": "OpenDART",
        "source_url": DART_SOURCE_URL,
    }


def parse_dart_employees(payload: dict[str, object]) -> tuple[int | None, str | None]:
    rows = payload.get("list")
    if not isinstance(rows, list):
        return None, None
    valid_rows = [row for row in rows if isinstance(row, dict)]
    total_rows = [row for row in valid_rows if str(row.get("fo_bbm") or "").strip() == "합계"]
    selected = total_rows or valid_rows
    counts = [_signed_int(row.get("sm")) for row in selected]
    total = sum(value for value in counts if value is not None)
    dates = [str(row.get("stlm_dt") or "") for row in selected if row.get("stlm_dt")]
    as_of = max(dates).replace(".", "-") if dates else None
    if as_of and len(as_of) == 10:
        as_of = f"{as_of}T00:00:00+09:00"
    return (total if any(value is not None for value in counts) else None), as_of


def _find_account_amount(
    rows: list[object], *, account_ids: tuple[str, ...], names: tuple[str, ...]
) -> int | None:
    for row in rows:
        if not isinstance(row, dict) or row.get("sj_div") not in {"IS", "CIS"}:
            continue
        account_id = str(row.get("account_id") or "")
        account_name = re.sub(r"\s+", "", str(row.get("account_nm") or ""))
        if account_id in account_ids or any(
            re.sub(r"\s+", "", name) == account_name for name in names
        ):
            amount = _signed_int(row.get("thstrm_amount"))
            if amount is not None:
                return amount
    return None


def _signed_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace(",", "").replace(" ", "")
    if not normalized or normalized in {"-", "—"}:
        return None
    negative = normalized.startswith("(") and normalized.endswith(")")
    normalized = normalized.strip("()")
    if not re.fullmatch(r"-?\d+", normalized):
        return None
    parsed = int(normalized)
    return -parsed if negative else parsed
