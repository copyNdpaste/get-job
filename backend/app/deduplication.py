import re
from collections import defaultdict
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.normalization import normalize_name
from app.experience import parse_experience
from app.models import Company, JobPosting, JobSource

APPLICATION_STATUS_PRIORITY = {
    "rejected": 9,
    "withdrawn": 8,
    "offer": 7,
    "interview": 6,
    "document_passed": 5,
    "applied": 4,
    "resume_preparing": 3,
    "interested": 2,
    "not_reviewed": 1,
}


@dataclass(frozen=True, slots=True)
class DeduplicationSummary:
    groups: int
    grouped_postings: int


_CORPORATE_MARKERS = re.compile(
    r"(?:\(\s*주\s*\)|㈜|주식회사|\(\s*유\s*\)|유한책임회사|유한회사)"
    r"|(?:\b(?:co\.?\s*,?\s*ltd\.?|inc\.?|corp(?:oration)?\.?|llc|ltd\.?)\b)",
    re.IGNORECASE,
)
_ENGLISH_BRAND_SUFFIX = re.compile(r"\(\s*[a-z][a-z0-9 .&+_-]{1,60}\s*\)", re.IGNORECASE)
_TITLE_NOISE = re.compile(
    r"(?:채용(?:합니다)?|모집(?:합니다)?|공고|정규직|계약직|경력직|경력|신입|상시|수시)"
    r"|(?:hiring|recruit(?:ing)?|position|opening|career)",
    re.IGNORECASE,
)
_TITLE_BRACKET_PREFIX = re.compile(r"^\s*(?:\[[^\]]{1,50}\]\s*)+")
_TITLE_TOKEN_ALIASES = (
    (re.compile(r"back\s*[- ]?\s*end|백\s*엔드|서버", re.IGNORECASE), " backend "),
    (re.compile(r"(?<![a-z])be(?![a-z])", re.IGNORECASE), " backend "),
    (re.compile(r"front\s*[- ]?\s*end|프론트\s*엔드", re.IGNORECASE), " frontend "),
    (re.compile(r"(?<![a-z])fe(?![a-z])", re.IGNORECASE), " frontend "),
    (re.compile(r"full\s*[- ]?\s*stack|풀\s*스택", re.IGNORECASE), " fullstack "),
    (re.compile(r"product\s*[- ]?\s*minded|프로덕트", re.IGNORECASE), " product "),
    (re.compile(r"platform|플랫폼", re.IGNORECASE), " platform "),
    (re.compile(r"data|데이터", re.IGNORECASE), " data "),
    (re.compile(r"infrastructure|인프라", re.IGNORECASE), " infra "),
    (re.compile(r"security|보안", re.IGNORECASE), " security "),
    (re.compile(r"mobile|모바일", re.IGNORECASE), " mobile "),
    (re.compile(r"embedded|임베디드", re.IGNORECASE), " embedded "),
    (re.compile(r"robotics|로보틱스|로봇", re.IGNORECASE), " robotics "),
    (re.compile(r"research|리서치|연구", re.IGNORECASE), " research "),
    (re.compile(r"application|애플리케이션|어플리케이션", re.IGNORECASE), " application "),
    (re.compile(r"machine\s*learning|머신러닝", re.IGNORECASE), " ml "),
    (re.compile(r"llm|gen\s*ai|생성형\s*ai", re.IGNORECASE), " ai "),
    (re.compile(r"데브옵스", re.IGNORECASE), " devops "),
    (re.compile(r"전문연(?:구요원)?", re.IGNORECASE), " 전문연구요원 "),
    (re.compile(r"developer|engineer|개발자|엔지니어|개발", re.IGNORECASE), " engineer "),
    (re.compile(r"node\s*\.?\s*js", re.IGNORECASE), " nodejs "),
    (re.compile(r"type\s*script", re.IGNORECASE), " typescript "),
    (re.compile(r"파이썬|python", re.IGNORECASE), " python "),
    (re.compile(r"golang|\bgo\b", re.IGNORECASE), " go "),
    (re.compile(r"nest\s*\.?\s*js", re.IGNORECASE), " nestjs "),
)
_ROLE_TOKENS = frozenset(
    {
        "backend",
        "fullstack",
        "product",
        "platform",
        "data",
        "ai",
        "ml",
        "infra",
        "devops",
        "sre",
        "security",
        "frontend",
        "mobile",
        "embedded",
        "robotics",
        "research",
        "application",
        "qa",
    }
)
_DISTINCT_ROLE_TOKENS = _ROLE_TOKENS
_STRONG_ROLE_TOKENS = _ROLE_TOKENS - {"ai", "ml", "research", "robotics"}
_SENIORITY_PATTERNS = {
    "entry": re.compile(
        r"신입|주니어|인턴|(?<![a-z])(?:junior|intern)(?![a-z])|entry\s*level",
        re.IGNORECASE,
    ),
    "senior": re.compile(r"시니어|(?<![a-z])senior(?![a-z])|수석|책임", re.IGNORECASE),
    "lead": re.compile(r"리드|팀장|파트장|(?<![a-z])lead(?![a-z])|principal|staff", re.IGNORECASE),
}


def _company_key(company: Company) -> str:
    """Normalize legal suffixes and bilingual brand annotations across job boards."""
    name = _CORPORATE_MARKERS.sub(" ", company.name)
    if re.search(r"[가-힣]", name):
        name = _ENGLISH_BRAND_SUFFIX.sub(" ", name)
    return normalize_name(name)


def _title_tokens(title: str) -> frozenset[str]:
    def tokenize(value: str) -> frozenset[str]:
        normalized = value.casefold()
        normalized = _TITLE_NOISE.sub(" ", normalized)
        for pattern, replacement in _TITLE_TOKEN_ALIASES:
            normalized = pattern.sub(replacement, normalized)
        return frozenset(re.findall(r"[0-9a-z가-힣+#.]+", normalized))

    tokens = tokenize(title)
    without_prefix = _TITLE_BRACKET_PREFIX.sub("", title)
    if without_prefix != title:
        prefixless_tokens = tokenize(without_prefix)
        if prefixless_tokens & _STRONG_ROLE_TOKENS:
            return prefixless_tokens
    return tokens


def _posting_title_tokens(posting: JobPosting) -> frozenset[str]:
    tokens = _title_tokens(posting.title)
    company_name = posting.company.name if posting.company is not None else ""
    company_names = {
        company_name,
        _CORPORATE_MARKERS.sub(" ", company_name).strip(),
    }
    for name in sorted(company_names, key=len, reverse=True):
        if not name:
            continue
        match = re.match(
            rf"^\s*{re.escape(name)}\s*[-–—:|]\s*(?P<title>.+)$",
            posting.title,
            re.IGNORECASE,
        )
        if match is None:
            continue
        prefixless_tokens = _title_tokens(match.group("title"))
        if prefixless_tokens & _STRONG_ROLE_TOKENS:
            return prefixless_tokens
    return tokens


def _seniority(title: str) -> frozenset[str]:
    return frozenset(
        label for label, pattern in _SENIORITY_PATTERNS.items() if pattern.search(title)
    )


def _experience_overlaps(left: JobPosting, right: JobPosting) -> bool:
    left_info = parse_experience(" ".join(filter(None, (left.title, left.experience_text))))
    right_info = parse_experience(" ".join(filter(None, (right.title, right.experience_text))))
    if not left_info.has_year_range or not right_info.has_year_range:
        return True
    left_min = left_info.minimum_years or 0
    right_min = right_info.minimum_years or 0
    if abs(left_min - right_min) > 2:
        return False
    left_max = left_info.maximum_years if left_info.maximum_years is not None else float("inf")
    right_max = (
        right_info.maximum_years if right_info.maximum_years is not None else float("inf")
    )
    return left_min <= right_max and right_min <= left_max


def _titles_are_similar(left: JobPosting, right: JobPosting) -> bool:
    left_tokens = _posting_title_tokens(left)
    right_tokens = _posting_title_tokens(right)
    if not left_tokens or not right_tokens:
        return False

    left_seniority = _seniority(left.title)
    right_seniority = _seniority(right.title)
    if left_seniority != right_seniority:
        return False
    if not _experience_overlaps(left, right):
        return False

    left_roles = left_tokens & _DISTINCT_ROLE_TOKENS
    right_roles = right_tokens & _DISTINCT_ROLE_TOKENS
    left_strong_roles = left_roles & _STRONG_ROLE_TOKENS
    right_strong_roles = right_roles & _STRONG_ROLE_TOKENS
    if bool(left_strong_roles) != bool(right_strong_roles):
        return False
    if left_strong_roles and left_strong_roles.isdisjoint(right_strong_roles):
        return False

    if left_tokens == right_tokens:
        return True
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return overlap >= 0.75 and len(left_tokens & right_tokens) >= 2


def _find_component(parents: list[int], index: int) -> int:
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    return index


def _union_components(parents: list[int], left_index: int, right_index: int) -> None:
    left_root = _find_component(parents, left_index)
    right_root = _find_component(parents, right_index)
    if left_root != right_root:
        parents[right_root] = left_root


def _components_can_merge(
    parents: list[int],
    members: list[tuple[JobPosting, JobSource]],
    left_index: int,
    right_index: int,
) -> bool:
    left_root = _find_component(parents, left_index)
    right_root = _find_component(parents, right_index)
    left_members = [
        posting
        for index, (posting, _source) in enumerate(members)
        if _find_component(parents, index) == left_root
    ]
    right_members = [
        posting
        for index, (posting, _source) in enumerate(members)
        if _find_component(parents, index) == right_root
    ]
    return all(_titles_are_similar(left, right) for left in left_members for right in right_members)


def _has_same_source_competitor(
    posting: JobPosting,
    source: JobSource,
    members: list[tuple[JobPosting, JobSource]],
) -> bool:
    posting_tokens = _posting_title_tokens(posting)
    return any(
        other.id != posting.id
        and other_source.name == source.name
        and _posting_title_tokens(other) != posting_tokens
        and _titles_are_similar(posting, other)
        for other, other_source in members
    )


def _primary_priority(posting: JobPosting) -> tuple[int, int, int, int, float, int]:
    application_priority = APPLICATION_STATUS_PRIORITY.get(
        posting.application.status if posting.application else "", 0
    )
    return (
        application_priority,
        int(posting.is_active),
        int(posting.is_favorite),
        len(posting.description_text or ""),
        posting.last_seen_at.timestamp(),
        -posting.id,
    )


def refresh_duplicate_groups(session: Session) -> DeduplicationSummary:
    """Group equivalent same-company positions exposed by multiple public sources."""
    rows = session.execute(
        select(JobPosting, Company, JobSource)
        .join(Company, Company.id == JobPosting.company_id)
        .join(JobSource, JobSource.id == JobPosting.source_id)
    ).all()
    candidates: dict[str, list[tuple[JobPosting, JobSource]]] = defaultdict(list)
    for posting, company, source in rows:
        posting.duplicate_group_id = None
        posting.is_primary_posting = True
        posting.duplicate_reason = None
        company_key = _company_key(company)
        if company_key and _posting_title_tokens(posting):
            candidates[company_key].append((posting, source))

    groups = 0
    grouped_postings = 0
    for company_key, members in candidates.items():
        if len(members) < 2:
            continue

        parents = list(range(len(members)))

        for left_index, (left, left_source) in enumerate(members):
            for right_index in range(left_index + 1, len(members)):
                right, right_source = members[right_index]
                if left_source.name == right_source.name:
                    continue
                exact_tokens = _posting_title_tokens(left) == _posting_title_tokens(right)
                if not exact_tokens and (
                    _has_same_source_competitor(left, left_source, members)
                    or _has_same_source_competitor(right, right_source, members)
                ):
                    continue
                if _titles_are_similar(left, right) and _components_can_merge(
                    parents, members, left_index, right_index
                ):
                    _union_components(parents, left_index, right_index)

        components: dict[int, list[tuple[JobPosting, JobSource]]] = defaultdict(list)
        for index, member in enumerate(members):
            components[_find_component(parents, index)].append(member)

        for component in components.values():
            sources = {source.name for _posting, source in component}
            if len(component) < 2 or len(sources) < 2:
                continue
            title_key = min(
                "".join(sorted(_posting_title_tokens(posting)))
                for posting, _ in component
            )
            group_id = uuid5(NAMESPACE_URL, f"get-job:{company_key}:{title_key}")
            primary = max((posting for posting, _source in component), key=_primary_priority)
            reason = "동일 회사 · 유사 포지션명·경력 조건 · 복수 공개 채용 소스"
            for posting, _source in component:
                posting.duplicate_group_id = group_id
                posting.is_primary_posting = posting.id == primary.id
                posting.duplicate_reason = reason
            groups += 1
            grouped_postings += len(component)

    session.flush()
    return DeduplicationSummary(groups=groups, grouped_postings=grouped_postings)
