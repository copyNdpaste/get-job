from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import CandidateProfile
from app.profile_data import (
    default_candidate_profile,
    ensure_candidate_profile,
    save_candidate_profile,
    validate_candidate_profile,
)


@pytest.fixture
def profile_engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_default_profile_is_synthetic_and_preserves_required_fields() -> None:
    profile = default_candidate_profile()
    assert profile["years_experience"] == 4
    assert "Python" in profile["skills"]["backend"]
    assert "Go" in profile["skill_gaps"]["no_professional_experience"]
    assert profile["resume_versions"] == ["backend", "backend_ai", "product_engineer"]


def test_empty_database_gets_exactly_one_synthetic_profile(profile_engine) -> None:
    with Session(profile_engine) as session, session.begin():
        first = ensure_candidate_profile(session)
        second = ensure_candidate_profile(session)
        assert first.id == second.id
        assert first.profile_json == default_candidate_profile()


def test_existing_database_profile_is_never_replaced_or_loaded_from_files(
    profile_engine,
    monkeypatch,
) -> None:
    payload = default_candidate_profile()
    payload["summary"] = "synthetic custom summary"
    with Session(profile_engine) as session, session.begin():
        row = CandidateProfile(name="custom candidate", profile_json=payload)
        session.add(row)
        session.flush()
        profile_id = row.id

    def reject_file_read(*args, **kwargs):
        raise AssertionError("startup must not read candidate files")

    monkeypatch.setattr(Path, "read_text", reject_file_read)
    with Session(profile_engine) as session, session.begin():
        row = ensure_candidate_profile(session)
        assert row.id == profile_id
        assert row.profile_json == payload


def test_explicit_import_preserves_id_and_persists_direction(profile_engine) -> None:
    with Session(profile_engine) as session, session.begin():
        original_id = ensure_candidate_profile(session).id
    payload = default_candidate_profile()
    payload["summary"] = "synthetic imported summary"
    payload["career_direction"] = {"primary_role": "backend"}
    with Session(profile_engine) as session, session.begin():
        assert save_candidate_profile(session, payload).id == original_id
    with Session(profile_engine) as session:
        rows = list(session.scalars(select(CandidateProfile)))
        assert len(rows) == 1
        assert rows[0].profile_json == payload


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"summary": "synthetic"},
        {
            "summary": "synthetic",
            "years_experience": 1,
            "achievements": [],
            "skills": [],
            "skill_gaps": {},
        },
    ],
)
def test_invalid_import_does_not_modify_existing_profile(profile_engine, payload) -> None:
    with Session(profile_engine) as session, session.begin():
        original_id = ensure_candidate_profile(session).id
    with Session(profile_engine) as session, pytest.raises(ValueError):
        save_candidate_profile(session, payload)
    with Session(profile_engine) as session:
        stored = session.get(CandidateProfile, original_id)
        assert stored.profile_json == default_candidate_profile()


def test_validation_errors_do_not_echo_private_values() -> None:
    with pytest.raises(ValueError) as error:
        validate_candidate_profile({"summary": "synthetic-sensitive-marker"})
    assert "synthetic-sensitive-marker" not in str(error.value)
