from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class CollectedCompanyFacts:
    employee_count: int | None = None
    developer_count: int | None = None
    employee_count_source: str | None = None
    employee_count_as_of: str | None = None
    investment_stage: str | None = None
    funding_history: list[dict[str, object]] = field(default_factory=list)
    financial_history: list[dict[str, object]] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    business_registration_number: str | None = None
    dart_corp_code: str | None = None


@dataclass(slots=True)
class CollectedJob:
    source_name: str
    external_job_id: str
    company_name: str
    title: str
    url: str
    description_raw: str
    description_text: str
    main_tasks: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    preferred_requirements: list[str] = field(default_factory=list)
    benefits: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    hiring_process: list[str] = field(default_factory=list)
    has_coding_test: bool | None = None
    interview_count: int | None = None
    experience_text: str | None = None
    location: str | None = None
    employment_type: str | None = None
    salary_text: str | None = None
    posted_at: datetime | None = None
    deadline_at: datetime | None = None
    company_facts: CollectedCompanyFacts | None = None

    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def structured_content(self) -> dict[str, Any]:
        content = asdict(self)
        content.pop("description_raw", None)
        content.pop("observed_at", None)
        content["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        content["deadline_at"] = self.deadline_at.isoformat() if self.deadline_at else None
        return content


@dataclass(frozen=True, slots=True)
class RelevanceDecision:
    included: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UpsertResult:
    status: str
    job_posting_id: int
