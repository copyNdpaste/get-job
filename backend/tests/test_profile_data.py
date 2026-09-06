import json

import pytest

from app.config import Settings
from app.profile_data import default_candidate_profile, load_candidate_profile


def test_default_profile_preserves_experience_and_skill_gaps() -> None:
    profile = default_candidate_profile()

    assert profile["years_experience"] == 4
    assert "Python" in profile["skills"]["backend"]
    assert "Kafka" in profile["skills"]["messaging"]
    assert "Go" in profile["skill_gaps"]["no_professional_experience"]
    assert "PyTorch" in profile["skill_gaps"]["none"]


def test_default_profile_has_all_resume_versions() -> None:
    assert default_candidate_profile()["resume_versions"] == [
        "backend",
        "backend_ai",
        "product_engineer",
    ]


def test_local_candidate_profile_overrides_anonymous_example(tmp_path) -> None:
    path = tmp_path / "candidate-profile.local.json"
    profile = default_candidate_profile()
    profile["summary"] = "local-only summary"
    path.write_text(json.dumps(profile), encoding="utf-8")

    loaded, is_local = load_candidate_profile(
        Settings(candidate_profile_path=str(path), ai_enabled=False)
    )

    assert is_local is True
    assert loaded["summary"] == "local-only summary"


def test_invalid_local_candidate_profile_is_rejected(tmp_path) -> None:
    path = tmp_path / "candidate-profile.local.json"
    path.write_text('{"summary": "missing fields"}', encoding="utf-8")

    with pytest.raises(ValueError, match="candidate profile is missing"):
        load_candidate_profile(Settings(candidate_profile_path=str(path), ai_enabled=False))


def test_local_career_direction_sidecar_extends_profile_without_tracking_it(tmp_path) -> None:
    path = tmp_path / "candidate-profile.local.json"
    direction_path = tmp_path / "candidate-career-direction.local.json"
    path.write_text(json.dumps(default_candidate_profile()), encoding="utf-8")
    direction_path.write_text(
        json.dumps(
            {
                "years_experience": 6,
                "skill_experience_years": {"Node.js": 1.5, "TypeScript": 1.5},
                "career_direction": {"primary_role": "backend"},
            }
        ),
        encoding="utf-8",
    )

    loaded, is_local = load_candidate_profile(
        Settings(candidate_profile_path=str(path), ai_enabled=False)
    )

    assert is_local is True
    assert loaded["years_experience"] == 6
    assert loaded["skill_experience_years"]["Node.js"] == 1.5
    assert loaded["career_direction"]["primary_role"] == "backend"
