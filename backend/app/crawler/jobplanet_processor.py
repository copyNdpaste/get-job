import math
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

from app.crawler.normalization import normalize_text
from app.crawler.relevance import extract_tech_stack

JOBPLANET_JOB_URL_PREFIX = "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D="


def build_jobplanet_job_url(job_id: object) -> str:
    return f"{JOBPLANET_JOB_URL_PREFIX}{quote(str(job_id), safe='')}"


class JobPlanetProcessor:
    """Transform an already-collected JobPlanet payload into the internal format."""

    def __init__(self, config: dict[str, object] | None = None):
        self.config = config or {}

    def process_raw_payload(self, raw_data: dict[str, Any]) -> list[dict[str, object]]:
        data = raw_data.get("data") if isinstance(raw_data, dict) else None
        postings = self._postings(data)
        if not isinstance(postings, list):
            return []

        processed: list[dict[str, object]] = []
        for posting in postings:
            if not isinstance(posting, dict):
                continue

            company = posting.get("company")
            company_data = company if isinstance(company, dict) else {}
            job_id = self._job_id(posting.get("id"))
            rating = company_data.get("grade")
            if rating is None:
                rating = company_data.get("rate")
            title = self._text(posting.get("title"))
            location = self._location(posting, company_data)
            row: dict[str, object] = {
                "job_id": job_id,
                "title": title,
                "company_name": self._text(company_data.get("name")),
                "company_rating": self._rating(rating),
                "location": location,
                "job_url": build_jobplanet_job_url(job_id),
            }
            if self._has_analysis_metadata(posting):
                source_skills = self._string_list(posting.get("skills"))
                occupations = self._occupation_names(posting.get("occupation_names"))
                requirements = self._string_list(posting.get("recruitment_text"))
                experience_text = self._text(posting.get("career_text"))
                employment_type = self._text(posting.get("job_type"))
                description_text = normalize_text(
                    " ".join(
                        [
                            title,
                            *occupations,
                            *source_skills,
                            experience_text,
                            *requirements,
                            location,
                        ]
                    )
                )
                detected_skills = extract_tech_stack(description_text)
                row.update(
                    {
                        "description_text": description_text,
                        "tech_stack": self._unique_text(
                            [*detected_skills, *source_skills]
                        ),
                        "occupation_names": occupations,
                        "requirements": requirements,
                        "experience_text": experience_text,
                        "employment_type": employment_type,
                    }
                )
            processed.append(row)
        return processed

    @staticmethod
    def _has_analysis_metadata(posting: dict[str, Any]) -> bool:
        return any(
            key in posting
            for key in (
                "skills",
                "occupation_names",
                "recruitment_text",
                "career_text",
                "job_type",
            )
        )

    @classmethod
    def _string_list(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return cls._unique_text(cls._text(item) for item in value)

    @classmethod
    def _occupation_names(cls, value: object) -> list[str]:
        if not isinstance(value, dict):
            return []
        names: list[str] = []
        for level in ("level1", "level2"):
            names.extend(cls._string_list(value.get(level)))
        return cls._unique_text(names)

    @staticmethod
    def _unique_text(values: Iterable[object]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = normalize_text(str(value or ""))
            key = normalized.casefold()
            if normalized and key not in seen:
                seen.add(key)
                unique.append(normalized)
        return unique

    @staticmethod
    def _postings(data: object) -> object:
        if not isinstance(data, dict):
            return None
        recruits = data.get("recruits")
        if isinstance(recruits, list):
            return recruits
        return data.get("postings")

    @classmethod
    def _location(cls, posting: dict[str, Any], company: dict[str, Any]) -> str:
        cities = posting.get("cities")
        if isinstance(cities, list):
            names = [cls._text(city) for city in cities]
            normalized = [name for name in names if name]
            if normalized:
                return ", ".join(normalized)

        location = cls._text(posting.get("location"))
        if location:
            return location
        return cls._text(company.get("city_name"))

    @staticmethod
    def _job_id(value: object) -> str | int:
        if isinstance(value, bool) or value is None:
            return ""
        if isinstance(value, (str, int)):
            return value
        return normalize_text(str(value))

    @staticmethod
    def _text(value: object) -> str:
        return normalize_text(str(value or ""))

    @staticmethod
    def _rating(value: object) -> float:
        if value is None or isinstance(value, bool):
            return 0.0
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return 0.0
        return rating if math.isfinite(rating) else 0.0


# Preserve the legacy public name used by existing callers.
JobDataProcessor = JobPlanetProcessor
