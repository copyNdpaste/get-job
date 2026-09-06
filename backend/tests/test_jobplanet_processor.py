from typing import Any

from app.crawler.jobplanet_processor import JobDataProcessor, JobPlanetProcessor


def test_legacy_processor_name_points_to_jobplanet_processor() -> None:
    assert JobDataProcessor is JobPlanetProcessor


def test_jobplanet_payload_is_transformed_to_internal_format() -> None:
    raw_data: dict[str, Any] = {
        "data": {
            "postings": [
                {
                    "id": 12345,
                    "title": "  Python   Backend Engineer  ",
                    "company": {"name": " 예시 테크 ", "rate": "4.2"},
                    "location": " 서울  강남구 ",
                }
            ]
        }
    }

    jobs = JobDataProcessor().process_raw_payload(raw_data)

    assert jobs == [
        {
            "job_id": 12345,
            "title": "Python Backend Engineer",
            "company_name": "예시 테크",
            "company_rating": 4.2,
            "location": "서울 강남구",
            "job_url": "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=12345",
        }
    ]


def test_live_jobplanet_recruits_envelope_is_transformed() -> None:
    raw_data: dict[str, Any] = {
        "status": "success",
        "code": 200,
        "data": {
            "total_count": 1,
            "recruits": [
                {
                    "id": 9876,
                    "title": "  Platform   Backend Engineer ",
                    "company": {
                        "name": " Synthetic Platform ",
                        "grade": "4.6",
                        "city_name": "서울",
                    },
                    "cities": ["서울", "경기"],
                }
            ],
        },
    }

    jobs = JobPlanetProcessor().process_raw_payload(raw_data)

    assert jobs == [
        {
            "job_id": 9876,
            "title": "Platform Backend Engineer",
            "company_name": "Synthetic Platform",
            "company_rating": 4.6,
            "location": "서울, 경기",
            "job_url": "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=9876",
        }
    ]


def test_jobplanet_payload_is_null_safe() -> None:
    raw_data: dict[str, Any] = {
        "data": {
            "postings": [
                {
                    "id": None,
                    "title": None,
                    "company": None,
                    "location": None,
                },
                {
                    "id": "posting-2",
                    "company": {"name": None, "rate": "not-a-number"},
                },
            ]
        }
    }

    jobs = JobDataProcessor().process_raw_payload(raw_data)

    assert jobs == [
        {
            "job_id": "",
            "title": "",
            "company_name": "",
            "company_rating": 0.0,
            "location": "",
            "job_url": "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=",
        },
        {
            "job_id": "posting-2",
            "title": "",
            "company_name": "",
            "company_rating": 0.0,
            "location": "",
            "job_url": (
                "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=posting-2"
            ),
        },
    ]


def test_jobplanet_payload_ignores_invalid_container_values() -> None:
    processor = JobDataProcessor()

    assert processor.process_raw_payload({}) == []
    assert processor.process_raw_payload({"data": None}) == []
    assert processor.process_raw_payload({"data": {"postings": None}}) == []
    assert processor.process_raw_payload({"data": {"postings": [None, "invalid"]}}) == []


def test_jobplanet_rating_rejects_boolean_and_non_finite_values() -> None:
    raw_data: dict[str, Any] = {
        "data": {
            "postings": [
                {"id": 1, "company": {"rate": True}},
                {"id": 2, "company": {"rate": "NaN"}},
                {"id": 3, "company": {"rate": None}},
            ]
        }
    }

    jobs = JobDataProcessor().process_raw_payload(raw_data)

    assert [job["company_rating"] for job in jobs] == [0.0, 0.0, 0.0]
