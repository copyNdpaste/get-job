'use strict';

// This guide uses only synthetic, in-memory examples. It never calls service APIs.
const stages = [
  [['INPUT', '공개 채용 페이지·API', '등록된 소스의 공고 URL, 공개 JSON 또는 직접 가져온 HTML을 받습니다.'], ['PROCESS', '소스별 수집기로 읽기', '페이지 구조와 허용 방식에 맞는 어댑터로 제목·본문·회사 정보를 읽습니다.'], ['OUTPUT', '출처가 있는 공고', '어느 사이트에서 가져왔는지와 원문 URL을 함께 보관합니다.']],
  [['INPUT', '서로 다른 형태의 원문', '같은 자격요건도 사이트마다 제목과 HTML 구조가 다릅니다.'], ['PROCESS', '공통 항목으로 분리', '업무·필수·우대·기술·경력을 나누고 공백, 회사명, 추적 URL을 정리합니다.'], ['OUTPUT', 'CollectedJob', '동일한 필드로 비교하고 저장할 수 있는 구조화된 공고가 됩니다.']],
  [['INPUT', '정규화한 공고', '소스 ID, URL, 회사와 제목 등 식별 정보를 확인합니다.'], ['PROCESS', '갱신·이력·중복 그룹화', '내용 해시로 변경을 확인합니다. 여러 소스의 유사 공고는 별도 그룹으로 묶습니다.'], ['OUTPUT', '공고 DB와 스냅샷', '현재 내용과 변경 이력, 원문 출처가 남습니다. 중복 공고 원본을 삭제하지 않습니다.']],
  [['INPUT', '공고 + 구조화된 경력', '직무, 기술, 경험과 필수 조건을 비교합니다.'], ['PROCESS', '정해진 규칙으로 계산', '적합도와 지원가치를 산출하고, 공고에 맞는 이력서 버전을 추천합니다.'], ['OUTPUT', '점수와 추천 근거', 'AI를 부르기 전에도 공고를 정렬하고 살펴볼 수 있습니다.']],
  [['INPUT', '요구사항 + 선택한 근거', '완료 캐시를 먼저 확인하고, 필요한 경력 항목만 추립니다.'], ['PROCESS', 'LangGraph 조건부 분석', 'LangChain Core로 질문을 구성합니다. 규칙 0회, 기본 1회, 재검토 포함 최대 2회입니다.'], ['OUTPUT', '검증된 형식의 보고서', '요구사항별 근거, 확인할 점, 호출량을 담습니다. 의미가 정확한지는 원문과 함께 확인합니다.']],
  [['INPUT', '점수·보고서·기업 정보', '정량 점수와 AI 해석, 공개 출처를 함께 봅니다.'], ['PROCESS', '사람이 선택하고 준비', '우선 공고를 고르고, 사용할 경력과 이력서 버전, 추가 확인 사항을 정합니다.'], ['OUTPUT', '지원 준비와 진행 관리', '관심·지원 상태를 추적합니다. 외부 지원서 제출은 사용자가 진행합니다.']],
];

const stageButtons = [...document.querySelectorAll('[data-stage]')];
function selectStage(index) {
  stageButtons.forEach((button, i) => {
    button.classList.toggle('selected', i === index);
    button.setAttribute('aria-pressed', String(i === index));
  });
  document.getElementById('stage-detail').innerHTML = stages[index].map(([label, title, description]) =>
    `<div><span class="detail-label">${label}</span><h3>${title}</h3><p>${description}</p></div>`).join('');
}
stageButtons.forEach(button => button.addEventListener('click', () => selectStage(Number(button.dataset.stage))));
selectStage(0);

const sources = [
  { name: '데모데이', mark: 'D', category: 'http', method: '공개 페이지 / HTTP', note: '목록·상세 페이지 파싱' },
  { name: 'GroupBy', mark: 'G', category: 'browser', method: '브라우저 보조', note: '공개 채용·기업 정보' },
  { name: '원티드', mark: 'W', category: 'browser', method: '브라우저 보조', note: '소스별 공개 공고 수집' },
  { name: '리멤버', mark: 'R', category: 'browser', method: '브라우저 보조', note: '소스별 공개 공고 수집' },
  { name: '점핏', mark: 'J', category: 'http', method: '공개 페이지 / HTTP', note: '개발자 채용 정보' },
  { name: '랠릿', mark: 'R', category: 'http', method: '공개 페이지 / HTTP', note: '소스별 공고 파싱' },
  { name: '잡플래닛', mark: 'J', category: 'http', method: '공개 JSON', note: '공개 채용 데이터 처리' },
  { name: 'Greenhouse', mark: 'G', category: 'api', method: '공개 ATS API', note: '등록된 기업 채용 보드' },
  { name: 'Lever', mark: 'L', category: 'api', method: '공개 ATS API', note: '등록된 기업 채용 보드' },
  { name: 'Ashby', mark: 'A', category: 'api', method: '공개 ATS API', note: '등록된 기업 채용 보드' },
  { name: 'Greeting', mark: 'G', category: 'browser', method: '브라우저 보조', note: '허용된 기업별 채용 주소' },
  { name: 'Ninehire', mark: 'N', category: 'browser', method: '브라우저 보조', note: '허용된 기업별 채용 주소' },
  { name: '사람인', mark: 'S', category: 'limited', method: '승인된 API', note: '접근 승인·키 설정 필요' },
  { name: '로켓펀치', mark: 'R', category: 'limited', method: '수동 HTML 입력', note: '자동 크롤링 대상 아님' },
];
const sourceButtons = [...document.querySelectorAll('[data-source]')];
function selectSources(category) {
  sourceButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.source === category)));
  const selected = sources.filter(source => category === 'all' || source.category === category);
  document.getElementById('sources-grid').innerHTML = selected.map(source => `<article class="source-card"><span class="source-mark" aria-hidden="true">${source.mark}</span><div><h3>${source.name}</h3><small>${source.method}</small><p>${source.note}</p></div></article>`).join('');
  document.getElementById('source-count').textContent = `${selected.length}개 등록 소스 · 실제 수집 가능 여부는 설정과 소스 정책에 따릅니다.`;
}
sourceButtons.forEach(button => button.addEventListener('click', () => selectSources(button.dataset.source)));
selectSources('all');

const journeyViews = [
  `<div class="example-header"><b>가상의 채용 페이지</b><span>원문 형태 · 이해를 위한 축약</span></div><div class="example-body"><span class="pill">예시테크 · 가상 회사</span><h3>Python 백엔드 엔지니어</h3><p>주문 서비스를 함께 만들 개발자를 찾습니다.</p><h4>주요 업무</h4><ul><li>Python·FastAPI로 주문 API 개발</li><li>PostgreSQL 데이터 모델 설계와 운영</li></ul><h4>필수 요건 / 우대 사항</h4><ul><li>Python API 개발 경험</li><li>대규모 트래픽 운영 경험 우대</li></ul><p class="raw-url">https://careers.example.com/jobs/backend?utm_source=board</p><p class="example-caption">수집기는 이 원문에서 공고 항목을 읽습니다. 분석 모델이 웹 전체를 직접 탐색하는 과정은 아닙니다.</p></div>`,
  `<div class="example-header"><b>정규화된 CollectedJob</b><span>코드로 분리 · LLM 0회</span></div><div class="example-body"><dl class="field-table"><div><dt>회사<code>company_name</code></dt><dd>예시테크</dd></div><div><dt>제목<code>title</code></dt><dd>Python 백엔드 엔지니어</dd></div><div><dt>필수 요건<code>requirements</code></dt><dd>Python API 개발 경험</dd></div><div><dt>우대 사항<code>preferred_requirements</code></dt><dd>대규모 트래픽 운영 경험</dd></div><div><dt>주요 업무<code>main_tasks</code></dt><dd>FastAPI 주문 API 개발<br>PostgreSQL 설계·운영</dd></div><div><dt>기술<code>tech_stack</code></dt><dd>Python · FastAPI · PostgreSQL</dd></div></dl><p class="example-caption"><b>정규화</b>는 다른 양식을 같은 항목으로 정리하는 일입니다. 저장할 때 추적 파라미터를 제거한 canonical URL을 별도로 만들고, 내용 해시로 변경을 확인합니다.</p></div>`,
  `<div class="example-header"><b>요구사항별 분석 보고서</b><span>설명용 가상 결과</span></div><div class="example-body"><div class="match-card"><div class="match-head"><b>R1 · Python API 개발 경험</b><span class="pill">supported · 근거 있음</span></div><p>API를 개발한 경력이 요구사항과 연결됩니다.</p><blockquote><b>C1 · achievements[0].evidence</b><br>“Python·FastAPI로 주문 API를 만들고 PostgreSQL을 운영했다.”</blockquote></div><div class="match-card"><div class="match-head"><b>R2 · 대규모 트래픽 운영</b><span class="pill unknown">unknown · 확인 필요</span></div><p>운영 경험은 있지만 트래픽 규모를 입증하는 내용은 없습니다. 실제 처리량과 장애 대응 사례를 확인하세요.</p></div><p class="example-caption"><b>근거 ID</b>는 경력의 어떤 항목을 인용했는지 가리키는 주소입니다. “기재되지 않음”을 “경험 없음”으로 단정하지 않습니다. 이 화면은 두 요구사항만 보여주는 축약 예시입니다.</p></div>`,
];
const journeyButtons = [...document.querySelectorAll('[data-journey]')];
function selectJourney(index) {
  journeyButtons.forEach((button, i) => button.setAttribute('aria-pressed', String(i === index)));
  document.getElementById('journey-content').innerHTML = journeyViews[index];
}
journeyButtons.forEach(button => button.addEventListener('click', () => selectJourney(Number(button.dataset.journey))));
selectJourney(0);

// Counts are explanatory model completions, not network telemetry or cost estimates.
const makeStep = (node, label, title, description, calls) => ({ node, label, title, description, calls });
const cacheMiss = () => makeStep('cache', '캐시 조회', '같은 분석을 이미 했나요?', '공고·경력·점수·모델·정책을 묶은 해시로 완료 보고서를 찾습니다. 이 상황은 일치하는 캐시가 없다고 가정합니다.', 0);
const prepare = () => makeStep('prepare', '준비', 'AI에게 필요한 부분만 건넵니다.', '정규화된 필드에서 요구사항을 추리고, 단어가 겹치는 경력 근거를 고릅니다. 프롬프트 한도에 맞게 줄이는 작업까지 코드가 담당합니다.', 0);
function buildRoute(scenario, reviewEnabled) {
  if (scenario === 'cache') return [makeStep('cache', '캐시 재사용', '저장된 보고서를 바로 읽습니다.', '입력·점수·모델·정책이 같은 완료 보고서가 있습니다. LangGraph를 다시 실행하지 않고 기존 결과를 반환합니다. 이번 요청의 모델 호출은 0회입니다.', 0)];
  const route = [cacheMiss(), prepare()];
  if (scenario === 'rules') {
    route[1] = makeStep('prepare', '규칙 일치', '짧은 기술명이 모두 직접 일치합니다.', '예: 요구사항이 “Python”이고 선택된 경력의 기술 항목도 “Python”입니다. 모든 요구사항이 이 규칙으로 충족되면 문장 해석 모델을 건너뜁니다.', 0);
    route.push(makeStep('finalize', '규칙 보고서', '모델 없이 결과를 정리합니다.', 'rules_only 보고서를 만듭니다. 정확한 기술명 일치를 보여주는 결과이며, 복잡한 업무 수행 능력까지 보장하는 판정은 아닙니다.', 0));
    return route;
  }
  if (scenario === 'budget') {
    route.push(makeStep('fast', '예약 실패', '호출하기 전에 한도가 막습니다.', '모델은 사용 가능하지만 오늘의 남은 예약량이 부족한 상황입니다. DB의 조건부 예약이 실패하여 모델 응답 요청은 보내지 않습니다.', 0));
    route.push(makeStep('finalize', '예산 제한', '현재 근거와 제한 사유를 돌려줍니다.', 'budget_limited 상태로 끝납니다. 한도 제한 결과는 완료 캐시에 남기지 않아, 나중에 여건이 바뀌면 다시 분석할 수 있습니다.', 0));
    return route;
  }
  if (scenario === 'offline') {
    route.push(makeStep('fast', '연결 실패', '예약 후, 분석 요청이 실패했습니다.', '모델의 사전 상태 확인과 예약은 성공했지만 실제 completion 연결이 실패했다고 가정합니다. 호출을 시도했으므로 예약은 유지되고 실제 토큰은 미제공일 수 있습니다.', 1));
    route.push(makeStep('finalize', '사용 불가', '상위 모델로 자동 재시도하지 않습니다.', 'unavailable 상태와 연결 실패 사유를 표시합니다. 네트워크 실패는 더 비싼 모델을 호출하는 조건이 아닙니다.', 1));
    return route;
  }
  const ambiguous = scenario === 'review';
  const invalid = scenario === 'invalid';
  route.push(makeStep('fast', invalid ? '검증 실패' : ambiguous ? '모호한 결과' : '기본 분석', invalid ? '인용한 근거가 실제 입력에 없습니다.' : ambiguous ? '연결은 있지만, 근거가 충분하지 않습니다.' : '기본 모델이 요구사항과 경력을 비교합니다.', invalid ? '모델이 입력에 없던 경력 ID를 반환했다고 가정합니다. Pydantic과 근거 ID 검증에서 걸러지며, 검증을 통과한 답변으로 채택하지 않습니다.' : ambiguous ? 'partial 또는 근거를 인용한 unknown이 절반 이상인 결과를 가정합니다. 프로그램의 조건식이 재검토 후보로 분류합니다.' : '예산을 예약하고 LangChain Core가 만든 질문을 보냅니다. 결과 형식과 모든 요구사항의 포함 여부, 실제 경력 ID 인용을 검증합니다.', 1));
  if (ambiguous || invalid) {
    if (reviewEnabled) {
      route.push(makeStep('review', '선택적 재검토', '다른 모델에게 한 번 더 맡깁니다.', '별도의 재검토 모델이 설정되어 있고, 배치·일일 한도와 예약 예산이 남았다고 가정합니다. 같은 제한된 근거로 분석하고 다시 검증합니다.', 2));
      route.push(makeStep('finalize', '재검토 결과', '두 번으로 분석을 마칩니다.', '이 예시는 재검토가 유효하고 명확한 결과를 냈다고 가정합니다. 다시 모호하거나 검증에 실패하면 확인 필요 상태로 끝내며 세 번째 호출은 하지 않습니다.', 2));
    } else {
      route.push(makeStep('finalize', '확인 필요', '재검토를 허용하지 않아 여기서 끝냅니다.', 'needs_review 상태와 사유를 표시합니다. 불확실성을 숨기지 않고 기본 분석 또는 규칙 근거를 제시합니다. 잘못된 인용의 결과는 완료 캐시에 저장하지 않습니다.', 1));
    }
  } else {
    route.push(makeStep('finalize', '완료', '한 번의 호출로 충분했습니다.', '유효하고 명확한 분석 결과를 보고서로 정리합니다. 인용된 경력 항목과 사용량을 담고, 같은 입력에서 재사용할 완료 캐시를 저장합니다.', 1));
  }
  return route;
}

const scenarioSelect = document.getElementById('scenario');
const reviewToggle = document.getElementById('review-enabled');
const playButton = document.getElementById('run-simulation');
const nextButton = document.getElementById('sim-next');
let route = [];
let stepIndex = 0;
let playback = null;
function stopPlayback() {
  clearInterval(playback);
  playback = null;
  playButton.innerHTML = '흐름 재생 <span aria-hidden="true">▶</span>';
}
function renderStep() {
  const step = route[stepIndex];
  document.querySelectorAll('[data-graph]').forEach(node => {
    const name = node.dataset.graph;
    node.classList.toggle('current', name === step.node);
    node.classList.toggle('visited', route.slice(0, stepIndex).some(item => item.node === name));
    node.classList.toggle('skipped', !route.some(item => item.node === name));
    if (name === step.node) node.setAttribute('aria-current', 'step');
    else node.removeAttribute('aria-current');
  });
  document.getElementById('sim-progress').textContent = `${stepIndex + 1} / ${route.length} 단계`;
  document.getElementById('sim-state').textContent = step.label;
  document.getElementById('sim-calls').textContent = String(step.calls);
  document.getElementById('sim-title').textContent = step.title;
  document.getElementById('sim-description').textContent = step.description;
  document.getElementById('sim-route').innerHTML = route.map((item, i) => `<li class="${i === stepIndex ? 'active' : ''}" ${i === stepIndex ? 'aria-current="step"' : ''}>${i + 1}. ${item.label}</li>`).join('');
  nextButton.disabled = stepIndex === route.length - 1;
  if (nextButton.disabled) stopPlayback();
}
function resetSimulation() {
  stopPlayback();
  route = buildRoute(scenarioSelect.value, reviewToggle.checked);
  stepIndex = 0;
  renderStep();
}
scenarioSelect.addEventListener('change', resetSimulation);
reviewToggle.addEventListener('change', resetSimulation);
document.getElementById('sim-reset').addEventListener('click', resetSimulation);
nextButton.addEventListener('click', () => {
  stopPlayback();
  if (stepIndex < route.length - 1) stepIndex += 1;
  renderStep();
});
playButton.addEventListener('click', () => {
  if (playback) return stopPlayback();
  if (stepIndex === route.length - 1) stepIndex = 0;
  renderStep();
  if (route.length === 1) return;
  playButton.innerHTML = '일시 정지 <span aria-hidden="true">Ⅱ</span>';
  playback = setInterval(() => { stepIndex += 1; renderStep(); }, 4200);
});
document.addEventListener('visibilitychange', () => { if (document.hidden) stopPlayback(); });
resetSimulation();

// Keep navigation tied to reading position without triggering layout or navigation.
const sections = [...document.querySelectorAll('main > section[id]')];
const navLinks = [...document.querySelectorAll('nav a')];
let scheduled = false;
function updateNavigation() {
  const current = sections.filter(section => section.getBoundingClientRect().top <= 140).at(-1) || sections[0];
  navLinks.forEach(link => {
    if (link.hash === `#${current.id}`) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
  scheduled = false;
}
window.addEventListener('scroll', () => {
  if (!scheduled) { scheduled = true; requestAnimationFrame(updateNavigation); }
}, { passive: true });
updateNavigation();

document.getElementById('print-guide').addEventListener('click', () => window.print());
document.getElementById('copy-resume').addEventListener('click', async () => {
  const text = document.getElementById('resume-text').textContent.trim();
  const status = document.getElementById('copy-status');
  try {
    await navigator.clipboard.writeText(text);
    status.textContent = '문장을 복사했습니다.';
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(document.getElementById('resume-text'));
    selection.removeAllRanges();
    selection.addRange(range);
    status.textContent = '선택된 문장을 직접 복사해 주세요.';
  }
});
