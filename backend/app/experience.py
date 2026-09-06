import re
from dataclasses import dataclass

YEAR_PATTERN = re.compile(
    r"(?P<low>\d+)\s*(?:년\s*)?(?:(?:[-~–—])\s*(?P<high>\d+)\s*년|년)"
    r"\s*(?P<qualifier>이상|이하)?"
)


@dataclass(frozen=True)
class ExperienceInfo:
    categories: frozenset[str]
    minimum_years: int | None
    maximum_years: int | None
    has_year_range: bool


def parse_experience(text: str | None) -> ExperienceInfo:
    if not text:
        return ExperienceInfo(frozenset(), None, None, False)

    compact = re.sub(r"\s+", "", text)
    normalized = text.casefold()
    categories: set[str] = set()
    is_intern = "인턴" in compact or bool(
        re.search(r"(?<!\w)intern(?:ship)?(?!\w)", normalized)
    )
    no_experience = not is_intern and any(
        marker in compact for marker in ("경력무관", "경력전체", "경력제한없음", "연차무관")
    )
    if is_intern:
        categories.add("intern")
    elif "신입" in text:
        categories.add("entry")
    if no_experience:
        categories.add("no_experience")

    ranges: list[tuple[int, int | None]] = []
    for match in YEAR_PATTERN.finditer(text):
        low = int(match.group("low"))
        high_text = match.group("high")
        qualifier = match.group("qualifier")
        if high_text is not None:
            ranges.append((low, int(high_text)))
        elif qualifier == "이상":
            ranges.append((low, None))
        elif qualifier == "이하":
            ranges.append((0, low))
        else:
            ranges.append((low, low))

    if not is_intern and not no_experience and ("경력" in text or ranges):
        categories.add("career")

    if ranges:
        minimum_years = min(low for low, _high in ranges)
        maximum_years = (
            None
            if any(high is None for _low, high in ranges)
            else max(high for _low, high in ranges if high is not None)
        )
        return ExperienceInfo(frozenset(categories), minimum_years, maximum_years, True)

    if categories and categories.issubset({"intern", "entry"}):
        return ExperienceInfo(frozenset(categories), 0, 0, True)
    return ExperienceInfo(frozenset(categories), None, None, False)


def is_junior_only_role(
    title: str,
    experience_text: str | None,
    employment_type: str | None = None,
) -> bool:
    """Exclude only roles that cannot accept someone above three years of experience."""
    combined = " ".join(value for value in (title, experience_text, employment_type) if value)
    compact = re.sub(r"\s+", "", combined)
    info = parse_experience(combined)

    title_compact = re.sub(r"\s+", "", title)
    title_normalized = title.casefold()
    title_info = parse_experience(title)
    if (
        title_info.has_year_range
        and title_info.maximum_years is not None
        and title_info.maximum_years <= 3
    ):
        return True
    if "인턴" in title_compact and "경력" not in title_compact:
        return True
    if (
        "주니어" in title_compact
        and "미들" not in title_compact
        and "시니어" not in title_compact
    ):
        return True
    if (
        re.search(r"(?<![a-z])junior(?![a-z])", title_normalized)
        and not re.search(r"(?<![a-z])(?:mid|middle|senior)(?![a-z])", title_normalized)
    ):
        return True
    if "no_experience" in info.categories:
        return False
    if "신입" in compact and "경력" not in compact:
        return True
    return bool(
        info.has_year_range
        and info.maximum_years is not None
        and info.maximum_years <= 3
    )
