from app.hard_requirements import assess_hard_requirements


def _backend_profile() -> dict:
    return {
        "summary": "Python 백엔드 서비스 개발자",
        "years_experience": 6,
        "skills": {
            "backend": ["Python", "Django", "MySQL"],
            "infra": ["AWS", "Docker"],
        },
        "achievements": [{"evidence": "Python API 서비스와 AWS 배포 파이프라인 개발"}],
        "skill_gaps": {"none": [], "no_professional_experience": []},
    }


def test_braindive_like_requirements_detect_unverified_hard_qualifications() -> None:
    requirements = [
        "클라우드 환경에서 보안 실무 또는 백엔드 개발 경험 5년 이상",
        "ISMS-P 또는 ISO27001 등 보안 인증의 실제 심사 대응 경험",
        "NCP 또는 AWS 환경의 VPC 및 보안 설정 운영 경험",
        "Python으로 서비스 로직이나 관리 도구를 개발할 수 있는 분",
        "RDB(MySQL 등) 설계 및 보안 관리 경험",
    ]

    gaps = assess_hard_requirements(requirements, _backend_profile())
    keys = {gap["key"] for gap in gaps}

    assert keys >= {
        "security_certification",
        "security_audit",
        "cloud_network_security",
    }
    security_operations_gap = next(gap for gap in gaps if gap["key"] == "security_operations")
    assert security_operations_gap["requirement"].startswith("RDB")


def test_explicit_security_evidence_satisfies_hard_qualification_rules() -> None:
    profile = _backend_profile()
    profile["achievements"].append(
        {"evidence": ("ISMS-P 심사 대응, AWS VPC·IAM 보안 설정 운영, 보안 감사 대응을 수행")}
    )
    requirements = [
        "ISMS-P 인증 심사 대응 경험",
        "AWS VPC 및 IAM 보안 설정 운영 경험",
    ]

    assert assess_hard_requirements(requirements, profile) == []


def test_equivalent_experience_avoids_false_education_gap() -> None:
    gaps = assess_hard_requirements(
        ["컴퓨터공학 학사 또는 이에 준하는 실무 경험"],
        _backend_profile(),
    )

    assert gaps == []


def test_generic_ai_agent_skill_does_not_satisfy_agent_runtime_requirement() -> None:
    profile = _backend_profile()
    profile["skills"]["ai"] = ["AI Agent", "LLM"]

    gaps = assess_hard_requirements(
        ["agent runtime, harness, tool calling, sandboxing, memory를 직접 만들어본 경험"],
        profile,
    )

    assert {gap["key"] for gap in gaps} == {"agent_runtime"}
