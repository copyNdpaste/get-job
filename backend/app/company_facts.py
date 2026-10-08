import re
from datetime import UTC, datetime
from typing import Any

from app.crawler.domain import CollectedCompanyFacts
from app.models import Company


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer():
        return int(value) if value >= 0 else None
    if isinstance(value, str):
        digits = re.sub(r"[^0-9-]", "", value)
        if digits and digits != "-":
            parsed = int(digits)
            return parsed if parsed >= 0 else None
    return None


def groupby_company_facts(
    startup: dict[str, Any],
    *,
    startup_profile: dict[str, Any] | None = None,
    collected_at: datetime | None = None,
) -> CollectedCompanyFacts:
    profile = startup_profile or {}
    # Display-restricted responses contain plausible substitute facts, not real data.
    # Never attach those figures to the requested company's existing record.
    for payload in (startup, profile):
        name = payload.get("name")
        if isinstance(name, str) and "[표시 제한]" in name:
            raise ValueError("GroupBy company profile is display restricted")
    startup_id = profile.get("id") or startup.get("id")
    source_url = (
        f"https://groupby.kr/startups/{startup_id}"
        if isinstance(startup_id, int) and startup_id > 0
        else "https://groupby.kr"
    )
    timestamp = (collected_at or datetime.now(UTC)).isoformat()
    fundings = profile.get("fundings")
    funding_history: list[dict[str, object]] = []
    if isinstance(fundings, list):
        for funding in fundings:
            if not isinstance(funding, dict):
                continue
            date = str(funding.get("attractedAt") or "")[:10] or None
            round_name = str(funding.get("round") or "").strip() or "투자"
            funding_history.append(
                {
                    "date": date,
                    "round": round_name,
                    "amount": _positive_int(funding.get("amount")),
                    "currency": "KRW",
                    "source": "그룹바이",
                    "source_url": source_url,
                }
            )
    funding_history.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
    latest_round = (
        str(funding_history[0]["round"])
        if funding_history
        else str(profile.get("fundingRound") or startup.get("fundingRound") or "").strip()
        or None
    )
    employee_count = _positive_int(profile.get("memberCount"))
    if employee_count is None:
        employee_count = _positive_int(startup.get("memberCount"))
    developer_count = _positive_int(profile.get("devCount"))
    if developer_count is None:
        developer_count = _positive_int(startup.get("devCount"))
    business_number = str(
        profile.get("businessNumber") or startup.get("businessNumber") or ""
    ).strip()
    return CollectedCompanyFacts(
        employee_count=employee_count,
        developer_count=developer_count,
        employee_count_source="그룹바이" if employee_count is not None else None,
        employee_count_as_of=timestamp if employee_count is not None else None,
        investment_stage=latest_round,
        funding_history=funding_history,
        source_urls=[source_url],
        business_registration_number=business_number or None,
    )


def merge_company_facts(company: Company, facts: CollectedCompanyFacts | None) -> None:
    if facts is None:
        return
    incoming_as_of = _parse_datetime(facts.employee_count_as_of)
    if facts.employee_count is not None and (
        company.employee_count_as_of is None
        or incoming_as_of is None
        or incoming_as_of >= company.employee_count_as_of
    ):
        company.employee_count = facts.employee_count
        company.company_size = f"{facts.employee_count:,}명"
        company.employee_count_source = facts.employee_count_source
        company.employee_count_as_of = incoming_as_of
    if facts.developer_count is not None:
        company.developer_count = facts.developer_count
    if facts.investment_stage:
        company.investment_stage = facts.investment_stage
    if facts.business_registration_number:
        company.business_registration_number = facts.business_registration_number
    if facts.dart_corp_code:
        company.dart_corp_code = facts.dart_corp_code
    if facts.funding_history:
        company.funding_history = _merge_history(
            company.funding_history or [], facts.funding_history, ("date", "round", "source")
        )
        known_total = sum(
            int(item["amount"])
            for item in company.funding_history
            if isinstance(item.get("amount"), int)
        )
        company.total_investment = f"{known_total:,}원" if known_total else None
    if facts.financial_history:
        company.financial_history = _merge_history(
            company.financial_history or [], facts.financial_history, ("year", "source")
        )
        latest = max(company.financial_history, key=lambda item: int(item.get("year") or 0))
        revenue = latest.get("revenue")
        company.annual_revenue = f"{revenue:,}원" if isinstance(revenue, int) else None
        operating_profit = latest.get("operating_profit")
        if isinstance(operating_profit, int):
            company.profitability_status = (
                "profit"
                if operating_profit > 0
                else "loss"
                if operating_profit < 0
                else "break_even"
            )
    company.facts_source_urls = list(
        dict.fromkeys([*(company.facts_source_urls or []), *facts.source_urls])
    )
    company.facts_updated_at = datetime.now(UTC)


def _merge_history(
    existing: list[dict[str, object]],
    incoming: list[dict[str, object]],
    keys: tuple[str, ...],
) -> list[dict[str, object]]:
    merged = {tuple(str(item.get(key) or "") for key in keys): item for item in existing}
    for item in incoming:
        merged[tuple(str(item.get(key) or "") for key in keys)] = item
    return sorted(
        merged.values(),
        key=lambda item: str(item.get("date") or item.get("year") or ""),
        reverse=True,
    )


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None
