Feature: 개발 관련 채용 공고 수집
  공개 채용 페이지에서 Python, TypeScript, AI, Server, Backend 직무만 구조화한다.

  Scenario Outline: 사이트별 개발 공고를 구조화한다
    Given "<source>"의 공개 채용 상세 HTML이 있다
    When 사이트 adapter로 공고를 파싱한다
    Then 공고는 개발 직무로 포함된다
    And 제목은 "<title>"이다
    And 기술 스택에 "<tech>"가 있다

    Examples:
      | source      | title                         | tech       |
      | groupby     | AI-Native 풀스택 개발자       | TypeScript |
      | wanted      | Backend Engineer              | Python     |
      | jumpit      | 백엔드 개발자 - python, Django | Django     |
      | rocketpunch | AI Backend Engineer           | Python     |
      | rallit      | Server Developer              | AI Agent   |

  Scenario: TypeScript가 있어도 순수 프론트엔드 공고는 제외한다
    Given 제목이 "Frontend Engineer"이고 본문에 "TypeScript React Next.js"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: Server 문구가 있어도 PM 공고는 제외한다
    Given 제목이 "웹 서버 개발 PM"이고 본문에 "프로젝트 일정 관리"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: Backend 문구가 있어도 서비스 기획자 공고는 제외한다
    Given 제목이 "환급 서비스기획자 (백엔드 로직 설계)"이고 본문에 "서비스 정책과 화면을 기획합니다"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: AWS가 있어도 하드웨어 개발 공고는 제외한다
    Given 제목이 "하드웨어 개발자 경력 정규직 채용"이고 본문에 "AWS 장비 연동"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: REST API가 있어도 안드로이드 앱 공고는 제외한다
    Given 제목이 "안드로이드 러닝 앱 개발자 경력"이고 본문에 "Kotlin REST API Firebase"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: Python이 있어도 QA 전용 공고는 제외한다
    Given 제목이 "QA엔지니어 (Web, App, AI)"이고 본문에 "Python TypeScript 테스트 자동화"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: Python 백엔드 공고는 수집한다
    Given 제목이 "백엔드 개발자 (Python)"이고 본문에 "REST API AWS 주문 정산 서비스"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 개발 직무로 포함된다

  Scenario: 일반 웹 개발자 제목도 상세에 Python 서버 기술이 있으면 수집한다
    Given 제목이 "웹 개발자"이고 본문에 "Python Django REST API 서버 개발"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 개발 직무로 포함된다

  Scenario: Python 구현을 직접 담당하는 Technical PO 공고는 수집한다
    Given 제목이 "Product Owner (초기 팀원)"이고 본문에 "Python 기반 AI 활용 및 개발 전문성으로 실험 환경 세팅부터 실행까지 풀스택 담당"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 개발 직무로 포함된다

  Scenario: Python 개발팀과 협업만 하는 일반 Product Owner는 제외한다
    Given 제목이 "Product Owner"이고 본문에 "Python 개발팀과 협업하며 로드맵과 백로그를 관리"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: 채용 절차에 코딩테스트만 있는 Product Owner는 제외한다
    Given 제목이 "Product Owner"이고 본문에 "LLM 제품 로드맵 관리, 채용 절차는 코딩테스트 후 면접"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: 직접 코드를 작성하지 않는 Technical PM은 제외한다
    Given 제목이 "Technical PM"이고 본문에 "직접 코드를 작성하지는 않지만 Python과 TypeScript 아키텍처를 이해하고 제품 결정을 지원"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: 복지로 바이브 코딩 교육만 제공하는 Product Owner는 제외한다
    Given 제목이 "AI 프로덕트 오너"이고 본문에 "Python AI 제품 로드맵을 관리하며 복지로 바이브 코딩 교육을 지원"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario Outline: 인턴·신입 전용 또는 경력 상한 3년 이하 공고는 제외한다
    Given 제목이 "<title>"이고 본문에 "Python FastAPI 백엔드 서버 개발"가 있으며 경력 조건이 "<experience>"이다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

    Examples:
      | title                     | experience            |
      | [인턴] Backend Engineer   | 인턴 · 신입-경력 1년  |
      | Python 백엔드 신입        | 신입                  |
      | Python Backend Engineer   | 경력 1~3년            |
      | Python Backend Engineer   | 경력 3년 이하         |
      | AI 풀스택 개발자 (주니어) | 경력 3년 이상         |
      | AI Engineer (3년 이하)    | 경력 전체              |
      | Junior LLM Engineer       | 경력 3년 이상          |

  Scenario Outline: 3년 초과 경력 지원이 가능한 공고는 유지한다
    Given 제목이 "Python Backend Engineer"이고 본문에 "Python FastAPI 백엔드 서버 개발"가 있으며 경력 조건이 "<experience>"이다
    When 개발 공고 관련성을 판정한다
    Then 공고는 개발 직무로 포함된다

    Examples:
      | experience                    |
      | 경력 3년 이상                 |
      | 경력 2~6년                    |
      | 주니어 1~3년, 미들 4~8년     |

  Scenario: Java와 Spring만 있는 백엔드 공고는 제외한다
    Given 제목이 "백엔드 개발자"이고 본문에 "Java Spring Boot REST API 개발"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: Java가 있어도 Python이 함께 있는 혼합 스택 공고는 수집한다
    Given 제목이 "백엔드 개발자"이고 본문에 "Python FastAPI Java 마이그레이션"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 개발 직무로 포함된다

  Scenario: JavaScript는 Java 전용 공고로 오인하지 않는다
    Given 제목이 "Node.js 서버 개발자"이고 본문에 "Node.js JavaScript REST API"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 개발 직무로 포함된다

  Scenario: AI 키워드가 있어도 교육 강사 공고는 제외한다
    Given 제목이 "AI Agent 교육 강사 모집"이고 본문에 "LangChain Python"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: 본문이 명시적으로 비개발 직무라고 밝힌 프롬프트 기획 공고는 제외한다
    Given 제목이 "AI Agent 기획 / 프롬프트 엔지니어"이고 본문에 "본 포지션은 소프트웨어 엔지니어 포지션이 아닙니다. LLM Agent 기획 업무"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario: Python 키워드가 있어도 반도체 RTL 설계 공고는 제외한다
    Given 제목이 "NoC RTL Design Engineer"이고 본문에 "Python으로 검증하며 Verilog 반도체 회로 설계"가 있다
    When 개발 공고 관련성을 판정한다
    Then 공고는 수집 대상에서 제외된다

  Scenario Outline: 원티드 목록에서 상세 수집 대상 직군을 먼저 선별한다
    Given 원티드 목록 공고 제목이 "<title>"이다
    When 상세 페이지 방문 전 직군을 판정한다
    Then 상세 페이지 방문 여부는 "<visit>"이다

    Examples:
      | title                                  | visit |
      | Backend Engineer (Consumer Service)    | yes   |
      | Software Engineer                      | yes   |
      | 데이터 엔지니어                        | yes   |
      | Android Developer                      | no    |
      | Product Designer                       | no    |
      | 웹 서버 개발 PM                        | no    |
      | Product Owner (초기 팀원)              | yes   |

  Scenario: 원티드 화면의 기술 스택 태그를 누락 없이 수집한다
    Given 원티드 화면 기술 스택이 포함된 공개 상세 API 응답이 있다
    When 원티드 API adapter로 공고를 파싱한다
    Then 기술 스택에 "Java"가 있다
    And 기술 스택에 "JPA"가 있다
    And 기술 스택에 "Spring Boot"가 있다
    And 코딩테스트가 있는 공고로 구분된다
    And 면접 횟수는 1회로 구분된다

  Scenario: 점핏 화면의 기술스택 태그를 원문 그대로 수집한다
    Given "jumpit"의 공개 채용 상세 HTML이 있다
    When 사이트 adapter로 공고를 파싱한다
    Then 기술 스택에 "JPA"가 있다

  Scenario: 랠릿 원본의 직무 기술 태그를 원문 그대로 수집한다
    Given "rallit"의 공개 채용 상세 HTML이 있다
    When 사이트 adapter로 공고를 파싱한다
    Then 기술 스택에 "JUnit"가 있다

  Scenario: 로켓펀치는 자동 네트워크 수집을 하지 않는다
    Given "rocketpunch" 수집 정책이 있다
    Then 수집 방식은 "manual_html"이다

  Scenario: 그룹바이는 브라우저에 남은 필터 대신 개발 직군 전체를 페이지네이션한다
    Given 그룹바이 공개 목록 API에 개발 공고 3개가 두 페이지에 있다
    When 그룹바이 공개 API에서 개발 후보를 탐색한다
    Then 그룹바이 개발 후보는 3개이다
    And 모든 그룹바이 목록 요청은 개발 직군 필터를 사용한다

  Scenario: 동일 공고 재수집과 변경 이력을 안전하게 저장한다
    Given 비어 있는 수집 DB와 "jumpit" 수집원이 있다
    When 같은 상세 HTML을 두 번 저장한다
    Then 공고는 1개이고 스냅샷도 1개이다
    When 주요업무가 변경된 HTML을 저장한다
    Then 공고는 1개이고 스냅샷은 2개이다

  Scenario Outline: 공고에 명시된 채용 절차만 구조화한다
    Given 채용 절차가 "<process>"로 명시되어 있다
    When 채용 절차를 분석한다
    Then 코딩테스트 여부는 "<coding_test>"이다
    And 면접 횟수는 "<interviews>"이다

    Examples:
      | process                                             | coding_test | interviews |
      | 서류 → 코딩테스트 → 1차 실무 면접 → 2차 컬처 면접 | 있음        | 2          |
      | 서류 - 직무 인터뷰                                 | 미확인      | 1          |
      | 서류 → 코딩테스트 없음 → 면접 없음                 | 없음        | 0          |
      | 미기재                                              | 미확인      | 미확인     |
