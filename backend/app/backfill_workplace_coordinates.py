"""Extract already collected public coordinates locally, without external geocoding."""

from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.job_locations import source_coordinates
from app.models import JobPosting, JobSource


def main() -> None:
    updated = 0
    cursor = 0
    while True:
        with SessionLocal.begin() as session:
            rows = session.execute(
                select(JobPosting.id, JobPosting.description_raw)
                .join(JobSource)
                .where(JobSource.name == "wanted", JobPosting.id > cursor)
                .order_by(JobPosting.id)
                .limit(100)
            ).all()
            if not rows:
                break
            for row in rows:
                point = source_coordinates("wanted", row.description_raw)
                session.execute(
                    update(JobPosting)
                    .where(JobPosting.id == row.id)
                    .values(workplace_coordinates=point)
                )
                updated += point is not None
            cursor = rows[-1].id
    print(f"Public workplace coordinates extracted: {updated}", flush=True)


if __name__ == "__main__":
    main()
