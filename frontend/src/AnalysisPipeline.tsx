import { useMutation, useQueryClient } from "@tanstack/react-query";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

type Report = {
  summary: string;
  requirements: { id: string; title: string; kind: string; quote: string }[];
  matches: {
    requirement_id: string;
    status: "supported" | "partial" | "unknown";
    candidate_source_ids: string[];
    explanation: string;
    next_step: string;
  }[];
  candidate_sources: Record<string, string>;
  steps: { name: string; attempts: number; duration_ms: number }[];
  model_calls: number;
  model: string;
  cached: boolean;
  local_only: boolean;
  outcome: string;
  notice: string;
  input_tokens: number | null;
  output_tokens: number | null;
  reserved_tokens: number;
  omitted_requirements: number;
  candidate_sources_considered: number;
  candidate_sources_selected: number;
};

const statusLabels = { supported: "직접 근거", partial: "부분 근거", unknown: "확인 필요" };
const stepLabels: Record<string, string> = {
  extract_requirements: "요구사항 추출·인용 검증",
  match_evidence: "이력서 매칭·근거 검증",
  finalize_report: "보고서 정리",
  prepare_and_retrieve: "규칙 추출·관련 경력 검색",
  fast: "기본 모델 분석·인용 검증",
  review: "재검토 모델 분석·인용 검증",
};

export function AnalysisPipeline({ jobId }: { jobId: number }) {
  const queryClient = useQueryClient();
  const analysis = useMutation<Report, Error, boolean>({
    mutationFn: async (refresh) => {
      const response = await fetch(
        `${API_URL}/api/ai/analysis/jobs/${jobId}?refresh=${refresh}`,
        { method: "POST" },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === "string"
        ? payload.detail : "심층 분석을 완료하지 못했습니다.");
      return payload;
    },
    retry: false,
    onSettled: () => { void queryClient.invalidateQueries({ queryKey: ["analysis-usage"] }); },
  });
  return <section className="interview-prep-section" aria-label="공고 심층 분석">
    <div className="interview-prep-head">
      <div><p>ECONOMY ANALYSIS</p><h3>공고 심층 분석</h3><span>관련 경력만 골라 기본 모델로 분석하고, 모호한 경우에만 재검토합니다. 모델 호출은 최대 2회입니다.</span></div>
      <button type="button" disabled={analysis.isPending}
        onClick={() => analysis.mutate(Boolean(analysis.data))}>
        {analysis.isPending ? "분석 중…" : analysis.data ? "다시 분석" : "심층 분석 실행"}
      </button>
    </div>
    <div aria-live="polite">
      {analysis.isPending && <p className="local-ai-loading">요구사항 추출 → 이력서 근거 매칭 → 인용 검증 → 보고서 정리 중입니다. 여러 단계로 진행되어 잠시 걸릴 수 있습니다.</p>}
      {analysis.isError && <p className="interview-prep-error">{analysis.error.message}</p>}
      {!analysis.data && !analysis.isPending && <p className="interview-prep-empty">분석 예산에 설정된 모델을 사용합니다. 단순 기술명은 규칙으로 처리하고 저장된 결과는 재사용합니다.</p>}
    </div>
    {analysis.data && <>
      <p className="local-ai-summary">{analysis.data.summary}</p>
      {analysis.data.notice && <p className="question-caution">{analysis.data.notice}</p>}
      <p className="question-intent">관련 경력 {analysis.data.candidate_sources_considered}개 중 {analysis.data.candidate_sources_selected}개 선택 · 이번 호출 {analysis.data.cached ? 0 : analysis.data.model_calls}회{analysis.data.omitted_requirements > 0 ? ` · 나머지 요구사항 ${analysis.data.omitted_requirements}개는 원문에서 확인하세요.` : ""}</p>
      <div className="interview-question-list">{analysis.data.requirements.map((requirement) => {
        const match = analysis.data!.matches.find((item) => item.requirement_id === requirement.id);
        return <article className="interview-question" key={requirement.id}>
          <div><span>{requirement.kind === "required" ? "필수 요건" : requirement.kind === "preferred" ? "우대 요건" : "담당 업무"}</span><b>{match ? statusLabels[match.status] : "확인 필요"}</b></div>
          <h4>{requirement.title}</h4>
          <p className="question-intent">공고 인용 · {requirement.quote}</p>
          {match && <>
            <p>{match.explanation}</p>
            {match.candidate_source_ids.length > 0 && <ul>{match.candidate_source_ids.map((id) =>
              <li key={id}>{analysis.data!.candidate_sources[id]}</li>)}</ul>}
            <p className="question-caution">지원 전 준비 · {match.next_step}</p>
          </>}
        </article>;
      })}</div>
      <details><summary>분석 과정 확인</summary><ol>{analysis.data.steps.map((step) =>
        <li key={step.name}>{stepLabels[step.name] ?? step.name} · {step.attempts}회 시도 · {(step.duration_ms / 1000).toFixed(1)}초</li>)}</ol></details>
      <small className="local-ai-privacy">생성 시 예산 예약량 {analysis.data.reserved_tokens.toLocaleString()} · {analysis.data.input_tokens == null || analysis.data.output_tokens == null ? "실사용 토큰 미제공" : `실사용 입력 ${analysis.data.input_tokens.toLocaleString()} / 출력 ${analysis.data.output_tokens.toLocaleString()} 토큰`}</small>
      <small className="local-ai-privacy">{analysis.data.cached ? "저장된 결과 재사용" : "새 분석 완료"} · {analysis.data.model} · 생성 시 모델 호출 {analysis.data.model_calls}회 · {analysis.data.local_only ? "로컬 AI 처리" : "외부 AI 사용 허용됨"}. 인용 검증은 원문 존재 여부를 확인하며, 해석의 정확성은 직접 검토해 주세요.</small>
    </>}
  </section>;
}
