from datetime import UTC, datetime

from app.company_enrichment import (
    _corp_alias,
    _match_dart_corp,
    parse_dart_employees,
    parse_dart_financial,
)
from app.company_facts import groupby_company_facts, merge_company_facts
from app.models import Company


def test_groupby_company_facts_preserve_disclosed_and_private_funding_amounts() -> None:
    facts = groupby_company_facts(
        {"id": 124, "memberCount": 20, "devCount": 13},
        startup_profile={
            "id": 124,
            "memberCount": 21,
            "devCount": 14,
            "businessNumber": "1234567890",
            "fundings": [
                {"round": "Pre-A", "amount": None, "attractedAt": "2026-05-01"},
                {"round": "Seed", "amount": 800_000_000, "attractedAt": "2025-01-01"},
            ],
        },
        collected_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert facts.employee_count == 21
    assert facts.developer_count == 14
    assert facts.investment_stage == "Pre-A"
    assert facts.funding_history[0]["amount"] is None
    assert facts.funding_history[1]["amount"] == 800_000_000
    assert facts.source_urls == ["https://groupby.kr/startups/124"]


def test_merge_company_facts_derives_scale_investment_and_profitability() -> None:
    company = Company(name="Example", normalized_name="example", source_urls=[])
    facts = groupby_company_facts(
        {"id": 7, "memberCount": 42, "fundingRound": "Series A"},
        collected_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    facts.financial_history = [
        {
            "year": 2025,
            "revenue": 5_000_000_000,
            "operating_profit": -300_000_000,
            "net_income": -400_000_000,
            "source": "OpenDART",
        }
    ]

    merge_company_facts(company, facts)

    assert company.company_size == "42명"
    assert company.annual_revenue == "5,000,000,000원"
    assert company.profitability_status == "loss"
    assert company.investment_stage == "Series A"


def test_dart_financial_parser_uses_income_statement_accounts() -> None:
    financial = parse_dart_financial(
        {
            "status": "000",
            "list": [
                {
                    "sj_div": "IS",
                    "account_id": "ifrs-full_Revenue",
                    "account_nm": "매출액",
                    "thstrm_amount": "12,300,000,000",
                },
                {
                    "sj_div": "IS",
                    "account_id": "dart_OperatingIncomeLoss",
                    "account_nm": "영업이익(손실)",
                    "thstrm_amount": "(450,000,000)",
                },
                {
                    "sj_div": "IS",
                    "account_id": "ifrs-full_ProfitLoss",
                    "account_nm": "당기순이익(손실)",
                    "thstrm_amount": "-510,000,000",
                },
            ],
        },
        year=2025,
        basis="연결",
    )

    assert financial == {
        "year": 2025,
        "revenue": 12_300_000_000,
        "operating_profit": -450_000_000,
        "net_income": -510_000_000,
        "currency": "KRW",
        "basis": "연결",
        "source": "OpenDART",
        "source_url": "https://dart.fss.or.kr/",
    }


def test_dart_employee_parser_sums_rows_and_keeps_statement_date() -> None:
    count, as_of = parse_dart_employees(
        {
            "status": "000",
            "list": [
                {"fo_bbm": "개발", "sexdstn": "남", "sm": "12", "stlm_dt": "2025.12.31"},
                {"fo_bbm": "개발", "sexdstn": "여", "sm": "8", "stlm_dt": "2025.12.31"},
            ],
        }
    )

    assert count == 20
    assert as_of == "2025-12-31T00:00:00+09:00"


def test_dart_company_matching_is_exact_and_rejects_ambiguous_names() -> None:
    assert _corp_alias("(주) 예시회사") == "예시회사"
    assert _match_dart_corp("예시회사", {"예시회사": ["00123456"]}) == "00123456"
    assert _match_dart_corp("예시회사", {"예시회사": ["00123456", "00999999"]}) is None
