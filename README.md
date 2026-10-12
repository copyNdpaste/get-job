# get-job · 공고별 이력서 추천기

리멤버·데모데이·원티드·그룹바이·점핏·랠릿·로켓펀치와 Greenhouse·Lever·Ashby·Greeting·Ninehire의
공개 채용 공고를 로컬에 누적하고, 개인 이력서와
비교해 적합도·지원가치·서류 경쟁력과 공고별 최적 이력서를 계산하는 로컬 우선 웹 애플리케이션입니다.

공고마다 Python 백엔드, Python·TypeScript 백엔드, 서버·인프라, 프로덕트 엔지니어 이력서를 모두
비교합니다. 핵심 직무 35점, 요구 기술 25점, 유사 문제 해결 20점, 수치 성과 10점, 스타트업 실행
방식 10점으로 추천 버전과 차선책을 고르고, 추천 근거·성과 근거·공고별 수정 포인트를 함께 보여줍니다.

핵심 점수와 순위는 재현 가능한 규칙으로 계산합니다. AI는 기본적으로 사용자 컴퓨터에서 실행되는
OpenAI-compatible 모델을 사용해 추천 답변과 근거를 교차검토합니다. 로컬 AI가 없어도 규칙 분석은 계속
작동하며, 외부 유료 AI API로 자동 전환하지 않습니다.

## 시스템 이해 가이드

서비스 상단의 **시스템 가이드 ↗**에서 수집 → 정규화 → 저장 → 규칙 점수 → AI 분석 → 지원 준비를
인터랙티브 구조도로 살펴볼 수 있습니다. LangChain Core·LangGraph의 역할, 가상 공고의 변환 과정,
0·1·2회 모델 호출 시뮬레이션, 예산 정책과 실제 구현 파일을 설명합니다.

프런트엔드 실행 후 `/system-guide/index.html`로 열거나
[HTML 원본](frontend/public/system-guide/index.html)을 브라우저에서 직접 열 수 있습니다.
HTML·CSS·JavaScript만 사용하며 외부 라이브러리 다운로드, 서비스 API·모델 호출 없이 동작합니다.
[상세 설계 문서](docs/ai-analysis-architecture.md)와 함께 참고하세요.

## 빠른 실행

Docker와 Docker Compose가 필요합니다. macOS에서는 아래 스크립트 하나로 빌드, 실행과 화면 열기까지
처리할 수 있습니다.

```bash
cd /path/to/get-job
./run.sh
```

브라우저를 자동으로 열지 않으려면 `./run.sh --no-open`을 사용합니다. 처음 실행할 때 `.env`가 없으면
예시 설정으로 생성합니다. 기존 `job-analyzer_postgres_data` 볼륨이 있으면 새 이름으로 복사하거나
초기화하지 않고 그대로 연결합니다. 실제 DB 볼륨은 Git에서 제외됩니다.

이미 실행 중인 앱에 소스 변경만 반영하려면 빠른 재시작 명령을 사용합니다. 이미지 재빌드와 DB
초기화 없이 기존 데이터를 유지합니다.

```bash
./run.sh restart
```

OrbStack 앱이 켜져 있어도 Docker 서버가 응답하지 않으면 아래 명령으로 엔진을 복구할 수 있습니다.
이 옵션은 응답이 없는 엔진만 재시작하며, 같은 OrbStack에서 실행하는 다른 컨테이너도 잠시
중단될 수 있습니다. 컨테이너와 데이터 볼륨을 삭제하지 않습니다.

```bash
./run.sh --repair-docker
```

`--no-open`과 함께 사용할 수 있습니다. 일반 실행은 `orbctl start`로 엔진을 시작하고,
계속 응답이 없으면 복구 명령을 안내합니다. Docker 소켓 권한 오류는 엔진 장애와 구분해 표시합니다.

- GUI: <http://localhost:41739>
- API 문서: <http://localhost:8000/docs>
- 상태 확인: <http://localhost:8000/health>

프론트엔드와 API는 `127.0.0.1`에만 바인딩됩니다. PostgreSQL은 호스트에 포트를 열지 않고
Compose 내부 네트워크에서만 API와 통신합니다. DB는 `postgres_data` named volume에 저장되어
재빌드해도 유지됩니다. `docker compose down -v`는 DB까지 삭제합니다.

프로젝트 이름은 `get-job`이지만 기존 설치의 수집 DB를 보존하기 위해 기본 볼륨 이름은
`job-analyzer_postgres_data`를 계속 사용합니다. 새 DB로 시작하려면 Git에서 제외된 `.env`의
`POSTGRES_VOLUME_NAME`만 다른 이름으로 바꾸세요.

기존 브라우저 필터와 일일 추천 읽음 상태도 그대로 이어서 사용합니다.

## 개인 이력서 데이터

저장소의 `backend/examples/candidate-profile.example.json`은 익명의 가상 데이터입니다. 사용자는 이 파일을
`data/candidate-profile.local.json`으로 복사한 뒤 자신의 경력·기술·성과·보완점을 입력합니다.
특정 기술의 실무 연차와 지원 방향은 같은 디렉터리의
`candidate-career-direction.local.json`에 `skill_experience_years`, `career_direction`,
`node_transition_evidence`로 분리할 수 있습니다. 두 파일은 모두 Git과 Docker 빌드 컨텍스트에서
제외됩니다.

`data/` 내의 개인 파일, `.env`, DB export, 이력서 PDF/DOCX, 브라우저 세션과 크롤러 캐시는
Git에서 제외됩니다. 공개 push 전에는 반드시 `git status --short`와 staged diff를 확인하세요.
로컬 프로필이 없으면 익명 예시로 시작하고, 로컬 파일을 추가한 뒤 재시작하면 동기화합니다.

`data/generated-resumes.local/`에는 다음 로컬 전용 PDF 파일을 둡니다.

- `01_Python_서버_백엔드_이력서.local.pdf`
- `02_Python_서버_인프라_이력서.local.pdf`
- `03_Product_Builder_Technical_PO_이력서.local.pdf`
- `04_Python_TypeScript_백엔드_이력서.local.pdf`

공고 상세에서 추천 이력서를 바로 열 수 있습니다. PDF 응답은 캐시하지 않으며 외부 AI로 보내지 않습니다.

## 로컬 AI 기본 설정

```env
AI_ENABLED=true
AI_PROVIDER=openai-compatible
AI_BASE_URL=http://host.docker.internal:1234
AI_MODEL=auto
AI_ALLOW_REMOTE=false
```

로컬 AI 서버가 `/v1/models`와 `/v1/chat/completions`를 제공하도록 실행하세요. 기본 포트는
LM Studio 등에서 흔히 사용하는 `1234`입니다. `AI_MODEL=auto`는 서버가 반환하는 첫 모델을 사용합니다. 로컬
서버가 다른 포트를 사용하면 Git에서 제외된 `.env`의 `AI_BASE_URL`만 바꾸면 됩니다.

GUI 상단의 `LOCAL MODEL` 선택기는 서버의 `/v1/models` 목록을 읽습니다. 선택한 모델은 브라우저에
로컬 저장되고, 이후 추천 채팅과 근거 교차검토에 함께 전달됩니다. 새 모델을 로드했다면 옆의 새로고침
버튼으로 목록을 갱신할 수 있습니다.

### Codex GPT를 사용자가 직접 허용하는 경우

macOS에서는 기존 ChatGPT 로그인과 Codex CLI 모델을 제한된 loopback 브리지로 연결할 수 있습니다.

```bash
./scripts/install_codex_bridge_macos.sh
```

그다음 Git에서 제외된 `.env`에만 다음 값을 설정합니다.

```env
AI_PROVIDER=codex
AI_BASE_URL=http://host.docker.internal:48765
AI_MODEL=gpt-5.6-luna
AI_ALLOW_REMOTE=true
AI_TIMEOUT_SECONDS=180
AI_ANALYSIS_FAST_MODEL=gpt-5.6-luna
AI_ANALYSIS_REVIEW_MODEL=gpt-5.6-terra
```

이 모드는 API key를 Docker에 넣지 않고 사용자의 ChatGPT 로그인을 이용합니다. 다만 검색 질문,
구조화된 이력서 근거와 선택된 공고 정보가 OpenAI로 전송되고 Codex 사용량을 소비합니다. 브리지는
Codex의 셸·브라우저·앱 도구를 끄고 텍스트 응답만 반환하며, 인증 파일을 컨테이너에 마운트하지 않습니다.
삭제하려면 `./scripts/uninstall_codex_bridge_macos.sh`를 실행합니다.

브리지 설치 기본 모델은 `gpt-5.6-luna`, 허용된 재검토 모델은 `gpt-5.6-terra`입니다.
기존 Astra 전용 설치는 `./scripts/install_codex_bridge_macos.sh`로 다시 설치합니다.
`CODEX_BRIDGE_MODEL` / `CODEX_BRIDGE_REVIEW_MODEL`로 허용 모델을 명시적으로 바꿀 수 있습니다.
모델 접근 권한은 현재 Codex 로그인 계정에 따라 달라지며, 설정만으로 권한이 생기지는 않습니다.
연결 실패 시 다른 모델로 자동 전환하지 않습니다.

로컬 AI는 다음 곳에 사용됩니다.

- 추천 채팅: DB에서 규칙으로 정렬한 공고를 자연스럽게 요약
- 근거 모달: 이력서 근거와 공고 근거의 강점·격차를 교차검토
- 면접 준비 팩: 60초 자기소개, 예상 질문, STAR 답변 골격, 꼬리질문과 복습 주제를 구조화해 생성
- 공고 심층 분석: LangGraph로 요구사항 추출 → 이력서 매칭 → 인용 검증 → 보고서 정리

### LangChain / LangGraph 분석 파이프라인

공고의 적합도 근거 화면에서 **심층 분석 실행**을 누릅니다. 분석 예산에 설정한 모델을 사용하며,
요구사항별 직접 근거·부분 근거·확인 필요와 지원 전 준비 항목을 표시합니다.
분석 과정에서는 단계별 시도 횟수와 소요 시간을 확인할 수 있습니다.
상단 **AI 분석·예산**에서는 모델 구성·일일 예산·사용량을 확인하고 수집된 상위 공고를 일괄 분석합니다.
대화용 모델 선택기는 이 저비용 경로의 모델을 바꾸지 않습니다.

- **LangChain Core**: 프롬프트와 메시지를 구성합니다. 모델 호출은 기존 `LocalAIClient`를
  재사용해 로컬 모델, Ollama, 명시적으로 허용한 Codex 브리지의 연결 규칙을 유지합니다.
- **LangGraph**: 규칙 추출·관련 근거 검색 → 기본 모델 → 조건부 재검토 → 보고서의 상태와
  조건 분기를 관리합니다. 단순 기술명 일치는 모델 호출 없이 처리합니다.
- **검증**: 공고 인용이 원문에 존재하는지, 근거 ID가 실제 이력서 입력에 있는지,
  요구사항이 중복·누락 없이 평가됐는지 확인합니다. 인용 존재 검증이 의미적 정확성을 보장하지는
  않으므로 지원 결정 전에 원문을 검토합니다. 규칙 점수는 모델이 수정할 수 없습니다.
- **비용 제한**: 단순 기술명 0회, 일반 분석 기본 모델 1회, 모호한 매칭이나 검증 실패에만
  재검토 모델 1회를 추가합니다. 공고당 최대 2회, 배치당 새 분석 10건·재검토 2건이 기본입니다.
  연결 실패는 상위 모델 전환 사유가 아닙니다. 수집 후 자동 분석은 기본적으로 꺼져 있습니다.
- **입력 압축**: 중복 요구사항을 제거해 필수 요건부터 최대 8개, 관련 경력은 어휘 검색으로
  최대 10개만 선택합니다. LLM에 보내는 전체 메시지는 기본 12,000 UTF-8 바이트 이하입니다.
  생략된 요구사항 수를 화면에 표시하며, 전체 요건 충족 판단으로 오인하지 않도록 합니다.
- **예산 예약**: 일일 100,000 계획 단위와 재검토 5회가 기본입니다. DB의 조건부 UPDATE로
  호출 전에 원자적으로 예약하고 실패·타임아웃에도 예약을 유지합니다. 예약량은 입력 바이트+
  여유분+출력 상한이며 실제 토큰/과금액과 다릅니다. 실사용 토큰은 제공자 응답에서 따로 집계합니다.
- **로컬 저장**: 완료된 보고서는 기존 `job_ai_analyses` 테이블에 저장합니다. 입력·규칙 점수·
  파이프라인 버전·제공자·서버 주소·실제 모델에 따라 캐시를 구분합니다. 중간 그래프 상태는
  메모리에만 있으므로 프로세스 종료 후 중간부터 재개하는 체크포인트 기능은 없습니다.
- **개인정보**: 연락처 필드를 제외한 구조화된 경력 근거만 입력하고, 입력은 UTF-8 60,000바이트·
  근거 250개 이하로 제한합니다. 자유 서술문에 직접 넣은 개인정보까지 자동 익명화하지는 않습니다.
  LangSmith 외부 추적은 환경변수와 무관하게 이 파이프라인에서 비활성화합니다.

API: `POST /api/ai/analysis/jobs/{job_id}?refresh=false`,
`POST /api/ai/analysis/batch` (`{"limit":10}`), `GET /api/ai/analysis/usage`.
`refresh=true`는 캐시를 무시하고 새 분석을 생성하지만 일일 예산은 그대로 적용합니다.
예산·연결 실패와 검증되지 않은 결과는 캐시하지 않습니다.
기존 `/api/ai/jobs/{job_id}/analysis`는 호환용 단일 모델 경로이며 새 일괄 분석에서 사용하지 않습니다.
추가 교차검토·면접 팩·추천 채팅은 별도 기능으로 이 예산에 포함되지 않으며 수동 실행합니다.
새 테이블 마이그레이션이 있으므로 Docker 사용 시 `./run.sh --no-open`으로 다시 빌드합니다.
로컬 개발 환경은 `.venv/bin/pip install -e './backend[dev]'`로 의존성을 갱신합니다.
그다음 `cd backend && ../.venv/bin/alembic upgrade head`로 마이그레이션합니다.

수집 완료 후 연동하려면 개인 `.env`에 `AI_ANALYSIS_AFTER_CRAWL=true`를 설정합니다.
신규/갱신 대상으로 선택된 공고 중 규칙 점수 기준을 통과한 공고에 한해 처리합니다.
이미 수집된 데이터는 GUI의 일괄 분석 버튼으로 처리합니다.
외부 OpenAI-compatible API는 `AI_ANALYSIS_FAST_MODEL`을 명시해야 하며, Codex 모드의 자동값은
Luna로 해석합니다. 재검토 모델은 `AI_ANALYSIS_REVIEW_MODEL`을 설정해야 활성화됩니다.

Codex CLI의 출력 한도는 프롬프트로 요청하는 수준입니다. 실제 사용량에는 CLI의 추가 문맥이
포함될 수 있어 절대 과금 상한을 보장하지 않습니다. 제공된 실사용량이 예약량을 넘으면 초과분도
예산에 반영해 후속 호출을 차단합니다. 직접 API/Ollama 연결에는 출력 한도 파라미터를 전달합니다.
실제 전송과 비용 측정 없이 비용 절감률을 주장하지 않습니다.

[설계·평가 방법과 이력서용 기술 설명](docs/ai-analysis-architecture.md)을 참고하세요.

설계 참고: [LangChain 개요](https://docs.langchain.com/oss/python/langchain/overview),
[LangGraph 개요](https://docs.langchain.com/oss/python/langgraph/overview),
[OpenAI 모델 접근 권한](https://learn.chatgpt.com/docs/enterprise/workspace-model-availability).

면접 준비 팩은 사용자가 버튼을 누를 때만 생성합니다. 공고·후보자 프로필·규칙 분석을 정규화한 입력
해시와 모델을 기준으로 결과를 로컬 PostgreSQL에 캐시하므로 같은 입력에는 LLM을 다시 호출하지 않습니다.
공고나 프로필이 바뀌면 해시가 달라져 자동으로 새 분석을 만들며, 프롬프트 원문과 이력서 원문은 캐시
테이블에 저장하지 않습니다. 생성 결과는 Pydantic 스키마로 길이·개수·질문 유형을 검증한 뒤에만 화면에
표시합니다.

Codex 모드에서는 GPT가 질문을 먼저 구조화한 뒤 DB를 필터링하고 추천 근거를 작성합니다. 모델이나 브리지가
꺼져 있으면 GUI에 `GPT 미연결 · 규칙 엔진 사용 중`으로 표시되고 규칙 분석만 사용합니다.
외부 유료 API로 전환되지 않습니다. AI를 아예 끄려면 `AI_PROVIDER=disabled`로 설정하세요.

### 수집 이후 분석 파이프라인

1. 소스별 수집기가 공개 공고를 공통 스키마로 정규화하고 원본 변경 해시와 스냅샷을 남깁니다.
2. 재현 가능한 규칙 엔진이 역할·필수 기술·경력·업무 근거를 점수화하고 제외 기준을 적용합니다.
3. 저비용 LangGraph 파이프라인이 관련 경력을 검색하고 기본 모델로 매칭한 뒤 필요한 경우만 재검토합니다.
4. 구조화 출력은 스키마 검증과 입력 해시 캐시를 거친 뒤 GUI와 자연어 추천에서 사용됩니다.

LangChain Core의 프롬프트 구성과 LangGraph의 상태·조건 분기를 사용합니다.
모델 장애 시 규칙 점수와 목록은 그대로
사용할 수 있고, AI 결과가 핵심 랭킹의 재현성을 깨뜨리지 않습니다.

### 외부 AI를 사용자가 직접 허용하는 경우

```env
AI_PROVIDER=openai-compatible
AI_BASE_URL=https://your-explicit-provider.example/v1
AI_MODEL=your-model
AI_ALLOW_REMOTE=true
AI_API_KEY=
```

외부 OpenAI-compatible 서비스는 `AI_PROVIDER` 변경과 `AI_ALLOW_REMOTE=true`를 모두 명시해야만
시작됩니다. 이 설정은 이력서와 공고 데이터를 외부로 전송하며 요금이 발생할 수 있습니다.
API key는 Git에서 제외된 `.env`에만 보관하세요. 기본값에서 외부 호스트는 시작 단계에서 차단됩니다.

## 점수 의미

- **적합도**: 현재 이력서로 공고의 역할·필수 기술·경력·업무를 바로 수행할 수 있는 정도
- **지원가치**: 적합도 62% + 직무·업무 방향성 23% + 현실적인 성장 기회 10% + 공고 근거 품질 5%로 계산한 지원 우선순위
- **서류 경쟁력**: 필수 요건과 경력 충족도를 중심으로 본 서류 통과 가능성의 규칙 기반 추정치

적합도는 `직무 18% + 필수기술 22% + 우대·인접기술 8% + 경력 12% + 업무근거 14%
+ 운영·데이터 9% + 설계·오너십 7% + 품질·협업 5% + 공고근거 5% + Python↔Node 전환 보정
- Node/Go 특정언어 필수연차·기술격차·신뢰도 감점`으로
계산합니다. 필수 기술은 공고 문장의 강조도와 이력서의 성과 근거 깊이를 가중하고, 공고 구조화 수준도
별도 반영합니다. 일반적인 격차와 근거 부족은 연속 감점하며 모바일·교육·모델학습 중심처럼 명확한
직무 불일치에만 상한을 적용합니다. GUI는 점수를 0.1점 단위로 표시하고, 동점이면 서류 경쟁력·다른
핵심 점수·공고 최신순으로 정렬합니다. AI는 이 점수를 변경하지 않고 근거만 보충합니다.

Go 공고는 Python에서 익힌 API·DB·클라우드 운영 역량을 이전 가능한 기반으로 보되, Go 실무 자체를
동일 숙련도로 간주하지 않습니다. 프로필에 Go 실무가 없으면 성장 기술로 표시하고 전환 보너스를 주지
않으며, Go 직접 실무 3년 이상을 필수로 요구하는 공고는 적합도·지원가치 상한을 적용합니다.

## 공고 수집과 GUI

- 데모데이: 공통 Python·Node.js·TypeScript·NestJS·Express·Fastify·Go·Golang·백엔드 직무 검색어로 공개 공고 수집
- 관련성 필터: 제목뿐 아니라 상세 기술·자격요건을 검사하고, Java/Spring만 명시된 공고는 제외하되
  Python·Node.js 혼합 스택, Go 백엔드와 Java가 선택 기술인 공고는 유지
- 문맥 필터: 단독 `Node`, `TS`, `Nest`는 다른 JavaScript 백엔드 기술 신호가 있을 때만 확정하고
  DOM·블록체인·인프라 node와 프론트엔드 중심 풀스택 공고는 제외
- 그룹바이: 공개 채용 API의 개발 직군 목록과 상세 공고 수집. API가 `[표시 제한]` 응답을
  반환하면 해당 데이터를 저장하지 않고, robots.txt에서 허용한 공개 개발자 채용 HTML과 상세
  페이지에 노출된 공고만 부분 수집합니다(최대 50개 후보). 전체 목록을 확인하지 못한 실행은
  미확인 기존 공고를 마감 처리하지 않습니다.
- 원티드: 공개 활성 공고 API로 목록과 상세 수집
- 리멤버: 로그인·지원 자동화 없이 공개 채용 목록과 상세 페이지만 브라우저로 수집
- 점핏·랠릿: 공개 sitemap의 활성 상세 URL 순회
- 사람인: 사용자가 공식 채용정보 API 승인을 받은 경우에만 `SARAMIN_API_KEY`로 공개 메타데이터 수집
- 잡플래닛: https://www.jobplanet.co.kr/job url로 수집
- 로켓펀치: 사용자가 저장한 공개 공고 HTML만 가져오기
- Greenhouse·Lever·Ashby: 공개 채용보드 JSON API에서 한국·서울 또는 한국 지원이 가능한 원격
  백엔드 공고 수집
- Greeting·Ninehire: 등록된 회사의 공개 채용보드를 브라우저로 확인하고 상세 자격요건까지 수집

직접 채용보드는 `backend/app/direct_ats_catalog.py`의 공통 카탈로그로 관리합니다. Git에 변경을
남기지 않고 회사를 추가하려면 `data/ats-boards.local.json`에 최대 200개까지 다음 형식으로 적습니다.
호스트는 지원하는 ATS의 공개 채용 도메인으로 제한되며 임의 URL, 사내 주소와 로그인 URL은 거부합니다.

```json
[
  {
    "source_name": "greeting",
    "company_name": "Example Company",
    "board_key": "example-company",
    "board_url": "https://example-company.career.greetinghr.com/ko/position"
  },
  {
    "source_name": "ashby",
    "company_name": "Example Global",
    "board_key": "exampleglobal",
    "board_url": "https://jobs.ashbyhq.com/exampleglobal"
  }
]
```

LinkedIn은 로그인 세션·자동화 제한이 있고 Wellfound는 공고별 지원 가능 국가가 불명확한 경우가 많아
정기 크롤러가 로그인하거나 제한을 우회하지 않습니다. 해당 채널에서 찾은 공개 공고는 회사가 사용하는
Greenhouse·Lever·Ashby 보드를 위 카탈로그에 추가하는 방식으로 수집 범위를 넓힙니다.

잡플래닛 수집은 `JobPlanetApiClient`가
`https://www.jobplanet.co.kr/api/v3/job/postings`의 JSON packet을 읽어 표준 dict로 정규화합니다.
별도 endpoint 환경변수는 필요하지 않습니다. `id`, `title`, `company.name`은 DB 저장에 필수이며
누락된 행은 실패 건수로 기록됩니다. 백엔드 개발과 소프트웨어 개발 직군을 최신순으로 요청하고,
화면의 무한 스크롤과 동일한 `page` 요청을 마지막 페이지 또는 `max_jobs`까지 순차적으로 보냅니다.
페이지 사이에는 설정된 크롤러 지연 시간을 적용합니다. 공고 링크는 잡플래닛의 실제 상세 형식인
`/job/search?posting_ids[]=공고ID`로 저장합니다.

```json
{
  "data": {
    "postings": [
      {
        "id": 12345,
        "title": "Python Backend Engineer",
        "company": {"name": "Example Company", "rate": 4.2},
        "location": "서울"
      }
    ]
  }
}
```

GUI와 별개로 일회성 수집·DB 저장·점수 분석·중복 그룹 갱신을 한 트랜잭션으로 실행하려면 프로젝트
루트에서 다음 명령을 사용합니다. source와 후보자 프로필이 아직 없다면 먼저 seed를 실행해야 합니다.

```bash
.venv/bin/python -m app.seed
.venv/bin/python -m app.jobplanet_sync --max-jobs 5000
```

명령은 신규·갱신·변경 없음·분석 건수와 중복 그룹 갱신 결과를 JSON으로 출력하며, 저장 또는 분석
도중 오류가 발생하면 해당 실행의 DB 변경을 모두 rollback합니다.

이미 로컬 JSON 배열로 정제된 데이터를 네트워크 호출 없이 upsert하고 기업별·지역별 통계를
집계하려면 다음 명령을 사용합니다. 각 행에 `source_name`이 없다면 seeded source를 `--source`로
지정합니다. 입력 파일은 Git에서 제외된 `data/*.local.json`에 둡니다.

```bash
.venv/bin/python -m app.tasks.sync_and_analyze \
  --input data/jobplanet-jobs.local.json \
  --source jobplanet
```


GUI에서 사이트를 복수 선택해 병렬 수집하고, 진행률·신규·갱신·실패 건수를 확인할 수 있습니다.
복수 사이트에 같은 공고가 올라오면 회사 법인표기(예: `(주)`/`주식회사`), 직무명 동의어
(`개발자`/`Engineer`, `백엔드`/`Backend`), 경력 범위와 역할 토큰을 비교해 한 묶음으로 표시합니다.
주니어·시니어가 충돌하거나 백엔드·데이터처럼 역할이 다른 공고는 별개로 유지합니다.
공고 검색, 인턴·신입·경력·경력무관 및 요구 연차 범위 필터, 기술 스택 복수 포함·제외,
공고에 명시된 코딩테스트 여부·면접 횟수 복수 필터, 최소 적합도·지원가치 필터, 숨김,
필터 결과 전체 건수와 현재 표시 건수 구분, DB에 저장되는 하트 관심 공고 전용 화면,
행별·선택 일괄 숨김과 숨긴 공고 복원 화면, 브라우저별 필터 자동 저장과 초기화,
최대 4개 비교, 적합도 근거, DB 기반 추천 채팅을 지원합니다. 점수 설명 버튼에서는
적합도와 지원가치의 차이, 계산 비중, 현재 포함되지 않은 요소를 확인할 수 있습니다.

## 회사 규모·재무·투자 정보

공고 목록에는 회사별 인원, 최근 공개 매출, 흑자·적자 여부와 최근 3년 투자 요약이 함께 표시됩니다.
공고의 `근거` 화면에서는 최근 3개년 매출·영업손익과 최근 3년 투자 라운드를 출처별로 확인할 수
있습니다. 공개되지 않은 금액은 추정하지 않고 `비공개` 또는 `미공시`로 구분합니다.

- 그룹바이 공개 회사 프로필: 현재 인원·개발 인원·투자 단계·공개 투자 라운드
- OpenDART: 최근 3개년 사업보고서의 매출·영업손익·당기순손익과 공시 직원 수

그룹바이 공개정보는 별도 인증 없이 매일 수집 후 보강됩니다. OpenDART 재무정보를 켜려면
[OpenDART 인증키](https://opendart.fss.or.kr/)를 발급받아 Git에서 제외된 `.env`에만 입력합니다.

```env
DART_API_KEY=
COMPANY_ENRICHMENT_MAX_GROUPBY=25
COMPANY_ENRICHMENT_MAX_DART=50
COMPANY_FACTS_REFRESH_DAYS=7
```

회사명은 공시 법인명과 정확히 일치하는 경우에만 자동 연결합니다. 동명이거나 브랜드명만 공개된
회사는 잘못된 재무정보를 붙이지 않고 미확인으로 남깁니다.

## 매일 자동 수집·오늘의 추천

Compose의 `scheduler` 서비스는 기본적으로 매일 오전 10시, 오후 1시, 오후 5시(Asia/Seoul)에
리멤버·데모데이·그룹바이·원티드·점핏·랠릿·잡플래닛과
Greenhouse·Lever·Ashby·Greeting·Ninehire 수집을
병렬로 시작합니다. Python·Node.js/TypeScript·Go 백엔드뿐 아니라 Product Engineer,
Product-minded Engineer, Founding Engineer, 풀스택·프로덕트 엔지니어 검색어와 역할 판정도 함께
사용합니다. 로컬에서 관심 또는 지원 완료로 표시한 기존 공고는 각 소스의 공개 목록 안에서 먼저
재확인하므로 수집 상한에 밀리지 않으며, 사라진 공고는 비활성화하되 지원 기록은 유지합니다. 수집 중 새로 저장된 공고만
점수 분석하고, 기존 공고는 다시 분석하지 않습니다. 모든 수집과 신규 분석이 끝나면
회사 공개정보를 보강하고, 활성·비숨김 공고 중 설정한 적합도와
지원가치 기준을 모두 넘긴 공고를 최대 10개 저장합니다. 최근 14일 안에 이미 추천된 공고는 다시
추천하지 않습니다.

GUI의 `최근 수집` 탭은 원문 게시일이 아니라 DB의 `first_seen_at`을 기준으로 최근 7일 안에
처음 발견된 공고만 보여줍니다. 따라서 게시일이 지난달이나 그 이전이어도 이번 주에 새로 수집했다면
7일 동안 이 탭과 `신규` 배지에 표시됩니다.

GUI 우측 상단의 `오늘의 추천` 알림에서 최신 추천과 날짜별 히스토리를 확인할 수 있습니다. 읽지 않은
새 추천이 있으면 브라우저별 배지가 표시됩니다. 추천 히스토리 DB에는 공고 참조와 그날의 집계 점수만
보관하며 이력서 원문, 후보자 근거, 연락처, 비공개 메모는 복제하지 않습니다.

상단의 `지금 추천받기`는 재수집 없이 현재 DB의 활성·비숨김 공고를 즉시 다시 큐레이션합니다.
오늘의 추천 화면에서는 같은 결과를 조건형 추천 채팅으로 더 좁히거나, 공개 공고 정보와 집계 점수만
담은 Markdown 리포트로 로컬 저장할 수 있습니다. 즉시 추천은 Slack을 자동 전송하지 않습니다.

### 초기 투자사·창업 프로그램 모니터

상단 `창업 프로그램` 페이지에는 get-job의 현재 제품·단계와의 적합도, 추천 이유, 핵심 투자 태그를 기준으로
프라이머, 뉴키즈인베스트먼트, 디캠프, 스파크랩, 매쉬업벤처스,
씨엔티테크, 퓨처플레이, MYSC, 소풍벤처스, D3쥬빌리파트너스, 임팩트스퀘어, 카카오벤처스,
NAVER D2SF 등 초기 투자·지원 기관을 정리합니다. 벤처투자종합포털(VCS)의
`ICT서비스 + AI·빅데이터 + 창업초기 + 업력 0~3년` 검색에서 확인된 투자사와 운용규모·근거 링크도
함께 보여줍니다. 안정적인 공개 모집 페이지가 확인된 기관은 매일 자동 확인하며, VCS 공지·벤처투자마트를
포함해 새로 발견된 투자 검토·배치·교육·IR·데모데이·선발 공고는 최근 7일 동안 `신규`로 표시됩니다.
수동 `프로그램 수집`도 가능합니다.

실행 시각과 추천 기준은 Git에서 제외된 `.env`에서 바꿀 수 있습니다.

```env
DAILY_DIGEST_ENABLED=true
DAILY_DIGEST_TIMES=10:00,13:00,17:00
DAILY_DIGEST_TIMEZONE=Asia/Seoul
DAILY_RECOMMENDATION_LIMIT=10
DAILY_RECOMMENDATION_MIN_FIT=70
DAILY_RECOMMENDATION_MIN_VALUE=70
DAILY_RECOMMENDATION_COOLDOWN_DAYS=14
```

### 공고 최초 발견 시각 측정

기존 10시·13시·17시 수집 시간표를 유지하면서 공고 상세를 파싱한 시각과 DB 최초 저장 시각을
별도로 기록합니다. 시각은 내용 해시에서 제외하므로 재조회만으로 공고가 변경된 것으로 처리되지
않습니다. `GET /api/crawl/timing?days=30`은 사이트별 최초 발견 시간대, 수집 요청 시간대,
수집 성공·부분·실패 건수와 저장 지연을 보여줍니다. 기존 데이터는 최초 저장 시각만 있는 추정치로
구분하며, 보고서에는 이력서나 후보자 데이터가 포함되지 않습니다.

최초 대량 가져오기는 게시 시간 측정으로 사용할 수 없습니다. 하루 세 번의 관측은 수집 시간에
분포가 치우치므로 이를 실제 게시 시간으로 해석하거나 자동으로 시간표를 바꾸지 않습니다.
최소 14일 관측 후, 사이트가 제공한 게시 시각의 정밀도·실제 공개 시각 또는 허용된 더 촘촘한
공개 목록 관측을 확인하여 그 이후 실행하는 시간표를 정합니다.

작업 디렉터리에 필수 파일이 빠져 있다면 `python3 scripts/prepare_local_runtime.py`로
`data/runtime.local/`에 현재 소스와 Git HEAD의 누락 파일을 합친 실행 스냅샷을 만들 수 있습니다.
원본 디렉터리의 다른 누락 파일은 덮어쓰지 않습니다. 소스 변경 후에는 스냅샷을 다시 생성해야 합니다.

호스트 cron으로 실행할 때는 `.env`의 `DAILY_DIGEST_ENABLED=false`로 Docker의 반복 스케줄러를
끄고 `scripts/run_collection_cycle.py`를 10시·13시·17시에 실행합니다. 호스트 시간대는
Asia/Seoul이어야 합니다. OS 파일 잠금으로 중복 실행을 막으며, 각 실행 뒤 공개 시각 집계를
`data/collection-timing.local/`에 저장합니다. 컴퓨터가 켜져 있고 Docker와 백엔드가 실행 중이어야
수집합니다. 컴퓨터가 잠든 동안 지나간 cron 실행은 소급 실행하지 않습니다.

### Slack 알림을 명시적으로 켜는 경우

Slack은 공개 저장소 기본값에서 꺼져 있습니다. 실제 값은 채팅·문서·소스가 아니라 로컬 `.env`에만
입력하세요. Incoming Webhook 또는 bot token과 channel ID 중 하나를 사용할 수 있습니다.

```env
SLACK_NOTIFY_ENABLED=true
SLACK_WEBHOOK_URL=
# 또는
SLACK_BOT_TOKEN=
SLACK_CHANNEL_ID=
```

Webhook은 정확한 `hooks.slack.com`의 Incoming Webhook 주소만, bot 방식은 Slack의 고정 API 주소와
지정된 채널만 사용합니다. 메시지에는 회사·공고명·공개 URL·기술 스택·집계 점수만 포함되며 개인
이력서와 매칭 근거는 포함되지 않습니다. 설정이 없거나 꺼져 있어도 수집과 오늘의 추천 저장은 계속
작동합니다.

## 보안 운영 원칙

이 앱은 인증이 없는 로컬 단일 사용자 도구입니다. `0.0.0.0` 바인딩, 포트 포워딩, 공개 서버 배포를
하지 마세요. 공개 배포가 필요하면 인증·권한·rate limit·TLS가 먼저 필요합니다.
자동화 규칙은 `AGENTS.md`, 보안 정책과 외부 AI 동의 조건은 `SECURITY.md`를 확인하세요.
공개 push 전에는 `./scripts/security-check.sh`를 실행하세요. 이 검사는 Git에 올라간 민감 파일명과
credential 패턴을 값 자체를 출력하지 않고 검사하며, 필수 로컬 파일의 ignore 여부도 확인합니다.

## 로컬 개발과 검증

Python 3.12 이상과 Node.js 22 이상을 권장합니다.

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'backend[dev,crawler]'
cd backend
../.venv/bin/pytest
../.venv/bin/ruff check .
```

```bash
cd frontend
npm install
npm run build
```

Backend API에는 `GET /api/ai/status`, `POST /api/ai/jobs/{job_id}/evidence`,
`POST /api/recommendations/chat`, 사이트별 `POST /api/crawl/{source}`,
`GET /api/daily-recommendations`, `GET /api/daily-recommendations/dates`,
`GET /api/ecosystem/organizations`, `GET /api/ecosystem/programs`,
`POST /api/ecosystem/crawl`가 포함됩니다.

리멤버만 단독으로 확인하려면 `python -m app.cli crawl remember --headless`를 사용할 수 있습니다.
리멤버의 페이지 정책이나 공개 URL 구조가 바뀌면 수집은 실패로 기록되며, 로그인이나 CAPTCHA 우회는
시도하지 않습니다.

## 현재 제한

- 수집 사이트의 정책과 HTML/API 구조 변경에 따라 adapter 유지보수가 필요합니다.
- 회사 현황은 지원 판단용 참고자료이며 연봉·회사 안정성·출퇴근 비용과 함께 지원가치 점수에는
  아직 포함되지 않습니다.
- 최초 공개 전에 저장소 소유자가 MIT 또는 Apache-2.0 등의 LICENSE를 선택해야 합니다.

개인 수집의 robots 검사 여부는 `CRAWLER_RESPECT_ROBOTS`로 명시적으로 선택합니다(기본 true). 사용자 요청으로 이 컴퓨터의 로컬 설정은 false이며 공개 페이지에만 사용합니다. HTML 요청은 2~6초 간격, 원티드 API 요청 시작은 0.5~1.5초 간격으로 분산합니다. 429/503 응답은 Retry-After를 기다린 뒤 제한된 횟수만 재시도합니다. robots 검사 설정과 무관하게 허용 호스트와 리다이렉트 검증은 유지합니다.

`DAILY_RECOMMENDATION_PREFER_ESTABLISHED=true`인 로컬 추천에서는 직원 30명 이상·Series A 이후 확인 회사를 먼저 정렬하고, 규모 미확인을 직원 한 자릿수 회사와 구분합니다. 기본 저장소 설정에서는 기존 점수 순서를 유지합니다.

공고 목록의 기술·경력 필터는 제목·기술·경력 등 작은 컬럼만 먼저 읽고 페이지의 공고에 대해서만 목록 데이터를 로드합니다. 본문과 점수 설명 JSON을 모든 후보에 대해 역직렬화하지 않습니다. 기존 기술 경계 매칭과 연차 범위 겹침 규칙은 유지합니다. 기술·경력 필터는 경량 후보를 Python에서 판별하므로 후보 수에 비례하는 비용은 남습니다.

소스 제외는 `exclude_source=jobplanet&exclude_source=wanted`처럼 여러 값을 지정합니다. 포함 출처와 함께 지정할 때 제외가 우선하며 화면에서는 동일 출처를 포함/제외로 중복 선택하지 않게 합니다. 제외 선택은 다른 필터와 함께 브라우저에 저장되고 필터 초기화로 해제됩니다.

응답 시간은 `python scripts/benchmark_job_filters.py --samples 5 --output data/filter-performance.local/results.json`으로 같은 데이터에서 반복 측정할 수 있습니다. 결과에는 시간과 건수만 저장합니다. `test_job_filter_performance.py`는 3,000개 합성 공고에서 상세 로딩 개수, 제외 필터와 페이지 결과, 이전 전체 상세 스캔 대비 중앙값 개선과 조회 시간 예산을 검증합니다. 실제 PostgreSQL용 활성·노출 공고 정렬 인덱스는 `20261009_0013` 마이그레이션에 포함됩니다.

게시 기간 필터는 실제 게시일이 확인된 공고만 기본 포함합니다. `include_unknown_posted=true`를 함께 지정하면 게시일 미확인 공고도 포함하되, 확인된 오래된 공고는 제외합니다. 수집일을 게시일로 대체하지 않습니다. 화면의 “게시일 미확인 공고 포함” 선택은 브라우저에 저장되며 초기화할 수 있습니다.
