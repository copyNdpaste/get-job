"""Import a private profile from standard input directly into the local database."""

import json
import sys

from app.db.session import SessionLocal
from app.profile_data import save_candidate_profile

MAX_PROFILE_BYTES = 1_000_000


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_PROFILE_BYTES + 1)
        if len(raw) > MAX_PROFILE_BYTES:
            raise ValueError("profile too large")
        payload = json.loads(raw)
        with SessionLocal.begin() as session:
            save_candidate_profile(session, payload)
    except Exception:
        # Exception messages and database parameters can contain the submitted profile.
        print("Profile import failed; no profile data was printed.", file=sys.stderr)
        return 1
    print("Profile saved to the local database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
