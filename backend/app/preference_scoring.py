"""User-directed AI scores, grounded in bounded, identity-free structured evidence."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Company, JobPosting, JobScore

VERSION = "ai_preference_v1"
PROMPT_PATH = Path(__file__).parent / "prompts/job_preference_v1.md"
CRITERIA = {
    "role": "직무",
    "experience": "연차",
    "stack": "기술",
    "location": "근무지",
    "company": "회사 실적·투자",
    "workload": "팀 규모·업무 부담",
}
DEFAULT_PREFERENCES = {
    "roles": ["backend", "product_engineer"],
    "primary_stack": ["Python"],
    "regions": ["서울", "경기", "인천"],
    "company": {
        "prefer_established_team": True,
        "avoid_solo_developer": True,
        "prefer_revenue_or_funding_evidence": True,
    },
}
CONTACT_KEYS = {"name", "email", "phone", "address", "contact", "resume", "raw_text", "url"}
Score = Annotated[int, Field(strict=True, ge=0, le=100)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Criterion(StrictModel):
    score: Score
    state: Literal["supported", "partial", "unknown"]
    reason: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(max_length=6)


class Criteria(StrictModel):
    role: Criterion
    experience: Criterion
    stack: Criterion
    location: Criterion
    company: Criterion
    workload: Criterion


class Evaluation(StrictModel):
    job_id: int = Field(strict=True, gt=0)
    fit_score: Score
    value_score: Score
    confidence: Literal["high", "medium", "low"]
    verdict: Literal["apply", "review", "skip"]
    summary: str = Field(min_length=1, max_length=600)
    criteria: Criteria
    risks: list[str] = Field(max_length=4)
    unknowns: list[str] = Field(max_length=4)
    questions: list[str] = Field(max_length=4)


class Evaluations(StrictModel):
    evaluations: list[Evaluation] = Field(min_length=1, max_length=5)


def clean_text(value: str) -> str:
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[연락처 생략]", value)
    value = re.sub(
        r"(?<!\d)(?:\+82[- .]?)?0?1[016789][- .]?\d{3,4}[- .]?\d{4}(?!\d)", "[연락처 생략]", value
    )
    return value


def _sources(values: dict, prefix: str, byte_limit: int, *, private: bool = False) -> dict:
    result = {}
    used = 0

    def visit(value, path):
        nonlocal used
        if isinstance(value, dict):
            for key, item in value.items():
                if private and (
                    str(key).lower() in CONTACT_KEYS
                    or any(
                        token in str(key).lower()
                        for token in ("email", "phone", "contact", "raw_text")
                    )
                ):
                    continue
                visit(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value[:30]):
                visit(item, f"{path}[{index}]")
        elif value is not None and not isinstance(value, bool) and str(value).strip():
            text = f"{path}: {clean_text(str(value))}"
            # Per-source bounds do not turn a company metric into a complete annual report.
            text = text.encode()[:900].decode(errors="ignore")
            size = len(text.encode())
            if used + size <= byte_limit:
                result[f"{prefix}{len(result) + 1}"] = text
                used += size

    for key, value in values.items():
        visit(value, key)
    return result


def preferences(path: str) -> dict:
    file = Path(path)
    if not file.is_file():
        return DEFAULT_PREFERENCES
    if file.stat().st_size > 8000:
        raise ValueError("preferences_too_large")
    data = json.loads(file.read_text())
    if not isinstance(data, dict) or set(data) - set(DEFAULT_PREFERENCES):
        raise ValueError("invalid_preferences")
    return {**DEFAULT_PREFERENCES, **data}


def candidate_sources(profile: dict) -> dict:
    fields = ("summary", "years_experience", "skills", "achievements", "skill_gaps")
    sources = _sources({key: profile.get(key) for key in fields}, "C", 10000, private=True)
    for key in ("name", "full_name"):
        identity = profile.get(key)
        if isinstance(identity, str) and len(identity.strip()) >= 2:
            sources = {ref: text.replace(identity, "[이름 생략]") for ref, text in sources.items()}
    return sources


def job_context(job: JobPosting, company: Company) -> dict:
    data = {
        "title": job.title,
        "experience": job.experience_text,
        "location": job.location,
        "tech_stack": job.tech_stack,
        "employment_type": job.employment_type,
        "requirements": job.requirements,
        "main_tasks": job.main_tasks,
        "preferred_requirements": job.preferred_requirements,
        "description_excerpt": (job.description_text or "")[:1800],
    }
    facts = {
        "employee_count": company.employee_count,
        "developer_count": company.developer_count,
        "employee_count_as_of": company.employee_count_as_of.isoformat()
        if company.employee_count_as_of
        else None,
        "employee_count_source": company.employee_count_source,
        "annual_revenue": company.annual_revenue,
        "investment_stage": company.investment_stage,
        "total_investment": company.total_investment,
        "profitability_status": company.profitability_status
        if company.profitability_status != "undisclosed"
        else None,
        "financial_history": (company.financial_history or [])[:3],
        "funding_history": (company.funding_history or [])[:3],
        "facts_as_of": company.facts_updated_at.isoformat() if company.facts_updated_at else None,
        "source_urls": (company.facts_source_urls or [])[:5],
    }
    return {
        "job_id": job.id,
        "evaluation_year": (datetime.now(UTC)).year,
        "company_name": company.name,
        "job": _sources(data, f"J{job.id}_", 8500),
        "company": _sources(facts, f"F{job.id}_", 6000),
    }


def input_hash(candidate: dict, context: dict, prefs: dict, model: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "version": VERSION,
                "prompt": PROMPT_PATH.read_text(),
                "candidate": candidate,
                "job": context,
                "preferences": prefs,
                "model": model,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def validate_evaluation(report: Evaluation, candidate: dict, context: dict) -> None:
    if report.job_id != context["job_id"]:
        raise ValueError("wrong_job_id")
    all_sources = {**candidate, **context["job"], **context["company"]}
    for key in CRITERIA:
        item = getattr(report.criteria, key)
        if item.state == "unknown":
            if item.evidence_ids or item.score > 50:
                raise ValueError("unsupported_unknown_score")
        elif not item.evidence_ids:
            raise ValueError("missing_citations")
        if any(source_id not in all_sources for source_id in item.evidence_ids):
            raise ValueError("invented_citation")
        if key == "company" and any(
            source_id not in context["company"] for source_id in item.evidence_ids
        ):
            raise ValueError("company_requires_company_facts")
        if key == "location" and any(
            source_id not in context["job"] for source_id in item.evidence_ids
        ):
            raise ValueError("location_requires_job_evidence")
    if any(len(text) > 350 for text in [*report.risks, *report.unknowns, *report.questions]):
        raise ValueError("explanation_too_long")


def apply_evaluation(
    score: JobScore,
    report: Evaluation,
    *,
    model: str,
    fingerprint: str,
    candidate: dict,
    context: dict,
    now: datetime | None = None,
) -> None:
    validate_evaluation(report, candidate, context)
    now = now or datetime.now(UTC)
    prior = score.evidence_json or {}
    rules = prior.get("rule_evidence", prior)
    original_scores = prior.get(
        "rule_scores",
        {
            "fit": score.total_fit_score,
            "value": score.application_value_score,
            "probability": score.application_probability_score,
            "version": score.scoring_version,
        },
    )
    sources = {**candidate, **context["job"], **context["company"]}
    breakdown = []
    matches = []
    for key, label in CRITERIA.items():
        item = getattr(report.criteria, key)
        own = [sources[ref] for ref in item.evidence_ids if ref in candidate]
        job_facts = [sources[ref] for ref in item.evidence_ids if ref not in candidate]
        breakdown.append(
            {
                "label": label,
                "score": item.score,
                "weight": 0,
                "reason": item.reason,
                "state": item.state,
                "profile_evidence": own,
                "job_evidence": job_facts,
            }
        )
        if item.score >= 70 and item.state != "unknown":
            matches.append(
                {
                    "skill": label,
                    "strength": "strong" if item.score >= 80 else "partial",
                    "profile_evidence": own,
                    "job_evidence": job_facts,
                }
            )
    score.total_fit_score = report.fit_score
    score.application_value_score = report.value_score
    # Compatibility field only; never present this as a calibrated hiring probability.
    score.application_probability_score = report.fit_score
    score.grade = (
        "S"
        if report.value_score >= 90
        else "A"
        if report.value_score >= 75
        else "B"
        if report.value_score >= 60
        else "C"
    )
    score.priority = report.value_score
    score.matching_reasons = matches
    score.missing_skills = []
    score.risk_notes = [*report.risks, *[f"미확인: {text}" for text in report.unknowns]]
    score.scoring_version = VERSION
    score.scored_at = now
    score.evidence_json = {
        "rule_scores": original_scores,
        "rule_evidence": rules,
        "preference_evaluation": {
            **report.model_dump(),
            "model": model,
            "input_hash": fingerprint,
            "evaluated_at": now.isoformat(),
            "version": VERSION,
        },
        "score_breakdown": breakdown,
        "score_summary": report.summary,
        "confidence": report.confidence,
        "formula": (
            "GPT가 직무·연차·기술·근무지·사업 기반·업무 부담을 종합 평가합니다. "
            "고정 가중치 합산이 아닙니다."
        ),
        "definitions": {
            "fit": "GPT가 평가한 현재 업무 수행 적합도",
            "value": "근무지·확인된 사업 기반·조직 규모를 포함한 GPT 지원 우선순위",
            "probability": "합격 확률 추정값이 아니라 적합도와 같은 보조값",
        },
        "career_fit": {
            "recommendation_grade": {
                "apply": "우선 검토",
                "review": "조건 확인",
                "skip": "우선순위 낮음",
            }[report.verdict],
            "recommendation_reasons": [report.summary, *report.questions],
        },
        "resume_recommendation": rules.get("resume_recommendation"),
    }
