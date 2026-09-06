import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PUBLIC_API_ATS = {"greenhouse", "lever", "ashby"}
PUBLIC_BOARD_ATS = {"greeting", "ninehire"}
DIRECT_ATS_SOURCES = tuple(sorted(PUBLIC_API_ATS | PUBLIC_BOARD_ATS))


@dataclass(frozen=True, slots=True)
class DirectAtsBoard:
    source_name: str
    company_name: str
    board_key: str
    board_url: str


# Public company career boards only. This catalog intentionally contains no candidate data.
# A local ignored JSON file can extend it without repeating crawler code.
DEFAULT_DIRECT_ATS_BOARDS = (
    DirectAtsBoard(
        "greenhouse",
        "Speechify",
        "speechify",
        "https://job-boards.greenhouse.io/speechify",
    ),
    DirectAtsBoard(
        "greenhouse",
        "MarqVision",
        "marqvision",
        "https://job-boards.greenhouse.io/marqvision",
    ),
    DirectAtsBoard(
        "greenhouse",
        "LG AI Research",
        "lgairesearch",
        "https://job-boards.greenhouse.io/lgairesearch",
    ),
    DirectAtsBoard(
        "lever",
        "Channel Corp.",
        "zoyi",
        "https://jobs.lever.co/zoyi",
    ),
    DirectAtsBoard(
        "lever",
        "Match Group",
        "matchgroup",
        "https://jobs.lever.co/matchgroup",
    ),
    DirectAtsBoard(
        "lever",
        "Sendbird",
        "sendbird",
        "https://jobs.lever.co/sendbird",
    ),
    DirectAtsBoard(
        "ashby",
        "Cheiron",
        "Cheiron",
        "https://jobs.ashbyhq.com/Cheiron",
    ),
    DirectAtsBoard(
        "ashby",
        "BJAK",
        "bjakcareer",
        "https://jobs.ashbyhq.com/bjakcareer",
    ),
    DirectAtsBoard(
        "greeting",
        "Supercent",
        "supercent",
        "https://supercent.career.greetinghr.com/ko/position",
    ),
    DirectAtsBoard(
        "greeting",
        "Catenoid",
        "catenoid",
        "https://catenoid.career.greetinghr.com/ko/joblist",
    ),
    DirectAtsBoard(
        "greeting",
        "Echo Marketing",
        "echomarketing",
        "https://echomarketing.career.greetinghr.com/ko",
    ),
    DirectAtsBoard(
        "greeting",
        "KidariStudio/Lezhin",
        "kstd-lezhin",
        "https://kstd-lezhin.career.greetinghr.com/ko",
    ),
    DirectAtsBoard(
        "ninehire",
        "Specter",
        "specter",
        "https://specter.ninehire.site/recruit",
    ),
    DirectAtsBoard(
        "ninehire",
        "PiaSpace",
        "piaspace",
        "https://piaspace.ninehire.site/recruit",
    ),
    DirectAtsBoard(
        "ninehire",
        "ConnectWave",
        "connectwave",
        "https://connectwave.ninehire.site/",
    ),
    DirectAtsBoard(
        "ninehire",
        "KakaoStyle",
        "kakaostyle",
        "https://kakaostyle.ninehire.site/",
    ),
    DirectAtsBoard(
        "ninehire",
        "Fastlane",
        "fastlane",
        "https://fastlane.ninehire.site/job_posting",
    ),
)


def _validate_board(board: DirectAtsBoard) -> DirectAtsBoard:
    if board.source_name not in DIRECT_ATS_SOURCES:
        raise ValueError(f"unsupported direct ATS source: {board.source_name}")
    if not 1 <= len(board.company_name.strip()) <= 200:
        raise ValueError("direct ATS company name must be 1-200 characters")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", board.board_key):
        raise ValueError("direct ATS board key contains unsupported characters")

    parts = urlsplit(board.board_url)
    expected_hosts = {
        "greenhouse": "job-boards.greenhouse.io",
        "lever": "jobs.lever.co",
        "ashby": "jobs.ashbyhq.com",
    }
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in {None, 443}:
        raise ValueError("direct ATS board URL must be credential-free HTTPS")
    hostname = (parts.hostname or "").casefold()
    if board.source_name in expected_hosts:
        if hostname != expected_hosts[board.source_name]:
            raise ValueError(f"invalid {board.source_name} board hostname")
    elif board.source_name == "greeting":
        if not re.fullmatch(r"[a-z0-9-]+\.career\.greetinghr\.com", hostname):
            raise ValueError("invalid Greeting board hostname")
    elif not re.fullmatch(r"[a-z0-9-]+\.ninehire\.site", hostname):
        raise ValueError("invalid Ninehire board hostname")
    if len(parts.path) > 300 or parts.query or parts.fragment:
        raise ValueError("direct ATS board URL has an unsupported path or query")
    return board


def load_direct_ats_boards(local_path: str | None = None) -> tuple[DirectAtsBoard, ...]:
    boards = list(DEFAULT_DIRECT_ATS_BOARDS)
    if local_path:
        path = Path(local_path)
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, list) or len(payload) > 200:
                raise ValueError("direct ATS board file must contain at most 200 entries")
            for item in payload:
                if not isinstance(item, dict):
                    raise ValueError("direct ATS board entries must be objects")
                boards.append(
                    DirectAtsBoard(
                        source_name=str(item.get("source_name") or "").strip().casefold(),
                        company_name=str(item.get("company_name") or "").strip(),
                        board_key=str(item.get("board_key") or "").strip(),
                        board_url=str(item.get("board_url") or "").strip(),
                    )
                )

    deduplicated: dict[tuple[str, str], DirectAtsBoard] = {}
    for board in boards:
        validated = _validate_board(board)
        deduplicated[(validated.source_name, validated.board_key.casefold())] = validated
    return tuple(deduplicated.values())

