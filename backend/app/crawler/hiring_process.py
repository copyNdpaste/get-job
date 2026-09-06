import re
from collections.abc import Iterable
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.crawler.normalization import normalize_text

PROCESS_SEPARATOR = re.compile(
    r"(?:\r?\n|[•·]+|\s*(?:→|⇒|➜|≫|▶|->|>)\s*|\s+[–—-]\s+|;\s*)"
)
CODING_TEST_PATTERN = re.compile(
    r"(?:코딩\s*(?:테스트|시험|과제)|코테|라이브\s*코딩|온라인\s*코딩|"
    r"coding\s*(?:test|challenge|assessment)|live\s*coding)",
    re.IGNORECASE,
)
NO_CODING_TEST_PATTERN = re.compile(
    r"(?:(?:코딩\s*(?:테스트|시험|과제)|코테)\s*(?:은|는)?\s*"
    r"(?:없음|미실시|생략|진행하지\s*않|보지\s*않)|"
    r"(?:코딩\s*(?:테스트|시험|과제)|코테)\s*없이)",
    re.IGNORECASE,
)
INTERVIEW_PATTERN = re.compile(r"(?:면접|인터뷰|interviews?)", re.IGNORECASE)
NO_INTERVIEW_PATTERN = re.compile(
    r"(?:(?:면접|인터뷰)\s*(?:은|는)?\s*"
    r"(?:없음|미실시|생략|진행하지\s*않|보지\s*않)|(?:면접|인터뷰)\s*없이)",
    re.IGNORECASE,
)
NUMBERED_INTERVIEW_PATTERNS = (
    re.compile(r"([1-9]\d*)\s*차[^→>\n]{0,30}?(?:면접|인터뷰)", re.IGNORECASE),
    re.compile(r"([1-9]\d*)(?:st|nd|rd|th)[^→>\n]{0,30}?interview", re.IGNORECASE),
)
INTERVIEW_COUNT_PATTERNS = (
    re.compile(
        r"(?:면접|인터뷰|interviews?)\s*(?:총\s*)?([1-9]\d*)\s*(?:회|차|rounds?)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:총\s*)?([1-9]\d*)\s*회(?:의)?\s*(?:면접|인터뷰)", re.IGNORECASE),
)
INTERVIEW_RANGE_PATTERN = re.compile(
    r"(?:면접|인터뷰|interviews?)[^0-9]{0,12}[1-9]\d*\s*[~\-–—]\s*([1-9]\d*)\s*(?:회|차|rounds?)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class HiringProcessInfo:
    steps: tuple[str, ...]
    has_coding_test: bool | None
    interview_count: int | None


def process_items_from_value(value: object) -> list[str]:
    """Flatten a source-specific process field without interpreting unrelated job text."""
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, dict):
        items: list[str] = []
        for nested in value.values():
            items.extend(process_items_from_value(nested))
        return items
    if isinstance(value, (list, tuple)):
        items = []
        for nested in value:
            items.extend(process_items_from_value(nested))
        return items
    if not isinstance(value, str):
        return []

    text = BeautifulSoup(value, "html.parser").get_text("\n", strip=True)
    return _normalize_steps([text])


def analyze_hiring_process(values: Iterable[str]) -> HiringProcessInfo:
    steps = _normalize_steps(values)
    if not steps:
        return HiringProcessInfo((), None, None)

    combined = " → ".join(steps)
    if NO_CODING_TEST_PATTERN.search(combined):
        has_coding_test: bool | None = False
    elif CODING_TEST_PATTERN.search(combined):
        has_coding_test = True
    else:
        has_coding_test = None

    if NO_INTERVIEW_PATTERN.search(combined):
        interview_count: int | None = 0
    elif INTERVIEW_PATTERN.search(combined):
        explicit_counts: list[int] = []
        for pattern in (*NUMBERED_INTERVIEW_PATTERNS, *INTERVIEW_COUNT_PATTERNS):
            explicit_counts.extend(int(match) for match in pattern.findall(combined))
        explicit_counts.extend(int(match) for match in INTERVIEW_RANGE_PATTERN.findall(combined))
        step_count = sum(
            1
            for step in steps
            if INTERVIEW_PATTERN.search(step) and not NO_INTERVIEW_PATTERN.search(step)
        )
        interview_count = min(10, max([step_count, *explicit_counts, 1]))
    else:
        interview_count = None

    return HiringProcessInfo(tuple(steps), has_coding_test, interview_count)


def _normalize_steps(values: Iterable[str]) -> list[str]:
    steps: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        for part in PROCESS_SEPARATOR.split(value):
            cleaned = re.sub(r"^\s*(?:step\s*)?\d+\s*[.)]\s*", "", part, flags=re.IGNORECASE)
            cleaned = normalize_text(re.sub(r"^[\s•·-]+", "", cleaned))[:300]
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            steps.append(cleaned)
            if len(steps) >= 30:
                return steps
    return steps
