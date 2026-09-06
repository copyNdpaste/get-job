from datetime import UTC, datetime

from sqlalchemy import select, update

from app.config import get_settings
from app.db.session import SessionLocal
from app.deduplication import refresh_duplicate_groups
from app.ecosystem_catalog import DEFAULT_ECOSYSTEM_ORGANIZATIONS
from app.models import CandidateProfile, EcosystemOrganization, JobPosting, JobSource
from app.profile_data import load_candidate_profile
from app.scoring import score_jobs
from app.source_catalog import DEFAULT_JOB_SOURCES


def seed() -> None:
    profile_data, loaded_from_local_file = load_candidate_profile(get_settings())
    with SessionLocal.begin() as session:
        for definition in DEFAULT_JOB_SOURCES:
            source = session.scalar(select(JobSource).where(JobSource.name == definition.name))
            if source is None:
                session.add(
                    JobSource(
                        name=definition.name,
                        base_url=definition.base_url,
                        crawler_type=definition.crawler_type,
                    )
                )
            else:
                source.base_url = definition.base_url
                source.crawler_type = definition.crawler_type

        for definition in DEFAULT_ECOSYSTEM_ORGANIZATIONS:
            organization = session.scalar(
                select(EcosystemOrganization).where(EcosystemOrganization.slug == definition.slug)
            )
            if organization is None:
                session.add(
                    EcosystemOrganization(
                        slug=definition.slug,
                        name=definition.name,
                        organization_type=definition.organization_type,
                        summary=definition.summary,
                        website_url=definition.website_url,
                        program_url=definition.program_url,
                        fit_score=definition.fit_score,
                        fit_reason=definition.fit_reason,
                        focus_tags=list(definition.focus_tags),
                        source_url=definition.source_url,
                        operating_scale=definition.operating_scale,
                    )
                )
            else:
                organization.name = definition.name
                organization.organization_type = definition.organization_type
                organization.summary = definition.summary
                organization.website_url = definition.website_url
                organization.program_url = definition.program_url
                organization.fit_score = definition.fit_score
                organization.fit_reason = definition.fit_reason
                organization.focus_tags = list(definition.focus_tags)
                organization.source_url = definition.source_url
                organization.operating_scale = definition.operating_scale

        profile = session.scalar(
            select(CandidateProfile).where(CandidateProfile.name == "기본 후보자")
        )
        if profile is None:
            session.add(CandidateProfile(name="기본 후보자", profile_json=profile_data))
        elif loaded_from_local_file:
            profile.profile_json = profile_data
        session.execute(
            update(JobPosting)
            .where(
                JobPosting.is_active.is_(True),
                JobPosting.deadline_at.is_not(None),
                JobPosting.deadline_at < datetime.now(UTC),
            )
            .values(is_active=False)
        )
        session.flush()
        # Seed only rows that have never received a score; recurring crawler runs must not
        # overwrite previously stored analyses.
        score_jobs(session, skip_existing=True)
        # Low-fit JobPlanet rows are deactivated while scoring, so choose duplicate primaries
        # only after that visibility policy has been applied.
        refresh_duplicate_groups(session)


if __name__ == "__main__":
    seed()
