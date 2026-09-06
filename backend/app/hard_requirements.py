import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HardRequirementRule:
    key: str
    label: str
    job_patterns: tuple[str, ...]
    profile_patterns: tuple[str, ...]
    severity: str
    penalty: float
    cap: int
    needs_experience_context: bool = False


RULES: tuple[HardRequirementRule, ...] = (
    HardRequirementRule(
        "security_certification",
        "보안 인증 실무(ISMS-P·ISO27001·CSAP·KCMVP 등)",
        (
            r"\bisms(?: p)?\b",
            r"\biso ?27001\b",
            r"\bcsap\b",
            r"\bkcmvp\b",
            r"\bpci(?: dss)?\b",
            r"\bsoc ?2\b",
        ),
        (
            r"\bisms(?: p)?\b",
            r"\biso ?27001\b",
            r"\bcsap\b",
            r"\bkcmvp\b",
            r"\bpci(?: dss)?\b",
            r"\bsoc ?2\b",
        ),
        "high",
        18.0,
        62,
    ),
    HardRequirementRule(
        "security_audit",
        "보안 인증·감사 심사 대응",
        (r"심사 대응", r"인증 대응", r"보안 감사", r"security audit", r"audit 대응"),
        (r"심사 대응", r"인증 대응", r"보안 감사", r"security audit", r"audit 대응"),
        "high",
        15.0,
        65,
    ),
    HardRequirementRule(
        "cloud_network_security",
        "클라우드 네트워크·보안 설정 운영",
        (
            r"\bvpc\b",
            r"\biam\b",
            r"security group",
            r"네트워크 보안",
            r"보안 설정",
            r"방화벽",
            r"\bwaf\b",
        ),
        (
            r"\bvpc\b",
            r"\biam\b",
            r"security group",
            r"네트워크 보안",
            r"보안 설정",
            r"방화벽",
            r"\bwaf\b",
        ),
        "high",
        12.0,
        69,
        True,
    ),
    HardRequirementRule(
        "security_operations",
        "보안 실무·운영",
        (
            r"보안 실무",
            r"보안 운영",
            r"보안 관리",
            r"취약점",
            r"침해 대응",
            r"security operation",
            r"security engineer",
        ),
        (
            r"보안 실무",
            r"보안 운영",
            r"보안 관리",
            r"취약점",
            r"침해 대응",
            r"security operation",
            r"security engineer",
        ),
        "high",
        12.0,
        69,
        True,
    ),
    HardRequirementRule(
        "public_domain",
        "공공·정부 서비스 도메인 경험",
        (r"공공", r"정부", r"조달", r"나라장터"),
        (r"공공", r"정부", r"조달", r"나라장터"),
        "high",
        9.0,
        72,
        True,
    ),
    HardRequirementRule(
        "finance_domain",
        "금융·결제 도메인 경험",
        (r"금융", r"핀테크", r"결제", r"보험", r"증권", r"은행"),
        (r"금융", r"핀테크", r"결제", r"보험", r"증권", r"은행"),
        "high",
        9.0,
        72,
        True,
    ),
    HardRequirementRule(
        "health_domain",
        "의료·헬스케어 도메인 경험",
        (r"의료", r"헬스케어", r"병원", r"바이오"),
        (r"의료", r"헬스케어", r"병원", r"바이오"),
        "high",
        9.0,
        72,
        True,
    ),
    HardRequirementRule(
        "game_domain",
        "게임 서비스 도메인 경험",
        (r"게임", r"\bunity\b", r"\bunreal\b"),
        (r"게임", r"\bunity\b", r"\bunreal\b"),
        "high",
        10.0,
        70,
        True,
    ),
    HardRequirementRule(
        "agent_runtime",
        "에이전트 런타임·하네스·도구 호출 시스템 실무",
        (
            r"agent runtime",
            r"agentic harness",
            r"agent harness",
            r"에이전트 하네스",
            r"tool calling",
            r"도구 호출 인프라",
            r"(?<![a-z0-9])sandboxing(?![a-z0-9])",
            r"샌드박싱",
            r"agent memory",
            r"에이전트 메모리",
        ),
        (
            r"agent runtime",
            r"agentic harness",
            r"agent harness",
            r"에이전트 하네스",
            r"tool calling",
            r"도구 호출 인프라",
            r"(?<![a-z0-9])sandboxing(?![a-z0-9])",
            r"샌드박싱",
            r"agent memory",
            r"에이전트 메모리",
        ),
        "high",
        14.0,
        68,
        True,
    ),
    HardRequirementRule(
        "model_training",
        "모델 학습·파인튜닝 실무",
        (
            r"모델 학습",
            r"파인튜닝",
            r"fine tuning",
            r"fine-tuning",
            r"training pipeline",
            r"\bpytorch\b",
            r"\btensorflow\b",
        ),
        (
            r"모델 학습",
            r"파인튜닝",
            r"fine tuning",
            r"training pipeline",
            r"\bpytorch\b",
            r"\btensorflow\b",
        ),
        "high",
        14.0,
        67,
        True,
    ),
    HardRequirementRule(
        "robotics",
        "로보틱스·SLAM·ROS 실무",
        (r"로보틱스", r"\bslam\b", r"\bros2?\b", r"로봇"),
        (r"로보틱스", r"\bslam\b", r"\bros2?\b", r"로봇"),
        "high",
        14.0,
        66,
        True,
    ),
    HardRequirementRule(
        "embedded",
        "임베디드·펌웨어 실무",
        (r"임베디드", r"펌웨어", r"\bmcu\b", r"\brtos\b", r"embedded", r"firmware"),
        (r"임베디드", r"펌웨어", r"\bmcu\b", r"\brtos\b", r"embedded", r"firmware"),
        "high",
        14.0,
        66,
        True,
    ),
    HardRequirementRule(
        "leadership",
        "조직·프로젝트 리딩 경험",
        (r"리딩 경험", r"리더 경험", r"팀장 경험", r"매니징 경험", r"\bleadership\b"),
        (r"리딩", r"리더", r"팀장", r"매니징", r"\bleadership\b", r"\blead\b"),
        "medium",
        7.0,
        77,
    ),
    HardRequirementRule(
        "english",
        "영어 업무 역량",
        (r"영어", r"\benglish\b"),
        (r"영어", r"\benglish\b"),
        "medium",
        5.0,
        82,
        True,
    ),
    HardRequirementRule(
        "japanese",
        "일본어 업무 역량",
        (r"일본어", r"\bjapanese\b"),
        (r"일본어", r"\bjapanese\b"),
        "medium",
        5.0,
        82,
        True,
    ),
    HardRequirementRule(
        "chinese",
        "중국어 업무 역량",
        (r"중국어", r"\bchinese\b"),
        (r"중국어", r"\bchinese\b"),
        "medium",
        5.0,
        82,
        True,
    ),
    HardRequirementRule(
        "education",
        "요구 학력·전공",
        (r"학사", r"석사", r"박사", r"관련 전공", r"컴퓨터 공학 전공"),
        (r"학사", r"석사", r"박사", r"관련 전공", r"컴퓨터 공학", r"computer science"),
        "medium",
        4.0,
        84,
    ),
)


EXPERIENCE_MARKERS = (
    "경험",
    "경력",
    "실무",
    "운영",
    "구축",
    "대응",
    "설계",
    "개발",
    "이해",
    "지식",
    "역량",
    "능력",
    "가능",
    "숙련",
)


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣+#.]+", " ", value.casefold()).strip()


def _profile_corpus(profile: dict[str, Any]) -> str:
    values = [str(profile.get("summary", ""))]
    values.extend(str(skill) for skills in profile.get("skills", {}).values() for skill in skills)
    values.extend(
        str(achievement.get("evidence", "")) for achievement in profile.get("achievements", [])
    )
    return _normalized("\n".join(values))


def _negative_corpus(profile: dict[str, Any]) -> str:
    gaps = profile.get("skill_gaps", {})
    values = [
        str(value) for key in ("none", "no_professional_experience") for value in gaps.get(key, [])
    ]
    return _normalized("\n".join(values))


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _backend_alternative_satisfies_security(line: str, profile_text: str) -> bool:
    has_alternative = "또는" in line or re.search(r"\bor\b", line)
    has_security_backend_choice = "보안" in line and "백엔드" in line
    backend_profile = _matches(
        profile_text,
        (r"\bpython\b", r"\bdjango\b", r"\bfastapi\b", r"백엔드", r"\bbackend\b"),
    )
    return bool(has_alternative and has_security_backend_choice and backend_profile)


def assess_hard_requirements(
    requirements: list[str],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    profile_text = _profile_corpus(profile)
    negative_text = _negative_corpus(profile)
    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()

    for original_line in requirements:
        line = _normalized(original_line)
        for rule in RULES:
            if rule.key in seen or not _matches(line, rule.job_patterns):
                continue
            if rule.needs_experience_context and not any(
                marker in line for marker in EXPERIENCE_MARKERS
            ):
                continue
            if rule.key == "security_operations" and _backend_alternative_satisfies_security(
                line, profile_text
            ):
                continue
            if rule.key == "education" and "준하는" in line and profile.get("years_experience", 0):
                continue

            profile_match = _matches(profile_text, rule.profile_patterns)
            explicitly_absent = _matches(negative_text, rule.profile_patterns)
            if profile_match and not explicitly_absent:
                continue

            seen.add(rule.key)
            gaps.append(
                {
                    "key": rule.key,
                    "skill": rule.label,
                    "severity": rule.severity,
                    "penalty": rule.penalty,
                    "cap": rule.cap,
                    "requirement": original_line,
                }
            )
    return gaps
