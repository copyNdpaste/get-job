from app.ecosystem_monitor import extract_program_candidates


def test_extract_program_candidates_keeps_only_same_public_host_links() -> None:
    html = """
    <main>
      <a href="/program/batch-9">2026 배치 9기 스타트업 모집</a>
      <a href="https://example.com/apply">창업 교육 프로그램 지원</a>
      <a href="/news">일반 뉴스</a>
    </main>
    """

    candidates = extract_program_candidates(html, "https://investor.example/programs")

    assert len(candidates) == 1
    assert candidates[0].title == "2026 배치 9기 스타트업 모집"
    assert candidates[0].url == "https://investor.example/program/batch-9"
    assert candidates[0].program_type == "batch"
    assert candidates[0].is_open is True


def test_extract_program_candidates_marks_closed_programs() -> None:
    html = "<a href='/program/old'>창업 교육 프로그램 모집 마감</a>"

    candidates = extract_program_candidates(html, "https://investor.example/programs")

    assert candidates[0].program_type == "education"
    assert candidates[0].is_open is False


def test_extract_program_candidates_identifies_open_investment_batch_listing() -> None:
    html = """
    <section>
      <h2>지금 지원할 수 있는 배치 프로그램</h2>
      <a href="/incubations/29">모집중 프라이머 배치 29기 ~ 2026.12.31 까지 지원하기</a>
    </section>
    """

    candidates = extract_program_candidates(html, "https://apply.primer.kr/")

    assert len(candidates) == 1
    assert candidates[0].program_type == "batch"
    assert candidates[0].deadline_text == "2026.12.31"
    assert candidates[0].is_open is True


def test_extract_program_candidates_keeps_ir_and_event_announcements() -> None:
    html = """
    <main>
      <a href="/web/portal/bbs/notice/131126">서울시 공동 스케일업 IR 행사 개최</a>
      <a href="/web/portal/bbs/notice/131127">중소기업 AI 전환 세미나 개최 안내</a>
    </main>
    """

    candidates = extract_program_candidates(html, "https://www.vcs.go.kr/web/portal/bbs/notice/list")

    assert [item.program_type for item in candidates] == ["demo_day", "program"]
    assert all(item.is_open for item in candidates)


def test_extract_program_candidates_does_not_treat_registered_date_as_deadline() -> None:
    html = """
    <li>
      <a href="/web/portal/bbs/notice/131126">서울시 공동 스케일업 IR 행사 개최</a>
      <span>등록일자 2026-08-01</span>
    </li>
    """

    candidate = extract_program_candidates(
        html, "https://www.vcs.go.kr/web/portal/bbs/notice/list"
    )[0]

    assert candidate.deadline_text is None
    assert candidate.is_open is True


def test_vcs_collection_ignores_navigation_links() -> None:
    html = """
    <nav><a href="/web/portal/bbs/invtnotice/list">출자공고</a></nav>
    <a href="/web/portal/bbs/notice/131127">AI 전환 세미나 개최 안내</a>
    """

    candidates = extract_program_candidates(
        html, "https://www.vcs.go.kr/web/portal/bbs/notice/list"
    )

    assert [item.title for item in candidates] == ["AI 전환 세미나 개최 안내"]


def test_vcs_short_deadline_is_inferred_with_current_year() -> None:
    html = """
    <li>
      <a href="/web/portal/bbs/notice/2">기업현장 방문행사 참가기업 모집(~9/7 17:00)</a>
      <span>등록일자 2026-08-26</span>
    </li>
    """

    candidate = extract_program_candidates(
        html, "https://www.vcs.go.kr/web/portal/bbs/notice/list"
    )[0]

    assert candidate.deadline_text == "2026-09-07"
    assert candidate.is_open is True


def test_monthly_consultation_expires_at_end_of_program_month() -> None:
    html = """
    <a href="/web/portal/bbs/martnotice/1">2025년 7월 벤처투자톡톡 1:1 상담회 모집</a>
    """

    candidate = extract_program_candidates(
        html, "https://www.vcs.go.kr/web/portal/bbs/martnotice/list"
    )[0]

    assert candidate.deadline_text == "2025-07-31"
    assert candidate.is_open is False


def test_extract_program_candidates_excludes_fund_qna_not_for_founders() -> None:
    html = """
    <a href="/web/portal/bbs/notice/1">2026년 LP 성장펀드 출자사업 질의응답 게시</a>
    """

    assert extract_program_candidates(
        html, "https://www.vcs.go.kr/web/portal/bbs/notice/list"
    ) == []
