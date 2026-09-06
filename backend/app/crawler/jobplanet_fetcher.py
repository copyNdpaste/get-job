import math

import httpx

from app.crawler.job_provider_fetcher import ExternalJobFetcher
from app.crawler.jobplanet_processor import JobPlanetProcessor, build_jobplanet_job_url
from app.crawler.normalization import normalize_text

JOBPLANET_POSTINGS_ENDPOINT = "https://www.jobplanet.co.kr/api/v3/job/postings"
JOBPLANET_PUBLIC_SSR_HEADER = (
    "jobplanet_desktop_ssr_1d6f8a5f219176accbb8fe051729fc6a"
)
JOBPLANET_BACKEND_OCCUPATION_ID = "11904"
JOBPLANET_SOFTWARE_OCCUPATION_ID = "11607"
JOBPLANET_TARGET_OCCUPATION_IDS = (
    JOBPLANET_BACKEND_OCCUPATION_ID,
    JOBPLANET_SOFTWARE_OCCUPATION_ID,
)
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100


class JobPlanetApiClient:
    """Fetch and normalize JobPlanet REST API posting packets."""

    def __init__(
        self,
        *,
        timeout: float | httpx.Timeout = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
        processor: JobPlanetProcessor | None = None,
    ) -> None:
        self.base_url = JOBPLANET_POSTINGS_ENDPOINT
        self.processor = processor or JobPlanetProcessor()
        self.fetcher = ExternalJobFetcher(
            timeout=timeout,
            transport=transport,
            processor=self.processor,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "JP-OS-TYPE": "desktop_web",
                # Public, non-session client identifier emitted by JobPlanet's job page.
                # It is not a browser cookie or a user/login credential.
                "jp-ssr-auth": JOBPLANET_PUBLIC_SSR_HEADER,
                "User-Agent": "get-job/0.1 (+local personal job search)",
                "Referer": "https://www.jobplanet.co.kr/job",
            },
        )

    async def fetch_raw_postings(self, page: int = 1, per: int = DEFAULT_PER_PAGE) -> dict:
        """Fetch one raw JSON packet.

        Transport and status failures intentionally propagate as ``httpx.HTTPError``
        subclasses; an empty response and a failed request are not interchangeable.
        """
        self._validate_pagination(page, per)
        return await self.fetcher.fetch_raw_data(
            self.base_url,
            {
                "occupation_level1": "",
                "occupation_level2": ",".join(JOBPLANET_TARGET_OCCUPATION_IDS),
                "years_of_experience": "",
                "review_score": "",
                "job_type": "",
                "city": "",
                "education_level_id": "",
                "order_by": "recent",
                "page": page,
                "page_size": per,
            },
        )

    def parse_postings(self, raw_json: dict) -> list[dict[str, object]]:
        """Convert a raw packet into null-safe standard job dictionaries."""
        rows = self.processor.process_raw_payload(raw_json)
        jobs: list[dict[str, object]] = []
        for row in rows:
            job_id = normalize_text(str(row.get("job_id") or ""))
            if not job_id:
                continue
            job: dict[str, object] = {
                "job_id": job_id,
                "title": normalize_text(str(row.get("title") or "")),
                "company_name": normalize_text(str(row.get("company_name") or "")),
                "company_rating": self._rating(row.get("company_rating")),
                "location": normalize_text(str(row.get("location") or "")),
                "job_url": build_jobplanet_job_url(job_id),
            }
            for field in (
                "description_text",
                "tech_stack",
                "occupation_names",
                "requirements",
                "experience_text",
                "employment_type",
            ):
                if field in row:
                    job[field] = row[field]
            jobs.append(job)
        return jobs

    async def get_jobs(
        self,
        page: int = 1,
        per: int = DEFAULT_PER_PAGE,
    ) -> list[dict[str, object]]:
        """Fetch and normalize one page for the downstream persistence pipeline."""
        raw_data = await self.fetch_raw_postings(page=page, per=per)
        return self.parse_postings(raw_data)

    @staticmethod
    def _validate_pagination(page: int, per: int) -> None:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("page must be a positive integer")
        if (
            isinstance(per, bool)
            or not isinstance(per, int)
            or not 1 <= per <= MAX_PER_PAGE
        ):
            raise ValueError(f"per must be an integer between 1 and {MAX_PER_PAGE}")

    @staticmethod
    def _rating(value: object) -> float:
        if value is None or isinstance(value, bool):
            return 0.0
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return 0.0
        return rating if math.isfinite(rating) else 0.0
