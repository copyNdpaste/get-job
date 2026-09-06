import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.crawler.domain import CollectedJob
from app.crawler.job_provider_fetcher import collect_jobplanet_pages
from app.crawler.jobplanet_fetcher import JobPlanetApiClient
from app.crawler.persistence import persist_collected_jobs
from app.db.session import SessionLocal
from app.deduplication import refresh_duplicate_groups
from app.models import CandidateProfile, JobPosting, JobSource
from app.scoring import score_jobs

SOURCE_NAME = "jobplanet"


@dataclass(frozen=True, slots=True)
class JobPlanetSyncResult:
    found: int
    created: int
    updated: int
    unchanged: int
    analyzed: int
    duplicate_groups: int
    grouped_postings: int


class JobPlanetSyncPipeline:
    """Run one idempotent JobPlanet collection, persistence, and analysis cycle."""

    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: sessionmaker[Session] = SessionLocal,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def validate_prerequisites(self) -> None:
        with self.session_factory() as session:
            source = session.scalar(select(JobSource).where(JobSource.name == SOURCE_NAME))
            if source is None or not source.enabled:
                raise RuntimeError(
                    "jobplanet source가 없습니다. 먼저 python -m app.seed를 실행하세요."
                )
            profile_id = session.scalar(
                select(CandidateProfile.id).order_by(CandidateProfile.id).limit(1)
            )
            if profile_id is None:
                raise RuntimeError(
                    "후보자 프로필이 없습니다. 먼저 python -m app.seed를 실행하세요."
                )

    async def collect(self, *, max_jobs: int) -> list[CollectedJob]:
        return await collect_jobplanet_pages(
            JobPlanetApiClient(),
            max_jobs=max_jobs,
            delay_min_seconds=self.settings.crawler_delay_min_seconds,
        )

    def persist_and_analyze(
        self,
        jobs: list[CollectedJob],
        *,
        started_at: datetime,
    ) -> JobPlanetSyncResult:
        with self.session_factory.begin() as session:
            source_id = session.scalar(
                select(JobSource.id).where(
                    JobSource.name == SOURCE_NAME,
                    JobSource.enabled.is_(True),
                )
            )
            if source_id is None:
                raise RuntimeError(
                    "jobplanet source가 없습니다. 먼저 python -m app.seed를 실행하세요."
                )

            counts = persist_collected_jobs(session, SOURCE_NAME, jobs)
            collected_job_ids = set(
                session.scalars(
                    select(JobPosting.id).where(
                        JobPosting.source_id == source_id,
                        JobPosting.last_seen_at >= started_at,
                    )
                )
            )
            analyzed = score_jobs(
                session,
                job_ids=collected_job_ids,
                skip_existing=False,
            )
            duplicate_summary = refresh_duplicate_groups(session)

            return JobPlanetSyncResult(
                found=len(jobs),
                created=counts["created"],
                updated=counts["updated"],
                unchanged=counts["unchanged"],
                analyzed=analyzed,
                duplicate_groups=duplicate_summary.groups,
                grouped_postings=duplicate_summary.grouped_postings,
            )

    async def run(self, *, max_jobs: int) -> JobPlanetSyncResult:
        if max_jobs < 1:
            raise ValueError("max_jobs는 1 이상이어야 합니다.")

        self.validate_prerequisites()
        started_at = datetime.now(UTC)
        jobs = await self.collect(max_jobs=max_jobs)
        return self.persist_and_analyze(jobs, started_at=started_at)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobplanet-sync",
        description="잡플래닛 JSON API 공고를 수집·저장·분석합니다.",
    )
    parser.add_argument("--max-jobs", type=int, default=5_000)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    pipeline = JobPlanetSyncPipeline(get_settings())
    result = asyncio.run(pipeline.run(max_jobs=args.max_jobs))
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
