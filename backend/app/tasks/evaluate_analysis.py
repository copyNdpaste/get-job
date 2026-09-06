"""Offline, synthetic routing evaluation. No model server or private profile is read."""

import asyncio
import json

from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.types import BigInteger

from app.analysis_pipeline import prepare_sources
from app.budget_analysis import run_budget_analysis
from app.config import Settings
from app.db.base import Base
from app.local_ai import AICompletion, AIStatus, LocalAIClient


@compiles(BigInteger, "sqlite")
def _sqlite_integer(_type, _compiler, **_kwargs):
    return "INTEGER"


class SyntheticClient(LocalAIClient):
    def __init__(self, settings, scenario):
        super().__init__(settings)
        self.scenario = scenario

    async def status(self, *, model=None):
        return AIStatus(True, True, "synthetic", model, model, [model], True, "offline fixture")

    async def complete(self, messages, *, model=None, **_kwargs):
        data = json.loads(messages[1]["content"].split("\n", 1)[1])
        status = "partial" if self.scenario == "ambiguous" and model == "small" else "supported"
        result = {
            "matches": [
                {
                    "requirement_id": item["id"],
                    "status": status,
                    "candidate_source_ids": list(data["candidate_sources"])[:1],
                    "explanation": "가상 평가 데이터의 근거 매칭입니다.",
                    "next_step": "경험을 확인하세요.",
                }
                for item in data["requirements"]["requirements"]
            ]
        }
        return AICompletion(json.dumps(result), model)


async def evaluate() -> dict:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        ai_provider="openai-compatible",
        ai_allow_remote=False,
        ai_base_url="http://localhost:1234",
        ai_analysis_daily_budget=200000,
    )
    scenarios = [
        "rules",
        "rules",
        "ordinary",
        "ordinary",
        "ordinary",
        "ordinary",
        "ambiguous",
        "ambiguous",
    ]
    counts = []
    outcomes = []
    with Session(engine) as session:
        for scenario in scenarios:
            candidate = (
                {"skills": {"languages": ["Python"]}}
                if scenario == "rules"
                else {
                    "summary": "Python API 개발 운영 경험",
                }
            )
            job = {"requirements": ["Python" if scenario == "rules" else "Python API 개발 경험"]}
            result = await run_budget_analysis(
                SyntheticClient(settings, scenario),
                session,
                settings,
                sources=prepare_sources(candidate, job),
                rule_scores={"fit": 70},
                fast_model="small",
                review_model="review",
            )
            counts.append(result.model_calls)
            outcomes.append(result.outcome)
    engine.dispose()
    return {
        "mode": "offline_scripted_outputs_not_model_quality",
        "cases": len(scenarios),
        "actual_provider_calls": 0,
        "pipeline_calls_by_case": counts,
        "pipeline_calls": sum(counts),
        "v1_two_call_baseline": len(scenarios) * 2,
        "routes_match_expected": counts == [0, 0, 1, 1, 1, 1, 2, 2],
        "outcomes": outcomes,
        "note": "Synthetic routing evaluation only; no real cost or semantic accuracy measured.",
    }


def main():
    print(json.dumps(asyncio.run(evaluate()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
