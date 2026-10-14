# ruff: noqa: E501
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.relevance import (
    assess_relevance,
    estimate_backend_share,
    extract_tech_stack,
    is_likely_target_role,
    is_technical_product_role,
)
from app.hard_requirements import assess_hard_requirements
from app.models import CandidateProfile, JobPosting, JobScore
from app.resume_recommendation import build_resume_recommendation

SCORING_VERSION = "rules-v8-go-backend"

ALIASES = {
    "aws": {"aws", "aws ecs", "ecs fargate", "ec2", "rds", "s3", "ecr"},
    "ai agent": {"ai agent", "llm api", "prompt engineering", "claude code", "codex"},
    "django rest framework": {"django rest framework", "rest api"},
    "go": {"go", "golang"},
    "kafka": {"kafka", "aws sqs"},
    "kubernetes": {"kubernetes"},
    "llm": {"llm", "llm api", "prompt engineering", "gemini flash lite api"},
    "next.js": {"next.js", "nextjs", "react"},
    "node.js": {"node.js", "nodejs", "express", "fastify"},
    "nestjs": {"nestjs", "nest.js"},
    "express": {"express", "express.js", "node.js", "nodejs"},
    "fastify": {"fastify", "node.js", "nodejs"},
    "postgresql": {"postgresql", "sqlalchemy", "alembic"},
    "react": {"react", "vite"},
    "rest api": {"rest api", "django rest framework", "fastapi", "flask"},
    "spring": {"spring", "spring boot", "spring framework"},
    "typescript": {"typescript"},
    "ci/cd": {"ci/cd", "github actions", "jenkins", "argo cd", "gitlab ci"},
    "github actions": {"github actions", "ci/cd"},
    "jenkins": {"jenkins", "ci/cd"},
    "argo cd": {"argo cd", "ci/cd"},
    "unit testing": {"unit testing", "pytest", "unittest", "tdd", "test"},
    "pytest": {"pytest", "unit testing", "test"},
    "vector db": {"vector db", "faiss", "pgvector", "pinecone", "weaviate", "milvus"},
    "data pipeline": {"data pipeline", "etl", "airflow", "prefect", "dagster"},
}

BACKEND_CORE_SKILLS = {
    "python",
    "django",
    "fastapi",
    "flask",
    "typescript",
    "node.js",
    "nestjs",
    "express",
    "fastify",
    "rest api",
    "java",
    "spring",
    "go",
    "grpc",
    "c#",
    ".net",
    "ruby",
    "rails",
}
DATABASE_SKILLS = {"postgresql", "mysql", "redis", "mongodb", "elasticsearch"}
INFRA_SKILLS = {
    "aws",
    "docker",
    "kubernetes",
    "gcp",
    "azure",
    "terraform",
    "ncp",
    "ci/cd",
    "github actions",
    "jenkins",
    "argo cd",
    "linux",
    "prometheus",
    "grafana",
    "datadog",
    "sentry",
}
AI_SKILLS = {"llm", "ai agent", "langchain", "langgraph", "pytorch", "tensorflow"}
MODEL_TRAINING_TERMS = (
    "model training",
    "fine tuning",
    "fine-tuning",
    "학습 파이프라인",
    "모델 학습",
    "pytorch",
    "tensorflow",
    "rlhf",
    "dpo",
    "computer vision",
    "research scientist",
)
MODEL_SPECIALIST_TERMS = (
    "prompt engineering",
    "프롬프트 엔지니어링",
    "model inference",
    "모델 추론",
    "model serving",
    "모델 서빙",
    "open source model",
    "오픈소스 모델",
    "hugging face",
    "huggingface",
    "fine tuning",
    "fine-tuning",
    "파인튜닝",
    "gpu 환경",
    "ocr",
    "computer vision",
    "컴퓨터 비전",
    "vision ai",
    "영상처리",
    "image segmentation",
    "이미지 세그멘테이션",
    "deep learning",
    "딥러닝",
    "machine learning",
    "머신러닝",
    "모델 연구",
    "model research",
    "모델 평가",
    "model evaluation",
    "모델링",
    "논문",
    "labeling",
    "라벨링",
    "diffusion",
    "lora",
    "dreambooth",
    "영상 생성 모델",
    "이미지 생성 모델",
    "houdini",
)
BACKEND_DELIVERY_TERMS = (
    "backend",
    "백엔드",
    "api server",
    "api 서버",
    "rest api",
    "server development",
    "서버 개발",
    "database design",
    "데이터베이스 설계",
    "db 설계",
    "service development",
    "서비스 개발",
    "서비스 구현",
    "application development",
    "애플리케이션 개발",
    "web service",
    "웹 서비스",
    "product development",
    "프로덕트 개발",
    "제품 개발",
    "service architecture",
    "서비스 아키텍처",
    "cloud infrastructure",
    "클라우드 인프라",
    "ci cd",
    "observability",
    "인증 권한",
    "workflow orchestration",
    "워크플로우 오케스트레이션",
)
PURE_AI_TITLE_TERMS = (
    "ml engineer",
    "machine learning engineer",
    "머신러닝 엔지니어",
    "vision ai",
    "computer vision",
    "컴퓨터 비전",
    "deep learning engineer",
    "딥러닝 엔지니어",
    "nlp engineer",
    "자연어 처리",
    "ai r d",
    "ai 연구",
    "model engineer",
    "모델 엔지니어",
)
AI_ENGINEERING_TITLE_TERMS = (
    "ai engineer",
    "ai 엔지니어",
    "ai 개발자",
    "ai개발자",
    "ai agent developer",
    "ai agent engineer",
    "agentic ai engineer",
    "llm engineer",
    "applied ai engineer",
    "생성 ai",
    "생성형 ai",
)

RESPONSIBILITY_SIGNALS: tuple[tuple[tuple[str, ...], str, float], ...] = (
    (("api", "backend", "백엔드", "서버"), "API·백엔드 서비스", 1.25),
    (("database", "db", "데이터베이스", "sql"), "DB 설계·데이터 처리", 1.0),
    (("aws", "cloud", "docker", "배포", "운영"), "클라우드 배포·운영", 1.0),
    (("kafka", "queue", "messaging", "이벤트"), "메시징·비동기 처리", 0.9),
    (("test", "테스트", "tdd", "bdd", "품질"), "테스트·품질 개선", 0.8),
    (("llm api", "ai agent", "생성형 ai", "prompt"), "AI 제품 API 적용", 0.9),
    (("성능", "performance", "latency", "확장", "scale"), "성능·확장성 개선", 0.8),
    (("model training", "모델 학습", "pytorch", "tensorflow"), "모델 학습", 1.15),
)

SYSTEM_DESIGN_TERMS = (
    "architecture",
    "아키텍처",
    "system design",
    "시스템 설계",
    "distributed",
    "분산",
    "msa",
    "microservice",
    "확장성",
    "scalability",
    "대용량",
    "성능 최적화",
)
OWNERSHIP_TERMS = (
    "ownership",
    "오너십",
    "end to end",
    "end-to-end",
    "기획부터",
    "문제 정의",
    "제품 개선",
    "product",
    "주도",
    "lead",
    "리딩",
)
QUALITY_TERMS = (
    "test",
    "테스트",
    "tdd",
    "bdd",
    "품질",
    "code review",
    "코드 리뷰",
    "ci/cd",
)
COLLABORATION_TERMS = (
    "협업",
    "communication",
    "커뮤니케이션",
    "stakeholder",
    "코드 리뷰",
    "code review",
    "agile",
    "애자일",
    "scrum",
    "스프린트",
)

STATUS_POINTS = {
    "strong": 91.0,
    "transferable": 74.0,
    "limited": 51.0,
    "no_professional": 37.0,
    "none": 0.0,
    "missing": 9.0,
}

NODE_BACKEND_SKILLS = {"node.js", "typescript", "nestjs", "express", "fastify"}
GO_BACKEND_SKILLS = {"go"}
JAVA_SPRING_SKILLS = {"java", "spring"}
JOBPLANET_TARGET_OCCUPATIONS = ("백엔드 개발", "소프트웨어 개발")
JOBPLANET_MAX_EXCLUDED_FIT_SCORE = 60.0


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣+#.]+", " ", value.casefold()).strip()


def _has_ai_title_signal(title: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])(?:ai|ml|llm|nlp)(?![a-z0-9])", title)) or any(
        term in title
        for term in (
            "인공지능",
            "머신러닝",
            "딥러닝",
            "컴퓨터 비전",
            "vision",
            "프롬프트",
            "생성형",
        )
    )


def _is_jobplanet_development_role(job: JobPosting, excluded_reasons: tuple[str, ...]) -> bool:
    source = job.source
    description = job.description_text or ""
    return (
        source is not None
        and source.name == "jobplanet"
        and any(occupation in description for occupation in JOBPLANET_TARGET_OCCUPATIONS)
        and is_likely_target_role(job.title)
        and not any(reason.startswith("excluded:") for reason in excluded_reasons)
    )


def _exclude_low_fit_jobplanet(job: JobPosting, fit_score: float) -> None:
    source = job.source
    if (
        source is not None
        and source.name == "jobplanet"
        and fit_score <= JOBPLANET_MAX_EXCLUDED_FIT_SCORE
    ):
        job.is_active = False


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _profile_skills(profile: dict[str, Any]) -> set[str]:
    return {_normalized(skill) for values in profile.get("skills", {}).values() for skill in values}


def _profile_skill_years(profile: dict[str, Any], skill: str) -> float:
    requested = _normalized(skill)
    values = profile.get("skill_experience_years", {})
    if not isinstance(values, dict):
        return 0.0
    for name, years in values.items():
        if _normalized(str(name)) not in _skill_candidates(requested):
            continue
        try:
            return max(0.0, float(years))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _has_node_backend_experience(profile: dict[str, Any]) -> bool:
    corpus = _profile_corpus(profile)
    if any(
        term in corpus
        for term in ("node.js", "nodejs", "typescript", "serverless framework", "aws lambda")
    ):
        return True
    return any(_profile_skill_years(profile, skill) > 0 for skill in NODE_BACKEND_SKILLS)


def _skill_required_years(lines: list[str], skills: set[str]) -> int | None:
    maximum: int | None = None
    for line in lines:
        normalized = _normalized(line)
        if "우대" in normalized or "preferred" in normalized:
            continue
        line_skills = {_normalized(skill) for skill in extract_tech_stack(line)}
        if not line_skills.intersection(skills):
            continue
        years = [int(value) for value in re.findall(r"(\d+)\s*년", normalized)]
        if years:
            maximum = max(maximum or 0, max(years))
    return maximum


def _requires_java_spring(lines: list[str]) -> bool:
    for line in lines:
        normalized = _normalized(line)
        line_skills = {_normalized(skill) for skill in extract_tech_stack(line)}
        if not line_skills.intersection(JAVA_SPRING_SKILLS):
            continue
        alternative_markers = ("또는", "중 하나", "하나 이상", "one or more", "any of")
        has_backend_alternative = bool(line_skills & {"python", *NODE_BACKEND_SKILLS}) and (
            any(marker in normalized for marker in alternative_markers)
            or bool(re.search(r"\bor\b", normalized))
        )
        if not has_backend_alternative:
            return True
    return False


def _skill_candidates(skill: str) -> set[str]:
    normalized = _normalized(skill)
    return {_normalized(value) for value in ALIASES.get(normalized, {normalized})}


def _matches(skill: str, known: set[str]) -> bool:
    return bool(_skill_candidates(skill) & known)


def _skill_status(
    skill: str,
    known: set[str],
    limited: set[str],
    no_experience: set[str],
    none: set[str],
) -> str:
    candidates = _skill_candidates(skill)
    if candidates & none:
        return "none"
    if candidates & no_experience:
        return "no_professional"
    if candidates & limited:
        return "limited"
    if candidates & known:
        return "strong"
    return "missing"


def _profile_evidence(skill: str, profile: dict[str, Any]) -> list[str]:
    candidates = _skill_candidates(skill)
    evidence: list[str] = []
    for category, values in profile.get("skills", {}).items():
        for value in values:
            if _normalized(value) in candidates:
                evidence.append(f"이력서 기술/{category}: {value}")
    for achievement in profile.get("achievements", []):
        achievement_text = _normalized(str(achievement.get("evidence", "")))
        if any(candidate and candidate in achievement_text for candidate in candidates):
            evidence.append(
                f"성과/{achievement.get('company', '프로젝트')}: {achievement.get('evidence', '')}"
            )
    return evidence[:3]


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _profile_corpus(profile: dict[str, Any]) -> str:
    values = [str(profile.get("summary", ""))]
    values.extend(str(skill) for skills in profile.get("skills", {}).values() for skill in skills)
    values.extend(
        str(achievement.get("evidence", "")) for achievement in profile.get("achievements", [])
    )
    return _normalized("\n".join(values))


def _skill_evidence_depth(skill: str, profile: dict[str, Any]) -> int:
    candidates = _skill_candidates(skill)
    depth = 0
    for values in profile.get("skills", {}).values():
        if any(_normalized(value) in candidates for value in values):
            depth += 1
    for achievement in profile.get("achievements", []):
        evidence = _normalized(str(achievement.get("evidence", "")))
        if any(candidate and candidate in evidence for candidate in candidates):
            depth += 1
    return depth


def _status_score(skill: str, status: str, profile: dict[str, Any]) -> float:
    base = STATUS_POINTS[status]
    if status == "strong":
        return min(99.0, base + min(8.0, _skill_evidence_depth(skill, profile) * 2.25))
    if status == "transferable":
        return min(82.0, base + min(8.0, _skill_evidence_depth(skill, profile) * 2.0))
    if status == "limited":
        return min(59.0, base + min(8.0, _skill_evidence_depth(skill, profile) * 2.0))
    if status == "no_professional":
        return min(45.0, base + min(8.0, _skill_evidence_depth(skill, profile) * 2.0))
    return base


def _skill_weights(skills: list[str], lines: list[str]) -> dict[str, float]:
    normalized_lines = [_normalized(line) for line in lines]
    weights: dict[str, float] = {}
    for skill in skills:
        candidates = _skill_candidates(skill)
        matched_lines = [
            line
            for line in normalized_lines
            if any(candidate and candidate in line for candidate in candidates)
        ]
        emphasis = any(
            marker in line
            for line in matched_lines
            for marker in ("필수", "required", "must", "mandatory", "이상", "숙련")
        )
        weights[skill] = (
            1.0 + min(0.6, max(0, len(matched_lines) - 1) * 0.2) + (0.25 if emphasis else 0.0)
        )
    return weights


def _strict_required_gap(
    skill: str,
    requirement_lines: list[str],
    statuses: dict[str, str],
) -> bool:
    """Return true only for an unmet technology stated as a concrete must-have."""
    candidates = _skill_candidates(skill)
    for original_line in requirement_lines:
        line = _normalized(original_line)
        if not any(candidate and candidate in line for candidate in candidates):
            continue
        line_skills = extract_tech_stack(original_line)
        has_alternative = any(
            marker in line for marker in ("또는", "중 하나", "하나 이상", "one or more", "any of")
        ) or bool(re.search(r"\bor\b", line))
        if has_alternative and any(
            statuses.get(other) == "strong" for other in line_skills if other != skill
        ):
            continue
        if any(marker in line for marker in ("학습 의지", "관심이 있", "우대")):
            continue
        if any(
            marker in line
            for marker in (
                "경험",
                "경력",
                "실무",
                "운영",
                "구축",
                "설계",
                "개발",
                "활용",
                "사용",
                "능력",
                "역량",
                "숙련",
                "필수",
                "이상",
            )
        ):
            return True
    return False


def _weighted_coverage(
    skills: list[str],
    statuses: dict[str, str],
    profile: dict[str, Any],
    weights: dict[str, float] | None = None,
    default: float = 58.0,
) -> float:
    if not skills:
        return default
    resolved_weights = weights or {skill: 1.0 for skill in skills}
    total_weight = sum(resolved_weights.get(skill, 1.0) for skill in skills)
    weighted = sum(
        _status_score(skill, statuses[skill], profile) * resolved_weights.get(skill, 1.0)
        for skill in skills
    )
    return _clamp(weighted / total_weight)


def _precise_experience_score(text: str | None, years: int, base: float) -> float:
    if not text:
        return 67.0
    normalized = text.casefold()
    if "무관" in normalized or "전체" in normalized:
        return 92.0 + min(3.0, years * 0.35)
    ranges = [
        (int(low), int(high)) for low, high in re.findall(r"(\d+)\s*[~\-]\s*(\d+)\s*년", normalized)
    ]
    matching = [(low, high) for low, high in ranges if low <= years <= high]
    if matching:
        low, high = min(matching, key=lambda item: item[1] - item[0])
        midpoint = (low + high) / 2
        half_width = max(1.0, (high - low) / 2)
        closeness = max(0.0, 1.0 - abs(years - midpoint) / half_width)
        return 92.0 + closeness * 5.0
    values = [int(value) for value in re.findall(r"\d+", normalized)]
    if values and base >= 90:
        requirement = values[0]
        surplus = years - requirement
        return _clamp(91.0 + min(6.0, max(0, surplus) * 0.75))
    return _clamp(base - (2.0 if base < 70 else 0.0))


def _evidence_quality(job: JobPosting, explicit_required: bool) -> float:
    description_length = len((job.description_text or "").strip())
    score = 24.0
    score += min(24.0, len(job.requirements or []) * 4.0)
    score += min(18.0, len(job.main_tasks or []) * 3.0)
    score += min(12.0, len(job.tech_stack or []) * 1.5)
    score += min(7.0, len(job.preferred_requirements or []) * 1.4)
    score += 7.0 if job.experience_text else 0.0
    score += 4.0 if explicit_required else 0.0
    score += min(4.0, description_length / 500.0 * 4.0)
    return _clamp(score)


def _term_alignment(
    job_text: str,
    profile_text: str,
    terms: tuple[str, ...],
    neutral: float,
) -> tuple[float, int, int]:
    normalized_terms = [_normalized(term) for term in terms]
    job_hits = sum(bool(term and term in job_text) for term in normalized_terms)
    if not job_hits:
        return neutral, 0, 0
    profile_hits = sum(bool(term and term in profile_text) for term in normalized_terms)
    if not profile_hits:
        return max(28.0, 48.0 - min(12.0, job_hits * 2.0)), job_hits, 0
    coverage = min(1.0, profile_hits / max(1, job_hits))
    return min(98.0, 82.0 + coverage * 12.0 + min(4.0, profile_hits)), job_hits, profile_hits


def _job_evidence(skill: str, job: JobPosting) -> list[str]:
    candidates = _skill_candidates(skill)
    evidence: list[str] = []
    for label, lines in (
        ("자격요건", job.requirements or []),
        ("우대사항", job.preferred_requirements or []),
        ("주요업무", job.main_tasks or []),
    ):
        for line in lines:
            normalized_line = _normalized(line)
            if any(candidate and candidate in normalized_line for candidate in candidates):
                evidence.append(f"{label}: {line}")
    return evidence[:3] or [f"공고 기술 스택: {skill}"]


def _experience_eligibility(text: str | None, years: int) -> tuple[float, str | None]:
    if not text:
        return 70.0, "공고에 경력 조건이 없어 적합도 신뢰도가 낮음"
    normalized = text.casefold()
    if "무관" in normalized or "전체" in normalized:
        return 95.0, None

    ranges = [
        (int(low), int(high)) for low, high in re.findall(r"(\d+)\s*[~\-]\s*(\d+)\s*년", normalized)
    ]
    if ranges:
        if any(low <= years <= high for low, high in ranges):
            return 95.0, None
        minimum = min(low for low, _high in ranges)
        maximum = max(high for _low, high in ranges)
        if years < minimum:
            gap = minimum - years
            return max(20.0, 65.0 - gap * 15), f"요구 경력 {minimum}년 대비 프로필 {years}년"
        return max(65.0, 85.0 - (years - maximum) * 5), (
            f"공고 경력 상한 {maximum}년보다 프로필 경력 {years}년이 높아 포지션 레벨 확인 필요"
        )

    values = [int(value) for value in re.findall(r"\d+", normalized)]
    if not values:
        return 70.0, "경력 조건을 구조적으로 해석하지 못해 확인 필요"
    requirement = values[0]
    if "이하" in normalized:
        if years <= requirement:
            return 95.0, None
        return max(60.0, 85.0 - (years - requirement) * 5), (
            f"공고 경력 상한 {requirement}년보다 프로필 경력 {years}년이 높음"
        )
    if years >= requirement:
        return 95.0, None
    gap = requirement - years
    return max(20.0, 65.0 - gap * 15), f"요구 경력 {requirement}년 대비 프로필 {years}년"


def _role_assessment(job: JobPosting) -> tuple[float, str, list[str], int | None]:
    title = _normalized(job.title)
    full_text = _normalized(
        "\n".join([job.title, job.description_text or "", *(job.requirements or [])])
    )
    risks: list[str] = []
    cap: int | None = None
    if is_technical_product_role(job.title, job.description_text or ""):
        return (
            78.0,
            "Technical PO·Product Builder",
            ["백엔드 전담보다 제품 목표·실험·구현 오너십이 큰 하이브리드 직무"],
            82,
        )
    if any(term in title for term in ("강사", "instructor", "teacher")):
        return 25.0, "교육·강사", ["개발 실무보다 교육 전달이 중심인 직무"], 45
    if any(term in title for term in ("android", "안드로이드", "ios developer")):
        return 20.0, "모바일 앱", ["현재 핵심 경력인 Python 백엔드와 직무 방향이 다름"], 40
    if any(
        term in title
        for term in (
            "research engineer",
            "researcher",
            "리서치",
            "리서칭",
            "연구 엔지니어",
            "연구원",
        )
    ):
        return (
            42.0,
            "모델 연구·학습 AI",
            ["Python 활용과 별개로 논문 재현·모델 연구가 중심인 직무"],
            65,
        )
    if any(term in title for term in ("backend", "back end", "백엔드", "server", "서버")):
        return 96.0, "백엔드·서버", risks, cap
    if any(
        term in title
        for term in (
            "full stack",
            "fullstack",
            "풀스택",
            "product engineer",
            "제품 엔지니어",
            "프로덕트 엔지니어",
        )
    ):
        return 85.0, "제품·풀스택", risks, cap
    if any(
        term in title
        for term in (
            "devops",
            "데브옵스",
            "platform engineer",
            "sre",
            "cloud",
            "mlops",
            "llm ops",
            "ai ops",
            "ai infrastructure",
            "ai 인프라",
        )
    ):
        return 76.0, "플랫폼·DevOps", risks, None
    if any(term in title for term in ("data engineer", "데이터 엔지니어")):
        return 72.0, "데이터 엔지니어", risks, None
    if any(term in title for term in ("software engineer", "소프트웨어 엔지니어")):
        return 70.0, "소프트웨어 엔지니어", risks, None
    model_training = any(_normalized(term) in full_text for term in MODEL_TRAINING_TERMS)
    model_specialist = any(
        _normalized(term) in full_text for term in MODEL_SPECIALIST_TERMS
    )
    backend_delivery = any(
        _normalized(term) in full_text for term in BACKEND_DELIVERY_TERMS
    )
    backend_delivery_hits = sum(
        _normalized(term) in full_text for term in BACKEND_DELIVERY_TERMS
    )
    substantial_backend_delivery = backend_delivery_hits >= 2
    pure_ai_title = any(term in title for term in PURE_AI_TITLE_TERMS)
    if pure_ai_title:
        risks.append("서버·앱 개발보다 모델링·학습·평가 전문성이 중심인 직무")
        return 45.0, "순수 모델 AI", risks, 62
    ai_engineering_title = any(
        term in title for term in AI_ENGINEERING_TITLE_TERMS
    ) or _has_ai_title_signal(title)
    if ai_engineering_title:
        if any(term in title for term in ("ai owner", "ai 기획", "ai 전략")):
            risks.append("소프트웨어 구현보다 AI 제품 기획·전략 오너십이 중심인 직무")
            return 35.0, "AI 기획·전략", risks, 50
        if model_training and not substantial_backend_delivery:
            risks.append("서버 구현보다 모델 학습·평가·연구가 중심인 직무")
            return 45.0, "순수 모델 AI", risks, 62
        if model_specialist and not substantial_backend_delivery:
            risks.append("서버 구현보다 프롬프트·OCR·모델 추론 운영이 중심인 직무")
            return 45.0, "AI 모델·추론 전담", risks, 62
        if backend_delivery:
            return 80.0, "AI 활용 서버·앱", risks, cap
        risks.append("AI 구현 직무이나 서버·앱·인프라 책임 범위가 공고에서 불명확함")
        return 58.0, "AI 역할 방향 불명확", risks, 68
    if any(term in title for term in ("system engineer", "서버 관리자", "시스템 관리자")):
        return 45.0, "시스템 운영", ["애플리케이션 백엔드 개발보다 시스템 운영 비중이 큼"], 62
    return 62.0, "일반 개발 직군", ["직무 제목만으로 백엔드 중심 역할인지 불명확함"], None


def _refined_role_score(
    base: float,
    role_label: str,
    job: JobPosting,
    required_skills: list[str],
    statuses: dict[str, str],
) -> float:
    title = _normalized(job.title)
    task_text = _normalized("\n".join(job.main_tasks or []))
    core_required = [
        skill for skill in required_skills if _normalized(skill) in BACKEND_CORE_SKILLS
    ]
    strong_core = sum(statuses.get(skill) == "strong" for skill in core_required)
    explicit_backend = sum(
        term in title for term in ("backend", "back end", "백엔드", "server", "서버")
    )
    task_signals = sum(
        term in task_text
        for term in ("api", "backend", "백엔드", "서버", "database", "데이터베이스")
    )
    adjustment = min(2.4, explicit_backend * 1.2) + min(2.4, task_signals * 0.4)
    if core_required:
        adjustment += min(2.0, strong_core / len(core_required) * 2.0)
    if role_label in {"모델 학습 AI", "모델 연구·학습 AI", "모바일 앱", "교육·강사"}:
        adjustment = min(0.0, adjustment)
    return _clamp(base + adjustment)


def _responsibility_assessment(
    job: JobPosting,
    profile_data: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
    lines = [*(job.main_tasks or []), *(job.requirements or [])]
    text = _normalized("\n".join(lines))
    profile_text = _profile_corpus(profile_data)
    scores: list[float] = []
    weights: list[float] = []
    matched_labels: list[str] = []
    evidence: list[str] = []
    for terms, label, weight in RESPONSIBILITY_SIGNALS:
        if any(_normalized(term) in text for term in terms):
            profile_hits = sum(
                bool(_normalized(term) and _normalized(term) in profile_text) for term in terms
            )
            if label == "모델 학습" and profile_hits == 0:
                score = 16.0
            elif profile_hits:
                score = min(98.0, 84.0 + min(10.0, profile_hits * 2.5))
            else:
                score = 42.0
            scores.append(score)
            weights.append(weight)
            matched_labels.append(label)
            for line in lines:
                if any(_normalized(term) in _normalized(line) for term in terms):
                    evidence.append(f"공고 업무: {line}")
                    break
    if not scores:
        fallback = 52.0 + min(9.0, len(job.main_tasks or []) * 1.5)
        return fallback, [], ["주요업무에서 이력서와 직접 비교할 책임 범위를 찾지 못함"]
    weighted_score = sum(score * weight for score, weight in zip(scores, weights, strict=True))
    return weighted_score / sum(weights), matched_labels, evidence[:5]


def _coverage_score(skills: list[str], statuses: dict[str, str], default: float) -> float:
    if not skills:
        return default
    return sum(STATUS_POINTS[statuses[skill]] for skill in skills) / len(skills)


def score_jobs(
    session: Session,
    *,
    job_ids: set[int] | None = None,
    skip_existing: bool = False,
) -> int:
    """Score selected jobs without mutating earlier score snapshots by default callers.

    Most crawls pass newly-created posting IDs with ``skip_existing=True``. Sources that gain
    richer metadata can pass all rows seen in the current run with ``skip_existing=False`` so
    existing score snapshots are replaced with the newly available evidence.
    """
    profile = session.scalar(select(CandidateProfile).order_by(CandidateProfile.id).limit(1))
    if profile is None:
        raise ValueError("candidate profile is not seeded")

    profile_data = profile.profile_json
    known = _profile_skills(profile_data)
    limited = {_normalized(value) for value in profile_data["skill_gaps"]["limited"]}
    no_experience = {
        _normalized(value) for value in profile_data["skill_gaps"]["no_professional_experience"]
    }
    none = {_normalized(value) for value in profile_data["skill_gaps"]["none"]}
    years = int(profile_data["years_experience"])
    scored = 0

    jobs_statement = select(JobPosting)
    if job_ids is not None:
        if not job_ids:
            return 0
        jobs_statement = jobs_statement.where(JobPosting.id.in_(job_ids))

    for job in session.scalars(jobs_statement):
        decision = assess_relevance(
            job.title,
            job.description_text or "",
            job.experience_text,
            job.employment_type,
        )
        source_verified_development_role = _is_jobplanet_development_role(
            job, decision.reasons
        )
        if source_verified_development_role:
            check = job.availability_check or {}
            if (
                check.get("status") == "closed"
                or check.get("reason") == "previously_inactive_not_reopened"
                or (job.deadline_at is not None and job.deadline_at < datetime.now(UTC))
            ):
                job.is_active = False
            # Role/fit evidence never reopens an inactive job, even without a prior check.
            # Fresh collection through persistence is responsible for recruitment state.
        existing = session.scalar(
            select(JobScore).where(
                JobScore.job_posting_id == job.id,
                JobScore.candidate_profile_id == profile.id,
            )
        )
        if (
            existing is not None
            and skip_existing
            and existing.scoring_version == SCORING_VERSION
        ):
            _exclude_low_fit_jobplanet(job, existing.total_fit_score)
            continue
        if not decision.included and not source_verified_development_role:
            job.is_active = False
            if existing is not None:
                existing.total_fit_score = 0
                existing.application_value_score = 0
                existing.application_probability_score = 0
                existing.grade = "Excluded"
                existing.priority = 0
                existing.matching_reasons = []
                existing.missing_skills = []
                existing.risk_notes = ["Python·TypeScript·AI·Server·Backend 대상 직무가 아님"]
                existing.evidence_json = {"excluded_reasons": list(decision.reasons)}
                existing.scored_at = datetime.now(UTC)
                existing.scoring_version = SCORING_VERSION
            scored += 1
            continue

        base_role_score, role_label, role_risks, role_cap = _role_assessment(job)
        base_experience_score, experience_risk = _experience_eligibility(job.experience_text, years)
        experience_score = _precise_experience_score(
            job.experience_text, years, base_experience_score
        )
        requirement_lines = job.requirements or []
        explicit_required_skills = _unique(extract_tech_stack("\n".join(requirement_lines)))
        explicit_required = bool(explicit_required_skills)
        inferred_required_skills = _unique(
            extract_tech_stack("\n".join([job.title, *(job.main_tasks or [])]))
        )
        required_skills = (
            explicit_required_skills if explicit_required else inferred_required_skills
        )
        preferred_skills = _unique(extract_tech_stack("\n".join(job.preferred_requirements or [])))
        contextual_skills = _unique(
            [
                *(job.tech_stack or []),
                *extract_tech_stack("\n".join([job.title, *(job.main_tasks or [])])),
            ]
        )
        contextual_skills = [
            skill
            for skill in contextual_skills
            if skill not in required_skills and skill not in preferred_skills
        ]
        all_skills = _unique([*required_skills, *preferred_skills, *contextual_skills])
        statuses = {
            skill: _skill_status(skill, known, limited, no_experience, none) for skill in all_skills
        }
        has_node_backend_experience = _has_node_backend_experience(profile_data)
        for skill in all_skills:
            normalized_skill = _normalized(skill)
            if normalized_skill not in NODE_BACKEND_SKILLS:
                continue
            if statuses[skill] == "strong":
                continue
            has_specific_experience = _profile_skill_years(profile_data, skill) > 0
            if has_specific_experience or has_node_backend_experience:
                statuses[skill] = "transferable"
        role_score = _refined_role_score(
            base_role_score, role_label, job, required_skills, statuses
        )
        required_weights = _skill_weights(
            required_skills,
            requirement_lines if explicit_required else [job.title, *(job.main_tasks or [])],
        )
        required_score = _weighted_coverage(
            required_skills,
            statuses,
            profile_data,
            required_weights,
            default=54.0,
        )
        preferred_weights = _skill_weights(preferred_skills, job.preferred_requirements or [])
        preferred_score = _weighted_coverage(
            preferred_skills,
            statuses,
            profile_data,
            preferred_weights,
            default=66.0,
        )
        contextual_score = _weighted_coverage(
            contextual_skills,
            statuses,
            profile_data,
            default=64.0,
        )
        adjacent_score = (
            preferred_score * 0.72 + contextual_score * 0.28
            if preferred_skills
            else contextual_score
        )
        responsibility_score, responsibility_labels, responsibility_evidence = (
            _responsibility_assessment(job, profile_data)
        )
        production_skills = [
            skill
            for skill in _unique([*required_skills, *contextual_skills])
            if _normalized(skill) in INFRA_SKILLS | DATABASE_SKILLS | {"kafka"}
        ]
        production_score = _weighted_coverage(
            production_skills,
            statuses,
            profile_data,
            {skill: required_weights.get(skill, 0.82) for skill in production_skills},
            default=67.0,
        )
        job_capability_text = _normalized(
            "\n".join(
                [
                    *(job.main_tasks or []),
                    *(job.requirements or []),
                    *(job.preferred_requirements or []),
                ]
            )
        )
        profile_text = _profile_corpus(profile_data)
        system_design_score, design_job_hits, design_profile_hits = _term_alignment(
            job_capability_text, profile_text, SYSTEM_DESIGN_TERMS, 67.0
        )
        ownership_score, ownership_job_hits, ownership_profile_hits = _term_alignment(
            job_capability_text, profile_text, OWNERSHIP_TERMS, 66.0
        )
        design_ownership_score = system_design_score * 0.58 + ownership_score * 0.42
        quality_alignment, quality_job_hits, quality_profile_hits = _term_alignment(
            job_capability_text, profile_text, QUALITY_TERMS, 68.0
        )
        collaboration_score, collaboration_job_hits, collaboration_profile_hits = _term_alignment(
            job_capability_text, profile_text, COLLABORATION_TERMS, 66.0
        )
        quality_score = quality_alignment * 0.68 + collaboration_score * 0.32
        evidence_score = _evidence_quality(job, explicit_required)
        hard_requirement_gaps = assess_hard_requirements(job.requirements or [], profile_data)
        hard_requirement_penalty = min(
            32.0, sum(float(gap["penalty"]) for gap in hard_requirement_gaps)
        )
        hard_requirement_cap = min(
            (int(gap["cap"]) for gap in hard_requirement_gaps),
            default=None,
        )

        high_gaps = [skill for skill in required_skills if statuses[skill] in {"missing", "none"}]
        medium_gaps = [
            skill
            for skill in required_skills
            if statuses[skill] in {"transferable", "limited", "no_professional"}
        ]
        required_weight_total = sum(required_weights.values()) or 1.0
        high_gap_weight = sum(required_weights.get(skill, 1.0) for skill in high_gaps)
        medium_gap_weight = sum(required_weights.get(skill, 1.0) for skill in medium_gaps)
        high_gap_ratio = high_gap_weight / required_weight_total if required_skills else 0.0
        medium_gap_ratio = medium_gap_weight / required_weight_total if required_skills else 0.0
        strict_high_gaps = [
            skill for skill in high_gaps if _strict_required_gap(skill, requirement_lines, statuses)
        ]
        gap_penalty = min(
            18.0,
            high_gap_ratio * 10.5 + medium_gap_ratio * 4.25 + max(0, len(high_gaps) - 1) * 0.65,
        )
        confidence = (
            "high"
            if evidence_score >= 76 and explicit_required and len(required_skills) >= 2
            else "medium"
            if evidence_score >= 50 or required_skills
            else "low"
        )
        confidence_penalty = {"high": 0.0, "medium": 1.25, "low": 3.5}[confidence]
        normalized_job_skills = {_normalized(skill) for skill in all_skills}
        node_job = bool(normalized_job_skills & NODE_BACKEND_SKILLS)
        go_job = bool(normalized_job_skills & GO_BACKEND_SKILLS)
        python_job = bool(normalized_job_skills & {"python", "django", "fastapi", "flask"})
        backend_share = estimate_backend_share(
            job.title,
            "\n".join(
                [
                    job.description_text or "",
                    *(job.main_tasks or []),
                    *(job.requirements or []),
                ]
            ),
        )
        node_required_years = _skill_required_years(requirement_lines, NODE_BACKEND_SKILLS)
        node_professional_years = max(
            (_profile_skill_years(profile_data, skill) for skill in NODE_BACKEND_SKILLS),
            default=0.0,
        )
        go_required_years = _skill_required_years(requirement_lines, GO_BACKEND_SKILLS)
        go_professional_years = _profile_skill_years(profile_data, "go")
        java_spring_required = _requires_java_spring(requirement_lines)
        transition_bonus = 0.0
        if node_job and has_node_backend_experience and backend_share >= 50:
            transition_bonus += 3.0
        if node_job and python_job and has_node_backend_experience:
            transition_bonus += 2.0
        if node_job and node_required_years is not None and 1 <= node_required_years <= 3:
            if years >= 5 and has_node_backend_experience:
                transition_bonus += 2.0
        career_direction_penalty = 18.0 if java_spring_required else 0.0
        long_node_requirement_gap = bool(
            node_required_years is not None
            and node_required_years >= 5
            and node_professional_years < node_required_years
        )
        if long_node_requirement_gap:
            career_direction_penalty += 16.0
        long_go_requirement_gap = bool(
            go_required_years is not None
            and go_required_years >= 3
            and go_professional_years < go_required_years
        )
        if long_go_requirement_gap:
            career_direction_penalty += 16.0
        raw_fit = (
            role_score * 0.18
            + required_score * 0.22
            + adjacent_score * 0.08
            + experience_score * 0.12
            + responsibility_score * 0.14
            + production_score * 0.09
            + design_ownership_score * 0.07
            + quality_score * 0.05
            + evidence_score * 0.05
            - gap_penalty
            - confidence_penalty
            - hard_requirement_penalty
            + transition_bonus
            - career_direction_penalty
        )

        caps: list[str] = []
        maximum = 98.5
        if role_cap is not None:
            maximum = min(maximum, float(role_cap))
            caps.append(f"직무 방향({role_label}) 상한 {role_cap}점")
        if hard_requirement_cap is not None:
            maximum = min(maximum, float(hard_requirement_cap))
            caps.append(f"미확인 필수 자격 상한 {hard_requirement_cap}점")
        if strict_high_gaps:
            technical_gap_cap = (
                68 if high_gap_ratio >= 0.5 else 72 if len(strict_high_gaps) >= 2 else 78
            )
            maximum = min(maximum, float(technical_gap_cap))
            caps.append(f"미확인 필수 기술 {len(strict_high_gaps)}개 상한 {technical_gap_cap}점")
        if java_spring_required:
            maximum = min(maximum, 58.0)
            caps.append("Java·Spring 필수 조건 상한 58점")
        if long_node_requirement_gap:
            maximum = min(maximum, 58.0)
            caps.append(
                f"Node.js·TypeScript 계열 실무 {node_required_years}년 필수 조건 상한 58점"
            )
        if long_go_requirement_gap:
            maximum = min(maximum, 58.0)
            caps.append(f"Go 실무 {go_required_years}년 필수 조건 상한 58점")
        strong_required = sum(statuses[skill] == "strong" for skill in required_skills)
        strong_ratio = strong_required / len(required_skills) if required_skills else 0.0
        total = round(_clamp(min(maximum, raw_fit), maximum=98.5), 2)

        strategic_value = _clamp(
            role_score * 0.68 + responsibility_score * 0.20 + production_score * 0.12
        )
        optional_skills = _unique([*preferred_skills, *contextual_skills])
        optional_growth_ratio = (
            sum(
                statuses[skill] in {"limited", "no_professional", "missing"}
                for skill in optional_skills
            )
            / len(optional_skills)
            if optional_skills
            else 0.25
        )
        growth_value = _clamp(
            61.0
            + optional_growth_ratio * 16.0
            + min(7.0, design_ownership_score / 100.0 * 7.0)
            - high_gap_ratio * 24.0
        )
        application_value = round(
            min(
                96.0,
                58.0
                if java_spring_required
                or long_node_requirement_gap
                or long_go_requirement_gap
                else 96.0,
                float(hard_requirement_cap + 3) if hard_requirement_cap is not None else 96.0,
                total * 0.62 + strategic_value * 0.23 + growth_value * 0.10 + evidence_score * 0.05,
            ),
            2,
        )
        probability = round(
            min(
                58.0
                if java_spring_required
                or long_node_requirement_gap
                or long_go_requirement_gap
                else 96.0,
                _clamp(
                    total * 0.42
                    + required_score * 0.28
                    + experience_score * 0.20
                    + evidence_score * 0.10
                    - high_gap_ratio * 6.0
                    - sum(
                        10.0 if gap["severity"] == "high" else 4.0
                        for gap in hard_requirement_gaps
                    ),
                    maximum=96.0,
                ),
            ),
            2,
        )
        grade = "S" if total >= 88 else "A" if total >= 76 else "B" if total >= 63 else "C"
        recommendation_grade = (
            "비추천"
            if java_spring_required
            or long_node_requirement_gap
            or long_go_requirement_gap
            or total < 58
            else "최우선"
            if total >= 82
            else "추천"
            if total >= 70
            else "도전 지원"
        )
        if not node_job:
            transition_possibility = "해당 없음 · Python 및 공통 백엔드 역량으로 평가"
        elif long_node_requirement_gap:
            transition_possibility = (
                f"낮음 · Node.js·TypeScript 계열 실무 {node_required_years}년 필수 조건"
            )
        elif has_node_backend_experience and backend_share >= 60:
            transition_possibility = (
                f"높음 · 약 {years}년의 전체 백엔드 역량과 Node.js·TypeScript 실무를 함께 활용"
            )
        else:
            transition_possibility = "보통 · API·DB·AWS 경험은 이전 가능하나 직접 실무 근거 확인 필요"
        if not go_job:
            go_transition_possibility = "해당 없음 · 공고의 핵심 기술에 Go가 없음"
        elif long_go_requirement_gap:
            go_transition_possibility = f"낮음 · Go 실무 {go_required_years}년 필수 조건"
        elif go_professional_years > 0:
            go_transition_possibility = (
                f"높음 · Go 실무 약 {go_professional_years:g}년과 공통 백엔드 역량을 함께 활용"
            )
        else:
            go_transition_possibility = (
                "보통 · API·DB·AWS 운영 역량은 이전 가능하지만 Go 실무와 "
                "고루틴·context·동시성 안전성 근거가 필요"
            )
        java_spring_present = bool(normalized_job_skills & JAVA_SPRING_SKILLS)
        java_spring_status = (
            "필수"
            if java_spring_required
            else "일부 포함 · 필수 아님"
            if java_spring_present
            else "아님"
        )
        if (
            role_label in {"제품·풀스택", "Technical PO·Product Builder"}
            and backend_share < 75
        ):
            resume_type = "프로덕트 엔지니어 이력서"
        elif node_job:
            resume_type = "Python·TypeScript 백엔드 이력서"
        else:
            resume_type = "Python 백엔드 이력서"
        recommendation_reasons = [
            (
                f"총 {years}년의 백엔드 경력과 공고의 {role_label} 역할을 함께 비교해 "
                f"적합도 {total:.1f}점으로 평가했습니다."
            ),
            (
                f"API·데이터베이스·클라우드·배포 등 운영 역량 점수는 "
                f"{production_score:.1f}점이며 백엔드 업무 비중은 약 {backend_share}%입니다."
            ),
        ]
        if node_job:
            recommendation_reasons.append(
                str(
                    profile_data.get("node_transition_evidence")
                    or (
                        "Node.js·TypeScript 실무 경험과 Python 백엔드에서 쌓은 API 설계, "
                        "데이터 모델링, AWS, 배포, 테스트, 장애 대응 역량을 이전할 수 있습니다."
                    )
                )
            )
        if go_job:
            recommendation_reasons.append(go_transition_possibility)
        if java_spring_required or long_node_requirement_gap or long_go_requirement_gap:
            recommendation_reasons.append(
                "특정 언어·프레임워크 필수 연차가 현재 직접 실무 범위를 넘어 낮게 평가했습니다."
            )
        career_fit = {
            "recommendation_grade": recommendation_grade,
            "matching_experience": [
                skill
                for skill in all_skills
                if statuses.get(skill) in {"strong", "transferable", "limited"}
            ][:8],
            "risks": [],
            "node_typescript_transition": transition_possibility,
            "go_transition": go_transition_possibility,
            "backend_work_share": backend_share,
            "backend_work_share_label": (
                "높음" if backend_share >= 70 else "보통" if backend_share >= 50 else "낮음"
            ),
            "java_spring_required": java_spring_required,
            "java_spring_status": java_spring_status,
            "recommendation_reasons": recommendation_reasons[:4],
            "resume_type": resume_type,
            "node_required_years": node_required_years,
            "node_professional_years": node_professional_years,
            "go_required_years": go_required_years,
            "go_professional_years": go_professional_years,
            "transition_bonus": transition_bonus,
            "career_direction_penalty": career_direction_penalty,
        }
        role_job_evidence = [f"공고 제목: {job.title}", *responsibility_evidence[:2]]
        role_profile_evidence = [f"프로필 요약: {profile_data.get('summary', '')}"]
        matching_reasons = [
            {
                "skill": f"직무 방향 · {role_label}",
                "strength": "strong" if role_score >= 85 else "partial",
                "profile_evidence": role_profile_evidence,
                "job_evidence": role_job_evidence,
            }
        ]
        for skill in all_skills:
            if statuses[skill] not in {
                "strong",
                "transferable",
                "limited",
                "no_professional",
            }:
                continue
            profile_skill_evidence = _profile_evidence(skill, profile_data)
            if statuses[skill] == "transferable" and not profile_skill_evidence:
                profile_skill_evidence = [
                    "Node.js·TypeScript 실무와 API·DB·AWS·배포 경험에서 이전 가능한 역량"
                ]
            matching_reasons.append(
                {
                    "skill": skill,
                    "strength": "strong" if statuses[skill] == "strong" else "partial",
                    "profile_evidence": profile_skill_evidence,
                    "job_evidence": _job_evidence(skill, job),
                }
            )
            if len(matching_reasons) >= 9:
                break
        if experience_score >= 85 and job.experience_text:
            matching_reasons.append(
                {
                    "skill": "경력 조건",
                    "strength": "strong",
                    "profile_evidence": [f"이력서 총 경력: {years}년"],
                    "job_evidence": [f"공고 경력 조건: {job.experience_text}"],
                }
            )

        missing_skills = []
        for skill in required_skills:
            status = statuses[skill]
            if status == "strong":
                continue
            severity = "high" if status in {"missing", "none"} else "medium"
            note = {
                "none": "이력서에 경험 없음으로 명시된 필수 기술",
                "missing": "이력서에서 확인되지 않는 필수 기술",
                "no_professional": "개인·학습 경험은 있으나 실무 경험이 없는 필수 기술",
                "limited": "이력서에 제한적 경험으로 표시된 필수 기술",
                "transferable": "직접 실무 연차는 짧지만 전체 백엔드 경력으로 이전 가능한 기술",
            }[status]
            missing_skills.append(
                {
                    "skill": skill,
                    "severity": severity,
                    "profile_note": note,
                    "job_evidence": _job_evidence(skill, job),
                }
            )
        for gap in hard_requirement_gaps:
            missing_skills.append(
                {
                    "skill": gap["skill"],
                    "severity": gap["severity"],
                    "profile_note": "이력서에서 확인되지 않는 필수 자격·도메인 경험",
                    "job_evidence": [f"자격요건: {gap['requirement']}"],
                }
            )

        resume_recommendation = build_resume_recommendation(
            job,
            profile_data,
            fit_score=total,
            missing_skills=missing_skills,
        )
        recommended = str(resume_recommendation["recommended_id"])

        risks = [*role_risks]
        if experience_risk:
            risks.append(experience_risk)
        if not explicit_required:
            risks.append(
                "자격요건에서 필수 기술을 직접 추출하지 못해 제목·주요업무 기반 추론으로 계산함"
            )
        if evidence_score < 50:
            risks.append("공고의 자격요건·주요업무 구조화 근거가 적어 세부 비교 신뢰도가 낮음")
        if high_gaps:
            risks.append(f"필수 기술 큰 격차: {', '.join(high_gaps)}")
        if medium_gaps:
            risks.append(f"필수 기술 부분 경험: {', '.join(medium_gaps)}")
        if hard_requirement_gaps:
            risks.append(
                "필수 자격·도메인 격차: "
                + ", ".join(str(gap["skill"]) for gap in hard_requirement_gaps)
            )
        if java_spring_present and not java_spring_required:
            risks.append("Java·Spring이 일부 포함되지만 필수 조건은 아니므로 전환 위험으로만 표시")
        if long_node_requirement_gap:
            risks.append(
                f"Node.js·TypeScript 계열 실무 {node_required_years}년 이상을 필수로 요구"
            )
        if long_go_requirement_gap:
            risks.append(f"Go 실무 {go_required_years}년 이상을 필수로 요구")
        risks.extend(caps)
        career_fit["risks"] = _unique(risks)[:8]

        achievement_evidence = [
            f"성과/{item.get('company', '프로젝트')}: {item.get('evidence', '')}"
            for item in profile_data.get("achievements", [])[:3]
        ]
        quality_profile_evidence = [
            f"이력서 기술/quality: {skill}"
            for skill in profile_data.get("skills", {}).get("quality", [])[:5]
        ]
        production_profile_evidence = _unique(
            [
                evidence
                for skill in production_skills[:5]
                for evidence in _profile_evidence(skill, profile_data)
            ]
        )[:5]
        required_origin = "자격요건 직접 추출" if explicit_required else "제목·주요업무 추론"
        breakdown = [
            {
                "label": "직무 방향",
                "score": role_score,
                "weight": 18,
                "reason": f"현재 경력의 중심인 Python 백엔드와 {role_label} 역할의 거리",
                "profile_evidence": role_profile_evidence,
                "job_evidence": [f"공고 제목: {job.title}"],
            },
            {
                "label": "필수 기술 충족",
                "score": required_score,
                "weight": 22,
                "reason": f"{required_origin} 기술 {len(required_skills)}개 중 강점 {strong_required}개, 부분 {len(medium_gaps)}개, 큰 격차 {len(high_gaps)}개",
                "profile_evidence": [
                    f"기술별 보유 상태와 실제 성과 근거 깊이를 함께 비교 ({confidence} 신뢰도)"
                ],
                "job_evidence": [
                    f"{required_origin}: {', '.join(required_skills) or '추출 기술 없음'}"
                ],
            },
            {
                "label": "우대·인접 기술",
                "score": adjacent_score,
                "weight": 8,
                "reason": f"우대 {len(preferred_skills)}개와 업무·태그 기술 {len(contextual_skills)}개의 보유 수준",
                "profile_evidence": ["강점·제한 경험을 구분해 선택 기술의 가중 평균을 계산"],
                "job_evidence": [
                    f"우대: {', '.join(preferred_skills) or '명시 없음'}",
                    f"업무·태그: {', '.join(contextual_skills) or '명시 없음'}",
                ],
            },
            {
                "label": "경력 조건",
                "score": experience_score,
                "weight": 12,
                "reason": experience_risk or "요구 경력 범위 안에서 구간 중심과의 거리까지 반영",
                "profile_evidence": [f"이력서 총 경력: {years}년"],
                "job_evidence": [f"공고 경력 조건: {job.experience_text or '미기재'}"],
            },
            {
                "label": "업무 경험 근거",
                "score": responsibility_score,
                "weight": 14,
                "reason": f"주요업무와 연결된 이력서 경험: {', '.join(responsibility_labels) or '직접 근거 부족'}",
                "profile_evidence": achievement_evidence,
                "job_evidence": responsibility_evidence,
            },
            {
                "label": "운영·데이터 역량",
                "score": production_score,
                "weight": 9,
                "reason": "DB·클라우드·컨테이너·메시징 요구를 기술별 실무 근거와 비교",
                "profile_evidence": production_profile_evidence
                or ["직접 비교할 운영 기술 근거 없음"],
                "job_evidence": [
                    f"운영 관련 기술: {', '.join(production_skills) or '별도 명시 없음'}"
                ],
            },
            {
                "label": "설계·오너십",
                "score": design_ownership_score,
                "weight": 7,
                "reason": f"설계 요구 {design_job_hits}개/이력서 근거 {design_profile_hits}개 · 오너십 요구 {ownership_job_hits}개/이력서 근거 {ownership_profile_hits}개",
                "profile_evidence": achievement_evidence or ["성과 근거 미기재"],
                "job_evidence": ["공고의 아키텍처·확장성·주도성 표현을 문장 단위로 비교"],
            },
            {
                "label": "품질·협업",
                "score": quality_score,
                "weight": 5,
                "reason": f"품질 요구 {quality_job_hits}개/근거 {quality_profile_hits}개 · 협업 요구 {collaboration_job_hits}개/근거 {collaboration_profile_hits}개",
                "profile_evidence": quality_profile_evidence or ["품질 기술 근거 미기재"],
                "job_evidence": ["테스트·리뷰·협업 관련 표현을 공고에서 비교"],
            },
            {
                "label": "공고 근거 품질",
                "score": evidence_score,
                "weight": 5,
                "reason": f"자격요건 {len(job.requirements or [])}개 · 주요업무 {len(job.main_tasks or [])}개 · 기술태그 {len(job.tech_stack or [])}개 구조화",
                "profile_evidence": ["근거가 적은 공고가 높은 점수를 받지 않도록 신뢰도 보정"],
                "job_evidence": [f"분석 신뢰도: {confidence}"],
            },
            {
                "label": "핵심 격차 감점",
                "score": gap_penalty,
                "weight": -1,
                "reason": f"필수 중요도 기준 큰 격차 {high_gap_ratio * 100:.1f}% · 부분 경험 {medium_gap_ratio * 100:.1f}%",
                "profile_evidence": [f"큰 격차: {', '.join(high_gaps) or '없음'}"],
                "job_evidence": [f"부분 경험: {', '.join(medium_gaps) or '없음'}"],
            },
            {
                "label": "필수 자격·도메인 격차",
                "score": hard_requirement_penalty,
                "weight": -1,
                "reason": (f"명시된 필수 자격·도메인 경험 미확인 {len(hard_requirement_gaps)}개"),
                "profile_evidence": ["이력서의 자격·도메인 경험 명시 여부를 비교"],
                "job_evidence": [
                    f"자격요건: {gap['requirement']}" for gap in hard_requirement_gaps[:5]
                ]
                or ["별도 격차 없음"],
            },
            {
                "label": "근거 신뢰도 보정",
                "score": confidence_penalty,
                "weight": -1,
                "reason": f"{confidence} 신뢰도에 따른 보정 ({confidence_penalty:.2f}점)",
                "profile_evidence": ["후보자 프로필의 기술·성과 구조화 상태"],
                "job_evidence": [f"공고 근거 품질 {evidence_score:.1f}/100"],
            },
        ]
        values = {
            "eligibility_score": experience_score,
            "backend_score": _weighted_coverage(
                [s for s in required_skills if _normalized(s) in BACKEND_CORE_SKILLS],
                statuses,
                profile_data,
                required_weights,
                role_score,
            ),
            "database_score": _weighted_coverage(
                [s for s in all_skills if _normalized(s) in DATABASE_SKILLS],
                statuses,
                profile_data,
                default=67.0,
            ),
            "system_design_score": system_design_score,
            "infra_score": production_score,
            "messaging_score": _weighted_coverage(
                [s for s in all_skills if _normalized(s) == "kafka"],
                statuses,
                profile_data,
                default=67.0,
            ),
            "quality_score": quality_score,
            "ai_product_score": _weighted_coverage(
                [s for s in all_skills if _normalized(s) in AI_SKILLS],
                statuses,
                profile_data,
                default=64.0,
            ),
            "product_ownership_score": ownership_score,
            "collaboration_score": collaboration_score,
            "domain_score": role_score,
            "salary_career_score": strategic_value,
            "skill_gap_score": _clamp(100.0 - high_gap_ratio * 78.0 - medium_gap_ratio * 38.0),
            "total_fit_score": total,
            "application_value_score": application_value,
            "application_probability_score": probability,
            "grade": grade,
            "priority": round(total),
            "matching_reasons": matching_reasons,
            "missing_skills": missing_skills,
            "risk_notes": _unique(risks),
            "evidence_json": {
                "required_skills": required_skills,
                "required_skill_origin": "explicit" if explicit_required else "inferred",
                "required_skill_weights": required_weights,
                "preferred_skills": preferred_skills,
                "contextual_skills": contextual_skills,
                "skill_statuses": statuses,
                "hard_requirement_gaps": hard_requirement_gaps,
                "score_breakdown": breakdown,
                "formula": "직무 18% + 필수기술 22% + 우대·인접기술 8% + 경력 12% + 업무근거 14% + 운영·데이터 9% + 설계·오너십 7% + 품질·협업 5% + 공고근거 5% + Python↔Node 전환 보정 - 필수자격·Node/Go 특정언어 연차·기술격차·신뢰도 감점",
                "score_summary": f"{role_label} · 필수기술 {required_score:.1f}점 · 필수자격 격차 {len(hard_requirement_gaps)}개 · 업무근거 {responsibility_score:.1f}점 · 경력 {experience_score:.1f}점 · {confidence} 신뢰도",
                "confidence": confidence,
                "caps_applied": caps,
                "rank_factors": {
                    "required_strong_ratio": round(strong_ratio, 4),
                    "high_gap_ratio": round(high_gap_ratio, 4),
                    "strict_required_gaps": strict_high_gaps,
                    "hard_requirement_gap_count": len(hard_requirement_gaps),
                    "high_hard_requirement_gap_count": sum(
                        gap["severity"] == "high" for gap in hard_requirement_gaps
                    ),
                    "evidence_quality": round(evidence_score, 2),
                    "responsibility_evidence": round(responsibility_score, 2),
                    "strategic_value": round(strategic_value, 2),
                    "growth_value": round(growth_value, 2),
                },
                "resume_recommendation": resume_recommendation,
                "career_fit": career_fit,
                "definitions": {
                    "fit": "현재 이력서로 공고의 역할·필수기술·필수자격·경력·업무를 수행할 수 있는 정도",
                    "value": "필수 자격 격차를 상한으로 반영한 적합도에 직무 방향·업무 확장성·공고 근거 품질을 더한 지원 우선순위",
                    "probability": "필수요건·필수자격·경력·공고 근거 충족도를 중심으로 추정한 서류 경쟁력",
                },
            },
            "labels": [job.source.name if job.source else "job", recommended, role_label],
            "recommended_resume_version": recommended,
            "scored_at": datetime.now(UTC),
            "scoring_version": SCORING_VERSION,
        }
        _exclude_low_fit_jobplanet(job, total)
        if existing is None:
            session.add(
                JobScore(
                    job_posting_id=job.id,
                    candidate_profile_id=profile.id,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        scored += 1
    session.flush()
    return scored
