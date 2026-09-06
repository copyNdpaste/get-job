import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

type Usage = {
  day: string; daily_budget: number; reserved_tokens: number; calls: number; reviews: number;
  input_tokens: number | null; output_tokens: number | null; usage_complete: boolean;
  fast_model: string; review_model: string | null; batch_size: number; after_crawl: boolean;
  output_limit: number; output_limit_enforced: boolean;
};
type Batch = { fresh: number; cached: number; model_calls: number; reviews: number;
  items: { job_id: number; outcome: string; cached: boolean }[] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}/api/ai/analysis/${path}`, init);
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "분석 요청 실패");
  return body;
}

export function AnalysisBudgetPanel({ onClose, onEvidence }: {
  onClose: () => void; onEvidence: (id: number) => void;
}) {
  const queryClient = useQueryClient();
  const usage = useQuery({ queryKey: ["analysis-usage"], queryFn: () => request<Usage>("usage"), retry: false });
  const batch = useMutation({
    mutationFn: () => request<Batch>("batch", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: usage.data?.batch_size ?? 10 }) }),
    onSettled: () => { void queryClient.invalidateQueries({ queryKey: ["analysis-usage"] }); },
    retry: false,
  });
  const labels: Record<string, string> = { validated: "검증 완료", rules_only: "규칙 분석",
    needs_review: "직접 확인 필요", budget_limited: "예산 한도", unavailable: "모델 미연결", invalid_input: "입력 확인 필요" };
  return <section className="interview-prep-section analysis-budget-panel" aria-label="수집 데이터 AI 분석">
    <div className="interview-prep-head"><div><p>ANALYSIS BUDGET</p><h3>수집 데이터 AI 분석</h3><span>활성 공고 중 규칙 점수가 높은 순서로 분석합니다. 저장된 결과를 재사용하고 새로운 분석 건수를 제한합니다.</span></div><button onClick={onClose}>닫기</button></div>
    {usage.isError && <p className="interview-prep-error">{usage.error.message}</p>}
    {usage.data && <>
      <p>기본 모델 <b>{usage.data.fast_model}</b> · 재검토 <b>{usage.data.review_model ?? "사용 안 함"}</b></p>
      <p>{usage.data.day} UTC · 예산 예약 {usage.data.reserved_tokens.toLocaleString()} / {usage.data.daily_budget.toLocaleString()} · 호출 {usage.data.calls}회 · 재검토 {usage.data.reviews}회</p>
      <small className="local-ai-privacy">예약량은 과다 호출을 막기 위한 보수적인 계획치입니다. {usage.data.usage_complete && usage.data.input_tokens != null && usage.data.output_tokens != null ? `실사용 입력 ${usage.data.input_tokens.toLocaleString()} / 출력 ${usage.data.output_tokens.toLocaleString()} 토큰.` : "실사용 토큰이 없거나 일부 요청에서 제공되지 않았습니다."} {usage.data.output_limit_enforced ? `출력 상한 ${usage.data.output_limit} 토큰을 서버에 전달합니다.` : "Codex 출력 한도는 요청 수준이며 실제 과금 상한을 보장하지 않습니다."}</small>
      <p>수집 후 자동 분석: {usage.data.after_crawl ? "켜짐" : "꺼짐"}</p>
      <button className="analysis-action-button" disabled={batch.isPending} onClick={() => batch.mutate()}>{batch.isPending ? "순차 분석 중…" : `상위 공고 분석 · 새 분석 최대 ${usage.data.batch_size}건`}</button>
    </>}
    <div aria-live="polite">
      {batch.isError && <p className="interview-prep-error">{batch.error.message}</p>}
      {batch.data && <><p>새 분석 {batch.data.fresh}건 · 캐시 재사용 {batch.data.cached}건 · 모델 호출 {batch.data.model_calls}회</p>
        <div className="analysis-batch-results">{batch.data.items.map((item) => <button key={item.job_id} onClick={() => onEvidence(item.job_id)}>공고 #{item.job_id} · {item.cached ? "캐시" : labels[item.outcome] ?? item.outcome}</button>)}</div></>}
    </div>
  </section>;
}
