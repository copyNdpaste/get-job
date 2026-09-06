from app.crawler.browser_groupby import parse_groupby_api_detail


def test_groupby_api_detail_preserves_real_url_and_structured_sections() -> None:
    job = parse_groupby_api_detail(
        {
            "id": 11459,
            "name": "AI Backend Engineer",
            "careerType": "경력",
            "experienceRange": {"min": 3, "max": 10},
            "techStacks": ["Python", "Django", {"name": "PostgreSQL"}],
            "publishedAt": "2026-05-01T09:30:00",
            "dueDate": "2026-08-31T23:59:59+09:00",
            "task": "<ul><li>AI API 서버 개발</li><li>백엔드 운영</li></ul>",
            "qualification": "<p>Python 서비스 개발 경험</p>",
            "preferred": "<p>Django 운영 경험</p>",
            "hiringProcess": "<p>서류 - 코딩테스트 - 1차 인터뷰 - 2차 인터뷰</p>",
            "location": {"name": "서울 강남구"},
            "address": "테헤란로 1",
            "startup": {
                "id": 99,
                "name": "테스트 스타트업",
                "memberCount": 31,
                "devCount": 12,
                "fundingRound": "Series A",
                "keywords": ["유연근무", "교육비 지원"],
            },
        }
    )

    assert job.external_job_id == "11459"
    assert job.url == "https://groupby.kr/positions/11459"
    assert job.main_tasks == ["AI API 서버 개발", "백엔드 운영"]
    assert job.requirements == ["Python 서비스 개발 경험"]
    assert job.preferred_requirements == ["Django 운영 경험"]
    assert {"Python", "Django", "PostgreSQL"}.issubset(job.tech_stack)
    assert job.experience_text == "경력 3년 이상"
    assert job.hiring_process == ["서류", "코딩테스트", "1차 인터뷰", "2차 인터뷰"]
    assert job.has_coding_test is True
    assert job.interview_count == 2
    assert job.posted_at is not None
    assert job.deadline_at is not None
    assert job.company_facts is not None
    assert job.company_facts.employee_count == 31
    assert job.company_facts.developer_count == 12
    assert job.company_facts.investment_stage == "Series A"
