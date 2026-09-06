from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.local_ai import AICompletion
from app.models import AIAnalysisDay, AIAnalysisUsage


class AnalysisBudgetExceeded(RuntimeError):
    pass


def reserve_call(
    session: Session, settings: Settings, *, model: str, stage: str, amount: int
) -> AIAnalysisUsage:
    """Commit the reservation BEFORE network I/O; a crash cannot erase spent budget."""
    now = datetime.now(UTC)
    insert = sqlite_insert if session.bind.dialect.name == "sqlite" else pg_insert
    session.execute(
        insert(AIAnalysisDay)
        .values(
            day=now.date(),
            reserved_tokens=0,
            calls=0,
            reviews=0,
        )
        .on_conflict_do_nothing(index_elements=["day"])
    )
    review = int(stage == "review")
    updated = session.execute(
        update(AIAnalysisDay)
        .where(
            AIAnalysisDay.day == now.date(),
            AIAnalysisDay.reserved_tokens + amount <= settings.ai_analysis_daily_budget,
            AIAnalysisDay.reviews + review <= settings.ai_analysis_daily_reviews,
        )
        .values(
            reserved_tokens=AIAnalysisDay.reserved_tokens + amount,
            calls=AIAnalysisDay.calls + 1,
            reviews=AIAnalysisDay.reviews + review,
        )
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        session.rollback()
        raise AnalysisBudgetExceeded("분석 예산 또는 재검토 횟수 한도에 도달했습니다.")
    usage = AIAnalysisUsage(
        created_at=now,
        model=model,
        provider=settings.ai_provider,
        stage=stage,
        status="reserved",
        reserved_tokens=amount,
    )
    session.add(usage)
    session.commit()
    return usage


def finish_call(
    session: Session, usage: AIAnalysisUsage, *, status: str, completion: AICompletion | None = None
) -> None:
    usage.status = status
    if completion is not None:
        usage.input_tokens = completion.input_tokens
        usage.output_tokens = completion.output_tokens
        actual = (completion.input_tokens or 0) + (completion.output_tokens or 0)
        if actual > usage.reserved_tokens:
            # Codex can include hidden harness/reasoning overhead. Account for overshoot
            # rather than pretending a planning reservation is a provider billing cap.
            session.execute(
                update(AIAnalysisDay)
                .where(
                    AIAnalysisDay.day == usage.created_at.date(),
                )
                .values(
                    reserved_tokens=AIAnalysisDay.reserved_tokens + actual - usage.reserved_tokens
                )
            )
            usage.reserved_tokens = actual
    session.commit()
