from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.crawler.relevance import extract_tech_stack, is_technical_product_role
from app.models import JobPosting


@dataclass(frozen=True)
class ResumeVariant:
    id: str
    label: str
    short_label: str
    summary: str
    file_name: str
    title_terms: tuple[str, ...]
    role_terms: tuple[str, ...]
    technology_terms: tuple[str, ...]
    problem_terms: tuple[str, ...]
    startup_fit: float


RESUME_VARIANTS: tuple[ResumeVariant, ...] = (
    ResumeVariant(
        id="python_backend",
        label="Python 백엔드 이력서",
        short_label="서버 백엔드",
        summary="API·데이터·메시징을 중심으로 서버 개발 성과를 먼저 보여주는 버전",
        file_name="01_Python_서버_백엔드_이력서.local.pdf",
        title_terms=("backend", "back end", "백엔드", "server", "서버"),
        role_terms=(
            "api",
            "서비스 개발",
            "서버 개발",
            "database",
            "데이터베이스",
            "비동기",
            "messaging",
            "메시징",
            "대용량",
        ),
        technology_terms=(
            "python",
            "django",
            "fastapi",
            "flask",
            "rest api",
            "postgresql",
            "mysql",
            "redis",
            "kafka",
            "aws sqs",
            "sqlalchemy",
        ),
        problem_terms=(
            "api",
            "성능",
            "latency",
            "트래픽",
            "확장",
            "데이터 모델",
            "캐시",
            "비동기",
            "이벤트",
            "메시징",
        ),
        startup_fit=0.78,
    ),
    ResumeVariant(
        id="python_typescript_backend",
        label="Python·TypeScript 백엔드 이력서",
        short_label="Python·TypeScript 백엔드",
        summary=(
            "Python 주력 경력과 Node.js·TypeScript 실무, 공통 백엔드 운영 역량을 "
            "함께 보여주는 버전"
        ),
        file_name="04_Python_TypeScript_백엔드_이력서.local.pdf",
        title_terms=("backend", "back end", "백엔드", "server", "서버"),
        role_terms=(
            "api",
            "서비스 개발",
            "서버 개발",
            "serverless",
            "lambda",
            "database",
            "데이터베이스",
            "메시징",
        ),
        technology_terms=(
            "python",
            "typescript",
            "node.js",
            "nestjs",
            "express",
            "fastify",
            "aws lambda",
            "serverless framework",
            "rest api",
            "postgresql",
            "mysql",
            "redis",
            "kafka",
            "aws",
            "docker",
        ),
        problem_terms=(
            "api",
            "데이터 모델",
            "serverless",
            "lambda",
            "배포",
            "테스트",
            "장애",
            "성능",
            "확장",
        ),
        startup_fit=0.86,
    ),
    ResumeVariant(
        id="server_infra",
        label="Python 서버·인프라 이력서",
        short_label="서버·인프라",
        summary="배포 자동화·클라우드 운영·안정성 개선 경험을 앞세우는 버전",
        file_name="02_Python_서버_인프라_이력서.local.pdf",
        title_terms=(
            "devops",
            "데브옵스",
            "platform",
            "플랫폼",
            "infra",
            "인프라",
            "sre",
            "cloud",
            "클라우드",
        ),
        role_terms=(
            "배포",
            "운영",
            "자동화",
            "가용성",
            "관측",
            "모니터링",
            "인프라 구축",
            "ci cd",
            "container",
            "컨테이너",
        ),
        technology_terms=(
            "python",
            "aws",
            "docker",
            "kubernetes",
            "terraform",
            "ci/cd",
            "github actions",
            "jenkins",
            "argo cd",
            "linux",
            "prometheus",
            "grafana",
            "redis",
            "kafka",
            "postgresql",
        ),
        problem_terms=(
            "배포",
            "운영",
            "자동화",
            "장애",
            "안정성",
            "가용성",
            "모니터링",
            "비용",
            "확장",
            "scale",
            "성능",
        ),
        startup_fit=0.80,
    ),
    ResumeVariant(
        id="product_builder",
        label="프로덕트 엔지니어 이력서",
        short_label="Product Builder",
        summary="문제 정의부터 제품 구현·실험까지 맡은 오너십을 보여주는 버전",
        file_name="03_Product_Builder_Technical_PO_이력서.local.pdf",
        title_terms=(
            "product engineer",
            "프로덕트 엔지니어",
            "product owner",
            "product builder",
            "technical po",
            "tech po",
            "풀스택",
            "full stack",
            "founding",
            "초기 멤버",
        ),
        role_terms=(
            "문제 정의",
            "제품 목표",
            "프로덕트",
            "사용자",
            "지표",
            "실험",
            "가설",
            "기획부터",
            "end to end",
            "로드맵",
            "사업",
        ),
        technology_terms=(
            "python",
            "typescript",
            "react",
            "next.js",
            "fastapi",
            "django",
            "llm",
            "ai agent",
            "rest api",
            "postgresql",
            "aws",
        ),
        problem_terms=(
            "문제 정의",
            "사용자",
            "지표",
            "실험",
            "가설",
            "제품",
            "프로덕트",
            "기획",
            "우선순위",
            "로드맵",
            "비즈니스",
        ),
        startup_fit=0.96,
    ),
)

RESUME_VARIANTS_BY_ID = {variant.id: variant for variant in RESUME_VARIANTS}

STARTUP_TERMS = (
    "스타트업",
    "초기",
    "founding",
    "small team",
    "소규모 팀",
    "빠르게",
    "애자일",
    "agile",
    "주도",
    "오너십",
    "ownership",
    "end to end",
    "end-to-end",
    "0 to 1",
)
METRIC_PATTERN = re.compile(
    r"\d|%|퍼센트|배|건|명|원|초|분|시간|일|개월|년|트래픽|매출|비용|전환"
)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣+#./%]+", " ", value.casefold()).strip()


def _contains_term(text: str, term: str) -> bool:
    normalized_term = _normalize(term)
    return bool(normalized_term and normalized_term in text)


def _matching_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if _contains_term(text, term)]


def _profile_corpus(profile: dict[str, Any]) -> str:
    parts = [str(profile.get("summary", ""))]
    parts.extend(str(skill) for values in profile.get("skills", {}).values() for skill in values)
    parts.extend(
        str(achievement.get("evidence", ""))
        for achievement in profile.get("achievements", [])
    )
    return _normalize("\n".join(parts))


def _achievement_evidence(
    profile: dict[str, Any], variant: ResumeVariant, limit: int = 3
) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    terms = (*variant.technology_terms, *variant.problem_terms, *variant.role_terms)
    for index, achievement in enumerate(profile.get("achievements", [])):
        evidence = str(achievement.get("evidence", "")).strip()
        if not evidence:
            continue
        normalized = _normalize(evidence)
        term_hits = sum(_contains_term(normalized, term) for term in terms)
        metric_bonus = 3 if METRIC_PATTERN.search(evidence) else 0
        ranked.append((term_hits * 2 + metric_bonus, -index, evidence))
    ranked.sort(reverse=True)
    return [evidence for _score, _index, evidence in ranked[:limit]]


def _primary_variant(job: JobPosting, full_text: str) -> str:
    title = _normalize(job.title)
    if is_technical_product_role(job.title, job.description_text or ""):
        return "product_builder"
    product = RESUME_VARIANTS_BY_ID["product_builder"]
    infra = RESUME_VARIANTS_BY_ID["server_infra"]
    if _matching_terms(title, product.title_terms):
        return product.id
    if _matching_terms(title, infra.title_terms):
        return infra.id
    if any(
        _contains_term(full_text, term)
        for term in ("node.js", "nodejs", "typescript", "nestjs", "express", "fastify")
    ):
        return "python_typescript_backend"
    if len(_matching_terms(full_text, product.role_terms)) >= 4:
        return product.id
    if len(_matching_terms(full_text, infra.role_terms)) >= 4:
        return infra.id
    return "python_backend"


def _required_technologies(job: JobPosting) -> list[str]:
    explicit = extract_tech_stack("\n".join(job.requirements or []))
    if explicit:
        return list(dict.fromkeys(explicit))
    return list(
        dict.fromkeys(
            [
                *(job.tech_stack or []),
                *extract_tech_stack("\n".join([job.title, *(job.main_tasks or [])])),
            ]
        )
    )


def _technology_alignment(
    required: list[str], variant: ResumeVariant, profile_text: str
) -> tuple[float, list[str], list[str]]:
    if not required:
        return 0.68, [], []
    focus = {_normalize(term) for term in variant.technology_terms}
    values: list[float] = []
    emphasized: list[str] = []
    not_emphasized: list[str] = []
    for skill in required:
        normalized = _normalize(skill)
        has_profile_evidence = bool(normalized and normalized in profile_text)
        is_focus = normalized in focus or any(
            normalized in term or term in normalized for term in focus if normalized and term
        )
        if is_focus and has_profile_evidence:
            values.append(1.0)
            emphasized.append(skill)
        elif is_focus:
            values.append(0.72)
            emphasized.append(skill)
        elif has_profile_evidence:
            values.append(0.56)
            not_emphasized.append(skill)
        else:
            values.append(0.24)
            not_emphasized.append(skill)
    return sum(values) / len(values), emphasized, not_emphasized


def _role_alignment(
    variant: ResumeVariant, primary_id: str, title: str, full_text: str
) -> tuple[float, list[str]]:
    title_hits = _matching_terms(title, variant.title_terms)
    role_hits = _matching_terms(full_text, variant.role_terms)
    ratio = 0.42 + min(0.34, len(title_hits) * 0.17) + min(0.24, len(role_hits) * 0.04)
    if variant.id == primary_id:
        ratio = max(ratio, 0.90)
    return min(1.0, ratio), [*title_hits, *role_hits]


def _problem_alignment(variant: ResumeVariant, full_text: str) -> tuple[float, list[str]]:
    hits = _matching_terms(full_text, variant.problem_terms)
    if not hits:
        return 0.52, []
    return min(1.0, 0.58 + len(hits) * 0.075), hits


def _startup_alignment(variant: ResumeVariant, full_text: str) -> tuple[float, list[str]]:
    hits = _matching_terms(full_text, STARTUP_TERMS)
    context_bonus = min(0.12, len(hits) * 0.025)
    return min(1.0, variant.startup_fit + context_bonus), hits


def _metric_alignment(evidence: list[str]) -> float:
    if not evidence:
        return 0.45
    metric_count = sum(bool(METRIC_PATTERN.search(item)) for item in evidence)
    return min(1.0, 0.62 + metric_count * 0.12)


def _suggested_edits(
    variant: ResumeVariant,
    emphasized: list[str],
    not_emphasized: list[str],
    problem_hits: list[str],
    missing_skills: list[dict[str, Any]],
) -> list[str]:
    suggestions: list[str] = []
    if emphasized:
        suggestions.append(
            f"상단 요약과 최근 경력 첫 문장에 {', '.join(emphasized[:3])} 경험을 먼저 배치하세요."
        )
    if problem_hits:
        suggestions.append(
            f"{', '.join(problem_hits[:2])} 문제를 어떻게 판단하고 개선했는지 "
            "한 문장으로 연결하세요."
        )
    elif not_emphasized:
        suggestions.append(
            f"공고가 요구하는 {', '.join(not_emphasized[:2])}와 맞닿은 실제 경험이 "
            "있다면 기술 목록보다 경력 문장에 넣으세요."
        )
    high_gaps = [
        str(item.get("skill"))
        for item in missing_skills
        if item.get("severity") == "high" and item.get("skill")
    ]
    if high_gaps:
        suggestions.append(
            f"{', '.join(high_gaps[:2])}는 실무 근거가 없다면 과장하지 말고, "
            "인접 경험과 학습 범위를 분리해 적으세요."
        )
    if not suggestions:
        suggestions.append(
            f"{variant.short_label} 버전의 핵심 성과 순서를 공고 주요업무 순서와 맞추세요."
        )
    return suggestions[:3]


def build_resume_recommendation(
    job: JobPosting,
    profile: dict[str, Any],
    *,
    fit_score: float,
    missing_skills: list[dict[str, Any]],
) -> dict[str, Any]:
    full_text = _normalize(
        "\n".join(
            [
                job.title,
                job.description_text or "",
                *(job.main_tasks or []),
                *(job.requirements or []),
                *(job.preferred_requirements or []),
            ]
        )
    )
    title = _normalize(job.title)
    primary_id = _primary_variant(job, full_text)
    required = _required_technologies(job)
    profile_text = _profile_corpus(profile)
    results: list[dict[str, Any]] = []

    for variant in RESUME_VARIANTS:
        role_ratio, role_hits = _role_alignment(variant, primary_id, title, full_text)
        tech_ratio, emphasized, not_emphasized = _technology_alignment(
            required, variant, profile_text
        )
        problem_ratio, problem_hits = _problem_alignment(variant, full_text)
        startup_ratio, startup_hits = _startup_alignment(variant, full_text)
        evidence = _achievement_evidence(profile, variant)
        metric_ratio = _metric_alignment(evidence)
        breakdown = [
            {
                "label": "핵심 직무 적합",
                "score": round(role_ratio * 35, 1),
                "max_score": 35,
            },
            {
                "label": "요구 기술 강조",
                "score": round(tech_ratio * 25, 1),
                "max_score": 25,
            },
            {
                "label": "유사 문제 해결",
                "score": round(problem_ratio * 20, 1),
                "max_score": 20,
            },
            {
                "label": "수치 성과 전달",
                "score": round(metric_ratio * 10, 1),
                "max_score": 10,
            },
            {
                "label": "스타트업 실행 방식",
                "score": round(startup_ratio * 10, 1),
                "max_score": 10,
            },
        ]
        score = round(sum(item["score"] for item in breakdown), 1)
        reasons: list[str] = []
        if variant.id == primary_id:
            reasons.append(f"공고의 중심 역할이 {variant.short_label} 방향과 가장 가깝습니다.")
        if emphasized:
            reasons.append(
                f"필요 기술 중 {', '.join(emphasized[:4])}를 이 버전에서 앞세울 수 있습니다."
            )
        if problem_hits:
            reasons.append(
                f"{', '.join(problem_hits[:3])} 관련 문제 해결 경험을 연결하기 좋습니다."
            )
        if startup_hits:
            reasons.append("빠른 실행과 오너십을 요구하는 문맥을 이력서 구성에 반영하기 좋습니다.")
        results.append(
            {
                "id": variant.id,
                "label": variant.label,
                "short_label": variant.short_label,
                "summary": variant.summary,
                "score": score,
                "breakdown": breakdown,
                "reasons": reasons[:3]
                or [f"{variant.short_label} 관점에서 공고의 역할과 기술을 비교했습니다."],
                "matched_evidence": evidence,
                "suggested_edits": _suggested_edits(
                    variant,
                    emphasized,
                    not_emphasized,
                    problem_hits,
                    missing_skills,
                ),
            }
        )

    results.sort(key=lambda item: (float(item["score"]), item["id"] == primary_id), reverse=True)
    for index, item in enumerate(results):
        item["rank"] = index + 1
        item["is_recommended"] = index == 0
    lead = float(results[0]["score"]) - float(results[1]["score"])
    confidence = "high" if lead >= 10 else "medium" if lead >= 5 else "low"
    decision_label = (
        "지원 추천"
        if fit_score >= 76
        else "조건부 추천"
        if fit_score >= 63
        else "보완 후 검토"
    )
    decision_reason = (
        f"공고 적합도 {fit_score:.1f}점이며, {results[0]['short_label']} 버전이 "
        f"차선 버전보다 {lead:.1f}점 높습니다."
    )
    return {
        "recommended_id": results[0]["id"],
        "recommended_label": results[0]["label"],
        "recommended_score": results[0]["score"],
        "alternative_id": results[1]["id"],
        "alternative_label": results[1]["label"],
        "confidence": confidence,
        "decision": {"label": decision_label, "reason": decision_reason},
        "criteria": (
            "핵심 직무 35 + 요구 기술 25 + 유사 문제 해결 20 + "
            "수치 성과 10 + 스타트업 실행 방식 10"
        ),
        "resumes": results,
    }


def resume_catalog(settings: Settings) -> list[dict[str, Any]]:
    return [resume_metadata(variant.id, settings) for variant in RESUME_VARIANTS]


def resume_metadata(resume_id: str, settings: Settings) -> dict[str, Any]:
    variant = RESUME_VARIANTS_BY_ID[resume_id]
    file_path = resolve_resume_file(resume_id, settings)
    return {
        "id": variant.id,
        "label": variant.label,
        "short_label": variant.short_label,
        "summary": variant.summary,
        "available": file_path is not None,
        "file_url": f"/api/resumes/{variant.id}/file" if file_path else None,
    }


def resolve_resume_file(resume_id: str, settings: Settings) -> Path | None:
    variant = RESUME_VARIANTS_BY_ID.get(resume_id)
    if variant is None:
        return None
    root = Path(settings.resume_directory).expanduser().resolve()
    candidate = (root / variant.file_name).resolve()
    if candidate.parent != root or not candidate.is_file() or candidate.suffix.casefold() != ".pdf":
        return None
    return candidate


def enrich_resume_recommendation(
    recommendation: dict[str, Any] | None, settings: Settings
) -> dict[str, Any] | None:
    if not recommendation:
        return None
    enriched = {**recommendation}
    resumes = []
    for item in recommendation.get("resumes", []):
        resume_id = str(item.get("id", ""))
        metadata = (
            resume_metadata(resume_id, settings)
            if resume_id in RESUME_VARIANTS_BY_ID
            else {"available": False, "file_url": None}
        )
        resumes.append(
            {
                **item,
                "available": metadata["available"],
                "file_url": metadata["file_url"],
            }
        )
    enriched["resumes"] = resumes
    return enriched
