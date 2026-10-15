import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate import CandidateProfile

EXAMPLE_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent / "examples" / "candidate-profile.example.json"
)


def ensure_candidate_profile(session: Session) -> CandidateProfile:
    """Keep the database authoritative; seed synthetic data only on an empty database."""
    profile = session.scalar(select(CandidateProfile).order_by(CandidateProfile.id).limit(1))
    if profile is None:
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add(profile)
        session.flush()
    return profile


def save_candidate_profile(session: Session, payload: object) -> CandidateProfile:
    """Explicitly import a profile without persisting an intermediate file or logging its data."""
    validate_candidate_profile(payload)
    profile = ensure_candidate_profile(session)
    profile.profile_json = payload
    session.flush()
    return profile


def default_candidate_profile() -> dict[str, Any]:
    profile = json.loads(EXAMPLE_PROFILE_PATH.read_text(encoding="utf-8"))
    validate_candidate_profile(profile)
    return profile


def validate_candidate_profile(profile: object) -> None:
    if not isinstance(profile, dict):
        raise ValueError("candidate profile must be a JSON object")
    required = {"years_experience", "summary", "skills", "achievements", "skill_gaps"}
    missing = required - profile.keys()
    if missing:
        raise ValueError("candidate profile is missing required fields")
    if not isinstance(profile["skills"], dict) or not isinstance(profile["skill_gaps"], dict):
        raise ValueError("candidate profile skills and skill_gaps must be objects")
