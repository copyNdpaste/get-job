import json
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings

EXAMPLE_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent / "examples" / "candidate-profile.example.json"
)


def load_candidate_profile(settings: Settings | None = None) -> tuple[dict[str, Any], bool]:
    resolved_settings = settings or get_settings()
    local_path = Path(resolved_settings.candidate_profile_path).expanduser()
    path = local_path if local_path.is_file() else EXAMPLE_PROFILE_PATH
    profile = json.loads(path.read_text(encoding="utf-8"))
    if path == local_path:
        direction_path = local_path.with_name("candidate-career-direction.local.json")
        if direction_path.is_file():
            direction = json.loads(direction_path.read_text(encoding="utf-8"))
            if not isinstance(direction, dict):
                raise ValueError(
                    f"candidate career direction must be a JSON object: {direction_path}"
                )
            profile.update(direction)
    _validate_profile(profile, path)
    return profile, path == local_path


def default_candidate_profile() -> dict[str, Any]:
    profile = json.loads(EXAMPLE_PROFILE_PATH.read_text(encoding="utf-8"))
    _validate_profile(profile, EXAMPLE_PROFILE_PATH)
    return profile


def _validate_profile(profile: object, path: Path) -> None:
    if not isinstance(profile, dict):
        raise ValueError(f"candidate profile must be a JSON object: {path}")
    required = {"years_experience", "summary", "skills", "achievements", "skill_gaps"}
    missing = required - profile.keys()
    if missing:
        raise ValueError(f"candidate profile is missing {', '.join(sorted(missing))}: {path}")
    if not isinstance(profile["skills"], dict) or not isinstance(profile["skill_gaps"], dict):
        raise ValueError(f"candidate profile skills and skill_gaps must be objects: {path}")
