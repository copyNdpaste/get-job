from app.api.ai import (
    AIInterviewPrepPayload,
    AIJobEvidencePayload,
    _interview_input_hash,
)


def test_evidence_payload_normalizes_codex_lists_to_text() -> None:
    payload = AIJobEvidencePayload.model_validate(
        {
            "summary": ["요약 1", "요약 2"],
            "strengths": [
                {
                    "title": ["백엔드", "경험"],
                    "profile_evidence": ["Django", "FastAPI"],
                    "job_evidence": ["Python", "API"],
                }
            ],
            "gaps": [
                {
                    "title": "보완점",
                    "severity": "HIGH",
                    "explanation": ["경험 확인 필요", "면접에서 검증"],
                }
            ],
            "recommendation": ["지원 권장", "근거 확인"],
        }
    )

    assert payload.summary == "요약 1 · 요약 2"
    assert payload.strengths[0].profile_evidence == "Django · FastAPI"
    assert payload.strengths[0].job_evidence == "Python · API"
    assert payload.gaps[0].severity == "high"
    assert payload.gaps[0].explanation == "경험 확인 필요 · 면접에서 검증"
    assert payload.recommendation == "지원 권장 · 근거 확인"


def test_evidence_payload_limits_generated_content() -> None:
    payload = AIJobEvidencePayload.model_validate(
        {
            "summary": "가" * 1400,
            "strengths": [
                {
                    "title": f"강점 {index}",
                    "profile_evidence": "이력서 근거",
                    "job_evidence": "공고 근거",
                }
                for index in range(8)
            ],
            "gaps": [],
            "recommendation": "나" * 1400,
        }
    )

    assert len(payload.summary) == 1200
    assert len(payload.strengths) == 6
    assert len(payload.recommendation) == 1200


def test_interview_prep_payload_normalizes_and_limits_generated_content() -> None:
    payload = AIInterviewPrepPayload.model_validate(
        {
            "opening_pitch": "가" * 1600,
            "questions": [
                {
                    "category": "TECHNICAL",
                    "question": ["대용량 트래픽", "처리 경험을 설명해 주세요"],
                    "why_asked": "공고의 확장성 요구 검증",
                    "answer_outline": [f"답변 {item}" for item in range(7)],
                    "resume_evidence": ["API 처리량 개선"],
                    "follow_ups": [f"꼬리질문 {item}" for item in range(6)],
                    "caution": ["수치를", "추측하지 않기"],
                }
            ],
            "study_topics": [f"복습 {item}" for item in range(10)],
            "questions_to_ask": [f"질문 {item}" for item in range(7)],
        }
    )

    assert len(payload.opening_pitch) == 1400
    assert payload.questions[0].category == "technical"
    assert payload.questions[0].question == "대용량 트래픽 · 처리 경험을 설명해 주세요"
    assert len(payload.questions[0].answer_outline) == 5
    assert len(payload.questions[0].follow_ups) == 4
    assert payload.questions[0].caution == "수치를 · 추측하지 않기"
    assert len(payload.study_topics) == 8
    assert len(payload.questions_to_ask) == 5


def test_interview_input_hash_is_stable_and_changes_with_grounded_input() -> None:
    first = {"job": {"title": "Backend"}, "candidate": {"skills": ["Python"]}}
    reordered = {"candidate": {"skills": ["Python"]}, "job": {"title": "Backend"}}
    changed = {"job": {"title": "Backend"}, "candidate": {"skills": ["Go"]}}

    assert _interview_input_hash(first) == _interview_input_hash(reordered)
    assert _interview_input_hash(first) != _interview_input_hash(changed)
