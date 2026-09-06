import json

import pytest

from app.crawler.direct_ats import (
    _is_korea_target,
    parse_ashby_job,
    parse_greenhouse_job,
    parse_lever_job,
    parse_rendered_board_job,
    validate_ats_api_url,
    validate_ninehire_api_url,
)
from app.direct_ats_catalog import DirectAtsBoard, load_direct_ats_boards


def test_greenhouse_job_keeps_typescript_backend_content() -> None:
    board = DirectAtsBoard(
        "greenhouse",
        "Example Global",
        "exampleglobal",
        "https://job-boards.greenhouse.io/exampleglobal",
    )

    job = parse_greenhouse_job(
        board,
        {
            "id": 5974394004,
            "title": "Software Engineer, Platform - Seoul",
            "location": {"name": "Seoul, South Korea"},
            "updated_at": "2026-08-20T12:00:00Z",
            "content": """
                <h2>What You'll Do</h2><ul><li>Build backend APIs</li></ul>
                <h2>Requirements</h2><p>Production TypeScript and Node.js experience</p>
                <h2>Preferred</h2><p>AWS and Docker</p>
            """,
        },
    )

    assert job.url == "https://job-boards.greenhouse.io/exampleglobal/jobs/5974394004"
    assert {"TypeScript", "Node.js", "AWS", "Docker"}.issubset(job.tech_stack)
    assert "Build backend APIs" in job.main_tasks
    assert job.location == "Seoul, South Korea"


def test_lever_job_uses_only_configured_public_host() -> None:
    board = DirectAtsBoard(
        "lever", "Example", "example", "https://jobs.lever.co/example"
    )
    job = parse_lever_job(
        board,
        {
            "id": "fbe11a2f-63e3-4cae-b2e5-68f94886cb06",
            "text": "Software Engineer, Backend",
            "description": "Python and Node.js services on AWS",
            "categories": {
                "location": "Seoul, Korea",
                "commitment": "Full-time",
            },
            "lists": [
                {"text": "Responsibilities", "content": "<li>Design REST API services</li>"},
                {"text": "Requirements", "content": "<li>5+ years backend experience</li>"},
            ],
            "createdAt": 1_787_491_545_000,
        },
    )

    assert job.url.startswith("https://jobs.lever.co/example/")
    assert {"Python", "Node.js", "AWS", "REST API"}.issubset(job.tech_stack)
    assert job.posted_at is not None


def test_ashby_job_rejects_cross_board_urls() -> None:
    board = DirectAtsBoard(
        "ashby", "Example", "example", "https://jobs.ashbyhq.com/example"
    )
    payload = {
        "title": "Backend Engineer",
        "location": "Seoul, Korea",
        "descriptionHtml": "<p>Python FastAPI PostgreSQL</p>",
        "jobUrl": "https://evil.example/internal",
    }

    with pytest.raises(ValueError, match="configured public board"):
        parse_ashby_job(board, payload)


def test_rendered_ninehire_page_is_structured_and_allowlisted() -> None:
    board = DirectAtsBoard(
        "ninehire", "Example Korea", "example", "https://example.ninehire.site/recruit"
    )
    html = """
        <html><body><main>
          <h2>주요업무</h2><ul><li>Node.js API 개발</li></ul>
          <h2>자격요건</h2><p>백엔드 경력 5년 이상, TypeScript 경험</p>
          <h2>우대사항</h2><p>NestJS, AWS Lambda 경험</p>
        </main></body></html>
    """
    job = parse_rendered_board_job(
        "ninehire",
        board,
        title="Backend Engineer (5년 이상)",
        url="https://example.ninehire.site/job_posting/ABC123",
        html=html,
        metadata={"location": "서울", "experience_text": "경력 5년 이상"},
    )

    assert job.external_job_id == "ABC123"
    assert {"Node.js", "TypeScript", "NestJS", "AWS"}.issubset(job.tech_stack)
    assert job.requirements
    assert job.experience_text == "경력 5년 이상"


def test_direct_ats_api_and_local_catalog_reject_untrusted_hosts(tmp_path) -> None:
    assert validate_ats_api_url(
        "greenhouse",
        "https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true",
    )
    with pytest.raises(ValueError, match="exact public API host"):
        validate_ats_api_url(
            "greenhouse", "https://127.0.0.1/v1/boards/example/jobs?content=true"
        )

    path = tmp_path / "boards.json"
    path.write_text(
        json.dumps(
            [
                {
                    "source_name": "greeting",
                    "company_name": "Synthetic Company",
                    "board_key": "synthetic",
                    "board_url": "https://evil.example/jobs",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Greeting board hostname"):
        load_direct_ats_boards(str(path))


def test_foreign_office_is_not_mistaken_for_korea_from_boilerplate() -> None:
    description = "We also have a separate engineering team in Seoul, Korea."

    assert _is_korea_target("Los Altos, California", description) is False
    assert _is_korea_target("Seoul, Korea", description) is True


def test_ninehire_public_api_url_is_exactly_allowlisted() -> None:
    url = (
        "https://api.ninehire.com/identity-access/homepage/recruitments"
        "?companyId=6badd180-31e5-11ef-b0a9-4b228a36b17d&page=1"
    )
    assert validate_ninehire_api_url(url) == url
    with pytest.raises(ValueError, match="exact public recruitment endpoint"):
        validate_ninehire_api_url(
            "https://api.ninehire.com/identity-access/homepage/employments"
            "?companyId=6badd180-31e5-11ef-b0a9-4b228a36b17d"
        )
