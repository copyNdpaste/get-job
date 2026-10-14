import { QueryClient, QueryClientProvider, useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import type { MapResponse } from "./JobMap";
import { AnalysisPipeline } from "./AnalysisPipeline";
import { AnalysisBudgetPanel } from "./AnalysisBudgetPanel";
import "./styles.css";
import "./advisor.css";

const JobMap = lazy(() => import("./JobMap").then((module) => ({ default: module.JobMap })));

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } });
const DEFAULT_AI_MODEL = "auto";
const AI_MODEL_STORAGE_KEY = "get-job.ai-model";
const LEGACY_AI_MODEL_STORAGE_KEY = "job-radar.ai-model";
const FILTER_STORAGE_KEY = "job-radar.filters.v2";
const DAILY_LAST_SEEN_KEY = "job-radar.daily-recommendations.last-seen";
const INTERVIEW_CATEGORY_LABELS = {
  role: "직무 이해",
  technical: "기술",
  system_design: "시스템 설계",
  experience: "경험",
  collaboration: "협업",
} as const;
const DEFAULT_EXCLUDED_TECH: string[] = [];
const COMMON_EXCLUDED_TECH = ["Kotlin", "Android", "Spring Boot", ".NET", "C#", "PHP", "Ruby"];
const EXPERIENCE_OPTIONS = [
  { value: "intern", label: "인턴" },
  { value: "entry", label: "신입" },
  { value: "career", label: "경력" },
  { value: "no_experience", label: "경력무관" },
];
const YEAR_OPTIONS = Array.from({ length: 21 }, (_item, year) => year);
const SCORE_THRESHOLDS = [40, 50, 60, 70, 80, 90];
const POSTED_PERIOD_OPTIONS = [
  { value: "year", label: "올해 게시" },
  { value: "", label: "게시 기간 전체" },
  { value: "7", label: "최근 1주 게시" },
  { value: "14", label: "최근 2주 게시" },
  { value: "30", label: "최근 1개월 게시" },
  { value: "90", label: "최근 3개월 게시" },
];
const POSTED_PERIOD_VALUES = new Set(POSTED_PERIOD_OPTIONS.map((option) => option.value));
const SORT_OPTIONS = [
  { value: "latest", label: "게시일 최신순" },
  { value: "collected", label: "수집일 최신순" },
  { value: "fit", label: "적합도 높은순" },
  { value: "value", label: "지원가치 높은순" },
  { value: "company", label: "회사명순" },
];
const CODING_TEST_OPTIONS = [
  { value: "yes", label: "있음" },
  { value: "no", label: "없음 · 명시" },
  { value: "unknown", label: "미확인" },
];
const INTERVIEW_COUNT_OPTIONS = [
  { value: "one", label: "1회" },
  { value: "two_plus", label: "2회 이상" },
  { value: "none", label: "없음 · 명시" },
  { value: "unknown", label: "미확인" },
];
const NEW_JOB_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;
const SUBMITTED_APPLICATION_STATUSES = new Set([
  "applied", "document_passed", "interview", "offer", "rejected", "withdrawn",
]);
const APPLICATION_STATUS_LABELS: Record<string, string> = {
  applied: "지원 완료",
  document_passed: "지원 · 서류 통과",
  interview: "지원 · 면접 진행",
  offer: "지원 · 최종 합격",
  rejected: "지원 · 불합격",
  withdrawn: "지원 · 취소",
};

type Job = {
  id: number;
  source: string;
  company: string;
  company_summary: CompanySummary;
  title: string;
  url: string;
  tech_stack: string[];
  hiring_process: string[];
  has_coding_test: boolean | null;
  interview_count: number | null;
  experience_text: string | null;
  location: string | null;
  availability_check?: { status: string; reason: string; checked_at: string } | null;
  posted_at: string | null;
  deadline_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  is_active: boolean;
  is_hidden: boolean;
  is_favorite: boolean;
  total_fit_score: number | null;
  application_value_score: number | null;
  application_probability_score: number | null;
  grade: string | null;
  recommendation_grade: "최우선" | "추천" | "도전 지원" | "비추천" | null;
  node_typescript_transition: string | null;
  go_transition: string | null;
  backend_work_share: number | null;
  java_spring_required: boolean | null;
  java_spring_status: string | null;
  recommended_resume_type: string | null;
  recommended_resume_id: string | null;
  recommended_resume_label: string | null;
  recommended_resume_score: number | null;
  application_status: string;
  duplicate_count: number;
  duplicate_postings: { id: number; source: string; url: string; is_active: boolean }[];
};

type CompanySummary = {
  employee_count: number | null;
  developer_count: number | null;
  employee_count_source: string | null;
  employee_count_as_of: string | null;
  latest_revenue: number | null;
  latest_revenue_year: number | null;
  profitability_status: "profit" | "loss" | "break_even" | "undisclosed";
  investment_stage: string | null;
  recent_investment_amount: number | null;
  recent_investment_count: number;
  disclosed_investment_count: number;
  facts_updated_at: string | null;
};

type CompanyProfile = CompanySummary & {
  financial_history: { year: number; revenue: number | null; operating_profit: number | null; net_income: number | null; basis?: string; source: string; source_url?: string }[];
  funding_history: { date: string | null; round: string; amount: number | null; currency?: string; source: string; source_url?: string }[];
  source_urls: string[];
};

type ResumeScore = {
  label: string;
  score: number;
  max_score: number;
};

type ResumeOption = {
  id: string;
  label: string;
  short_label: string;
  summary: string;
  score: number;
  rank: number;
  is_recommended: boolean;
  breakdown: ResumeScore[];
  reasons: string[];
  matched_evidence: string[];
  suggested_edits: string[];
  available: boolean;
  file_url: string | null;
};

type ResumeRecommendation = {
  recommended_id: string;
  recommended_label: string;
  recommended_score: number;
  alternative_id: string;
  alternative_label: string;
  confidence: "high" | "medium" | "low";
  decision: { label: string; reason: string };
  criteria: string;
  resumes: ResumeOption[];
};

type JobDetail = Job & {
  company_profile: CompanyProfile;
  main_tasks: string[];
  requirements: string[];
  preferred_requirements: string[];
  benefits: string[];
  description_text: string | null;
  matching_reasons: { skill: string; strength?: "strong" | "partial"; profile_evidence?: string[]; job_evidence?: string[] }[];
  missing_skills: { skill: string; severity: "high" | "medium" | "low"; profile_note?: string; job_evidence?: string[] }[];
  risk_notes: string[];
  score_breakdown: { label: string; score: number; weight: number; reason?: string; profile_evidence?: string[]; job_evidence?: string[] }[];
  score_formula: string | null;
  scoring_version: string | null;
  recommended_resume_version: string | null;
  resume_recommendation: ResumeRecommendation | null;
  candidate_summary: string | null;
  candidate_years_experience: number | null;
  score_summary: string | null;
  score_confidence: "high" | "medium" | "low" | null;
  score_caps: string[];
  score_definitions: Record<string, string>;
  recommendation_reasons: string[];
};

type RecommendationItem = Job & { recommendation_score: number; why: string[] };
type RecommendationResponse = {
  answer: string;
  interpreted_filters: Record<string, unknown>;
  items: RecommendationItem[];
  ai_used: boolean;
  ai_provider: string;
  ai_model: string | null;
  ai_local_only: boolean;
  ai_notice: string;
};
type AIStatus = {
  enabled: boolean;
  available: boolean;
  provider: string;
  configured_model: string;
  active_model: string | null;
  models: string[];
  local_only: boolean;
  message: string;
};
type AIJobEvidence = {
  summary: string;
  strengths: { title: string; profile_evidence: string; job_evidence: string }[];
  gaps: { title: string; severity: "high" | "medium" | "low"; explanation: string }[];
  recommendation: string;
  provider: string;
  model: string;
  local_only: boolean;
};
type AIInterviewPrep = {
  opening_pitch: string;
  questions: {
    category: keyof typeof INTERVIEW_CATEGORY_LABELS;
    question: string;
    why_asked: string;
    answer_outline: string[];
    resume_evidence: string[];
    follow_ups: string[];
    caution: string;
  }[];
  study_topics: string[];
  questions_to_ask: string[];
  provider: string;
  model: string;
  local_only: boolean;
  cached: boolean;
  generated_at: string;
};

type JobResponse = { items: Job[]; total: number; limit: number; offset: number };
type Stats = {
  total: number;
  active: number;
  new_last_7_days: number;
  favorite: number;
  applied: number;
  hidden: number;
  source_counts: Record<string, number>;
  tech_counts: Record<string, number>;
};
type CrawlRun = {
  id: number;
  source: string;
  status: "running" | "succeeded" | "partial" | "failed";
  started_at: string;
  finished_at: string | null;
  pages_visited: number;
  jobs_found: number;
  jobs_created: number;
  jobs_updated: number;
  jobs_failed: number;
  error: string | null;
};
type EcosystemOrganization = {
  slug: string;
  name: string;
  organization_type: string;
  summary: string;
  website_url: string;
  program_url: string | null;
  monitored: boolean;
  last_crawled_at: string | null;
  fit_score: number;
  fit_reason: string;
  focus_tags: string[];
  source_url: string | null;
  operating_scale: string | null;
};
type EcosystemProgram = {
  id: number;
  organization_slug: string;
  organization_name: string;
  organization_type: string;
  title: string;
  url: string;
  program_type: "batch" | "investment" | "education" | "demo_day" | "program";
  summary: string | null;
  deadline_text: string | null;
  is_open: boolean;
  first_seen_at: string;
  last_seen_at: string;
};
type EcosystemProgramResponse = { items: EcosystemProgram[]; total: number; new_last_7_days: number };
type EcosystemCrawlRun = {
  id: number;
  organization_slug: string;
  organization_name: string;
  status: "running" | "succeeded" | "failed";
  started_at: string;
  finished_at: string | null;
  pages_visited: number;
  programs_found: number;
  programs_created: number;
  programs_updated: number;
  error: string | null;
};
type CrawlResultItem = {
  id: number;
  title: string;
  company: string;
  url: string;
  status: "created" | "updated" | "seen";
};
type DailyRecommendationDate = {
  date: string;
  generated_at: string;
  item_count: number;
  slack_status: string;
};
type DailyRecommendationItem = {
  job_id: number;
  rank: number;
  company: string;
  title: string;
  source: string;
  url: string;
  tech_stack: string[];
  experience_text: string | null;
  location: string | null;
  posted_at: string | null;
  fit_score: number;
  application_value_score: number;
};
type DailyRecommendationResponse = {
  date: string | null;
  generated_at: string | null;
  slack_status: string | null;
  items: DailyRecommendationItem[];
};

const sources = [
  "all", "demoday", "groupby", "wanted", "remember", "jumpit", "rallit", "saramin", "rocketpunch",
  "jobplanet", "greenhouse", "lever", "ashby", "greeting", "ninehire",
];
const automaticSources = [
  "demoday", "groupby", "wanted", "jumpit", "rallit", "saramin",
  "jobplanet", "greenhouse", "lever", "ashby", "greeting", "ninehire",
];
const sourceLabels: Record<string, string> = {
  all: "전체 소스",
  demoday: "데모데이",
  groupby: "그룹바이",
  wanted: "원티드",
  remember: "리멤버",
  jumpit: "점핏",
  rallit: "랠릿",
  saramin: "사람인",
  jobplanet: "잡플래닛",
  rocketpunch: "로켓펀치",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  greeting: "Greeting",
  ninehire: "Ninehire",
};

function formatScore(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(1);
}

function formatKrw(value: number | null | undefined): string {
  if (value == null) return "비공개";
  const sign = value < 0 ? "−" : "";
  const amount = Math.abs(value);
  if (amount >= 1_000_000_000_000) return `${sign}${(amount / 1_000_000_000_000).toFixed(amount % 1_000_000_000_000 ? 1 : 0)}조원`;
  if (amount >= 100_000_000) return `${sign}${(amount / 100_000_000).toFixed(amount % 100_000_000 ? 1 : 0)}억원`;
  if (amount >= 10_000) return `${sign}${Math.round(amount / 10_000).toLocaleString("ko-KR")}만원`;
  return `${sign}${amount.toLocaleString("ko-KR")}원`;
}

function profitabilityLabel(status: CompanySummary["profitability_status"]): string {
  return status === "profit" ? "흑자" : status === "loss" ? "적자" : status === "break_even" ? "손익분기" : "미상";
}

type DeadlineDisplay = {
  date: string;
  countdown: string;
  tone: "unknown" | "open" | "soon" | "urgent" | "closed";
};

const SEOUL_DAY_FORMAT = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "numeric",
  day: "numeric",
});
const DEADLINE_DATE_FORMAT = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  year: "2-digit",
  month: "2-digit",
  day: "2-digit",
});

function seoulCalendarDay(date: Date): number {
  const parts = Object.fromEntries(
    SEOUL_DAY_FORMAT.formatToParts(date).map((part) => [part.type, part.value]),
  );
  return Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)) / 86_400_000;
}

function deadlineDisplay(deadlineAt: string | null, isActive = true, now = new Date()): DeadlineDisplay {
  if (!isActive) {
    const deadline = deadlineAt ? new Date(deadlineAt) : null;
    return {
      date: deadline && !Number.isNaN(deadline.getTime()) ? DEADLINE_DATE_FORMAT.format(deadline) : "최근 수집 확인",
      countdown: "공고 종료",
      tone: "closed",
    };
  }
  if (!deadlineAt) {
    return { date: "마감일 미기재", countdown: "상시/미기재", tone: "unknown" };
  }
  const deadline = new Date(deadlineAt);
  if (Number.isNaN(deadline.getTime())) {
    return { date: "마감일 미기재", countdown: "확인 필요", tone: "unknown" };
  }
  const days = seoulCalendarDay(deadline) - seoulCalendarDay(now);
  const countdown = days < 0 ? `D+${Math.abs(days)}` : days === 0 ? "D-Day" : `D-${days}`;
  const tone = days < 0 ? "closed" : days <= 3 ? "urgent" : days <= 7 ? "soon" : "open";
  return { date: DEADLINE_DATE_FORMAT.format(deadline), countdown, tone };
}

function isNewlyCollected(firstSeenAt: string, now = new Date()): boolean {
  const collectedAt = new Date(firstSeenAt).getTime();
  const nowAt = now.getTime();
  return Number.isFinite(collectedAt)
    && collectedAt <= nowAt
    && collectedAt >= nowAt - NEW_JOB_WINDOW_MS;
}

type JobFilters = {
  query: string;
  source: string;
  excludedSources: string[];
  technologies: string[];
  excludedTech: string[];
  experienceTypes: string[];
  minYears: string;
  maxYears: string;
  codingTests: string[];
  interviewCounts: string[];
  minFitScore: string;
  minValueScore: string;
  postedWithinDays: string;
  datePolicyVersion?: number;
  includeUnknownPosted: boolean;
  sort: string;
  viewMode: JobView;
};

type JobView = "all" | "recent" | "favorites" | "applied" | "hidden";

const DEFAULT_JOB_FILTERS: JobFilters = {
  query: "",
  source: "all",
  excludedSources: [],
  technologies: [],
  excludedTech: [...DEFAULT_EXCLUDED_TECH],
  experienceTypes: [],
  minYears: "",
  maxYears: "",
  codingTests: [],
  interviewCounts: [],
  minFitScore: "",
  minValueScore: "",
  postedWithinDays: "year",
  includeUnknownPosted: false,
  sort: "latest",
  viewMode: "all",
};
const FILTER_SORTS = new Set(["latest", "collected", "fit", "value", "company"]);
const JOB_VIEW_MODES = new Set<JobView>(["all", "recent", "favorites", "applied", "hidden"]);
const EXPERIENCE_FILTERS = new Set(EXPERIENCE_OPTIONS.map((option) => option.value));
const CODING_TEST_FILTERS = new Set(CODING_TEST_OPTIONS.map((option) => option.value));
const INTERVIEW_COUNT_FILTERS = new Set(INTERVIEW_COUNT_OPTIONS.map((option) => option.value));

function freshDefaultFilters(): JobFilters {
  return {
    ...DEFAULT_JOB_FILTERS,
    excludedSources: [],
    technologies: [],
    excludedTech: [...DEFAULT_JOB_FILTERS.excludedTech],
    experienceTypes: [],
    codingTests: [],
    interviewCounts: [],
  };
}

function savedText(value: unknown, maxLength: number): string {
  return typeof value === "string" ? value.slice(0, maxLength) : "";
}

function savedYear(value: unknown): string {
  const normalized = savedText(value, 2);
  return normalized !== "" && YEAR_OPTIONS.includes(Number(normalized)) ? String(Number(normalized)) : "";
}

function savedTechList(value: unknown, fallback: string[] = []): string[] {
  if (!Array.isArray(value)) return [...fallback];
  const seen = new Set<string>();
  const items: string[] = [];
  for (const candidate of value) {
    if (typeof candidate !== "string") continue;
    const item = candidate.trim().slice(0, 80);
    const key = item.toLocaleLowerCase();
    if (!item || seen.has(key)) continue;
    seen.add(key);
    items.push(item);
    if (items.length >= 50) break;
  }
  return items;
}

function savedChoiceList(value: unknown, allowed: Set<string>): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(new Set(value.filter(
    (item): item is string => typeof item === "string" && allowed.has(item)
  )));
}

function savedScore(value: unknown): string {
  const normalized = savedText(value, 3);
  return SCORE_THRESHOLDS.includes(Number(normalized)) ? normalized : "";
}

function loadSavedFilters(): JobFilters {
  try {
    const raw = window.localStorage.getItem(FILTER_STORAGE_KEY);
    if (!raw) return freshDefaultFilters();
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return freshDefaultFilters();
    const saved = parsed as Record<string, unknown>;
    let minYears = savedYear(saved.minYears);
    let maxYears = savedYear(saved.maxYears);
    if (minYears && maxYears && Number(minYears) > Number(maxYears)) maxYears = minYears;
    const legacyTech = savedText(saved.tech, 80).trim();
    const legacyCodingTest = savedText(saved.codingTest, 20);
    const legacyInterviewCount = savedText(saved.interviewCount, 20);
    const codingTests = Array.isArray(saved.codingTests)
      ? savedChoiceList(saved.codingTests, CODING_TEST_FILTERS)
      : CODING_TEST_FILTERS.has(legacyCodingTest) ? [legacyCodingTest] : [];
    const interviewCounts = Array.isArray(saved.interviewCounts)
      ? savedChoiceList(saved.interviewCounts, INTERVIEW_COUNT_FILTERS)
      : INTERVIEW_COUNT_FILTERS.has(legacyInterviewCount) ? [legacyInterviewCount] : [];

    return {
      query: savedText(saved.query, 200),
      source: typeof saved.source === "string" && sources.includes(saved.source) ? saved.source : "all",
      excludedSources: Array.isArray(saved.excludedSources)
        ? Array.from(new Set(saved.excludedSources.filter((value): value is string =>
            typeof value === "string" && value !== "all" && sources.includes(value))))
        : [],
      technologies: savedTechList(
        saved.technologies,
        legacyTech ? [legacyTech] : [],
      ),
      excludedTech: savedTechList(saved.excludedTech, DEFAULT_EXCLUDED_TECH),
      experienceTypes: Array.isArray(saved.experienceTypes)
        ? Array.from(new Set(saved.experienceTypes.filter((value): value is string => typeof value === "string" && EXPERIENCE_FILTERS.has(value))))
        : [],
      minYears,
      maxYears,
      codingTests,
      interviewCounts,
      minFitScore: savedScore(saved.minFitScore),
      minValueScore: savedScore(saved.minValueScore),
      includeUnknownPosted: saved.includeUnknownPosted === true,
      postedWithinDays: typeof saved.postedWithinDays === "string" && POSTED_PERIOD_VALUES.has(saved.postedWithinDays)
        ? (saved.postedWithinDays === "" && saved.datePolicyVersion !== 1 ? "year" : saved.postedWithinDays)
        : "year",
      sort: typeof saved.sort === "string" && FILTER_SORTS.has(saved.sort) ? saved.sort : "latest",
      viewMode: typeof saved.viewMode === "string" && JOB_VIEW_MODES.has(saved.viewMode as JobView)
        ? saved.viewMode as JobView
        : "all",
    };
  } catch {
    return freshDefaultFilters();
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { signal });
  if (!response.ok) throw new Error(`요청 실패 (${response.status})`);
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({})) as { detail?: string };
  if (!response.ok) throw new Error(payload.detail ?? `요청 실패 (${response.status})`);
  return payload as T;
}

function seoulDateKey(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function App() {
  const [displayMode, setDisplayMode] = useState<"list" | "map">("list");
  const [initialFilters] = useState(loadSavedFilters);
  const [query, setQuery] = useState(initialFilters.query);
  const [source, setSource] = useState(initialFilters.source);
  const [excludedSources, setExcludedSources] = useState<string[]>(initialFilters.excludedSources);
  const [debouncedQuery, setDebouncedQuery] = useState(query);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 200);
    return () => window.clearTimeout(timer);
  }, [query]);
  const [technologies, setTechnologies] = useState<string[]>(initialFilters.technologies);
  const [excludedTech, setExcludedTech] = useState<string[]>(initialFilters.excludedTech);
  const [experienceTypes, setExperienceTypes] = useState<string[]>(initialFilters.experienceTypes);
  const [minYears, setMinYears] = useState(initialFilters.minYears);
  const [maxYears, setMaxYears] = useState(initialFilters.maxYears);
  const [codingTests, setCodingTests] = useState<string[]>(initialFilters.codingTests);
  const [interviewCounts, setInterviewCounts] = useState<string[]>(initialFilters.interviewCounts);
  const [minFitScore, setMinFitScore] = useState(initialFilters.minFitScore);
  const [minValueScore, setMinValueScore] = useState(initialFilters.minValueScore);
  const [postedWithinDays, setPostedWithinDays] = useState(initialFilters.postedWithinDays);
  const [includeUnknownPosted, setIncludeUnknownPosted] = useState(initialFilters.includeUnknownPosted);
  const [sort, setSort] = useState(initialFilters.sort);
  const [viewMode, setViewMode] = useState<JobView>(initialFilters.viewMode);
  const [filterStorageAvailable, setFilterStorageAvailable] = useState(true);
  const [selected, setSelected] = useState<number[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const [evidenceJobId, setEvidenceJobId] = useState<number | null>(null);
  const [collectionOpen, setCollectionOpen] = useState(false);
  const [advisorOpen, setAdvisorOpen] = useState(false);
  const [scoreInfoOpen, setScoreInfoOpen] = useState(false);
  const [analysisBudgetOpen, setAnalysisBudgetOpen] = useState(false);
  const [dailyOpen, setDailyOpen] = useState(false);
  const [ecosystemOpen, setEcosystemOpen] = useState(false);
  const [dailyLastSeen, setDailyLastSeen] = useState(() => window.localStorage.getItem(DAILY_LAST_SEEN_KEY) ?? "");
  const [aiModel, setAiModel] = useState(() => window.localStorage.getItem(AI_MODEL_STORAGE_KEY) || window.localStorage.getItem(LEGACY_AI_MODEL_STORAGE_KEY) || DEFAULT_AI_MODEL);
  const [notice, setNotice] = useState<string | null>(null);

  const params = new URLSearchParams({ limit: "200", sort });
  if (debouncedQuery.trim()) params.set("q", debouncedQuery.trim());
  if (source !== "all") params.set("source", source);
  excludedSources.forEach((item) => params.append("exclude_source", item));
  if (postedWithinDays) {
    if (postedWithinDays === "year") params.set("posted_in_year", new Date().getFullYear().toString());
    else params.set("posted_within_days", postedWithinDays);
    if (includeUnknownPosted) params.set("include_unknown_posted", "true");
  }
  if (viewMode !== "hidden") {
    technologies.forEach((item) => params.append("tech", item));
    excludedTech.forEach((item) => params.append("exclude_tech", item));
    experienceTypes.forEach((item) => params.append("experience", item));
    if (minYears) params.set("min_years", minYears);
    if (maxYears) params.set("max_years", maxYears);
    codingTests.forEach((item) => params.append("coding_test", item));
    interviewCounts.forEach((item) => params.append("interview_count", item));
    if (minFitScore) params.set("min_fit_score", minFitScore);
    if (minValueScore) params.set("min_value_score", minValueScore);
  }
  if (viewMode === "favorites") params.set("favorite_only", "true");
  if (viewMode === "recent") params.set("collected_within_days", "7");
  if (viewMode === "applied") {
    params.set("applied_only", "true");
    params.set("active_only", "false");
    params.set("include_hidden", "true");
  }
  if (viewMode === "hidden") {
    params.set("hidden_only", "true");
    params.set("active_only", "false");
  }

  const jobs = useQuery({
    queryKey: ["jobs", viewMode, debouncedQuery, source, excludedSources.join("|"), technologies.join("|"), excludedTech.join("|"), experienceTypes.join("|"), minYears, maxYears, codingTests.join("|"), interviewCounts.join("|"), minFitScore, minValueScore, postedWithinDays, includeUnknownPosted, sort],
    queryFn: ({ signal }) => getJson<JobResponse>(`/api/jobs?${params}`, signal),
  });
  const mapParams = new URLSearchParams(params);
  mapParams.set("map_view", "true");
  mapParams.set("limit", "5000");
  const mapJobs = useQuery({
    queryKey: ["job-map", mapParams.toString()],
    queryFn: ({ signal }) => getJson<MapResponse>(`/api/jobs?${mapParams}`, signal),
    enabled: displayMode === "map",
  });
  const stats = useQuery({ queryKey: ["stats"], queryFn: () => getJson<Stats>("/api/jobs/stats") });
  const dailyDates = useQuery({
    queryKey: ["daily-recommendation-dates"],
    queryFn: () => getJson<DailyRecommendationDate[]>("/api/daily-recommendations/dates?limit=90"),
    refetchInterval: 60_000,
  });
  const aiStatus = useQuery({
    queryKey: ["ai-status", aiModel],
    queryFn: () => getJson<AIStatus>(`/api/ai/status?model=${encodeURIComponent(aiModel)}`),
    refetchInterval: 60_000,
    retry: false,
  });
  const runs = useQuery({
    queryKey: ["crawl-runs"],
    queryFn: () => getJson<CrawlRun[]>("/api/crawl/runs?limit=50"),
    refetchInterval: (query) => query.state.data?.some((run) => run.status === "running") ? 2_000 : 10_000,
  });
  const ecosystemPrograms = useQuery({
    queryKey: ["ecosystem-programs"],
    queryFn: () => getJson<EcosystemProgramResponse>("/api/ecosystem/programs?open_only=true&limit=100"),
    refetchInterval: 60_000,
  });
  const ecosystemOrganizations = useQuery({
    queryKey: ["ecosystem-organizations"],
    queryFn: () => getJson<EcosystemOrganization[]>("/api/ecosystem/organizations"),
    enabled: ecosystemOpen,
  });
  const ecosystemRuns = useQuery({
    queryKey: ["ecosystem-runs"],
    queryFn: () => getJson<EcosystemCrawlRun[]>("/api/ecosystem/runs?limit=30"),
    enabled: ecosystemOpen,
    refetchInterval: ecosystemOpen ? 10_000 : false,
  });
  const comparison = useQueries({
    queries: selected.map((id) => ({
      queryKey: ["job", id],
      queryFn: () => getJson<JobDetail>(`/api/jobs/${id}`),
    })),
  });
  const evidence = useQuery({
    queryKey: ["job", evidenceJobId],
    queryFn: () => getJson<JobDetail>(`/api/jobs/${evidenceJobId}`),
    enabled: evidenceJobId != null,
  });

  const latestRuns = useMemo(() => {
    const latest: Record<string, CrawlRun> = {};
    for (const run of runs.data ?? []) if (!latest[run.source]) latest[run.source] = run;
    return latest;
  }, [runs.data]);
  const latestDailyDate = dailyDates.data?.[0]?.date ?? "";
  const todayDate = seoulDateKey();
  const hasTodayRecommendations = Boolean(
    dailyDates.data?.some((item) => item.date === todayDate),
  );
  const hasUnreadDailyRecommendations = Boolean(
    latestDailyDate && latestDailyDate > dailyLastSeen,
  );
  const openDailyRecommendations = () => {
    setDailyOpen(true);
    setEcosystemOpen(false);
    setCompareOpen(false);
    setCollectionOpen(false);
    setAdvisorOpen(false);
    if (latestDailyDate) {
      try {
        window.localStorage.setItem(DAILY_LAST_SEEN_KEY, latestDailyDate);
        setDailyLastSeen(latestDailyDate);
      } catch {
        setDailyLastSeen(latestDailyDate);
      }
    }
  };
  const finishedSignature = (runs.data ?? []).filter((run) => run.finished_at).map((run) => `${run.id}:${run.status}`).join("|");
  useEffect(() => {
    if (!finishedSignature) return;
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["job-map"] });
    void queryClient.invalidateQueries({ queryKey: ["stats"] });
  }, [finishedSignature]);
  useEffect(() => {
    window.localStorage.setItem(AI_MODEL_STORAGE_KEY, aiModel);
  }, [aiModel]);
  useEffect(() => {
    try {
      window.localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify({
        query,
        source,
        excludedSources,
        technologies,
        excludedTech,
        experienceTypes,
        minYears,
        maxYears,
        codingTests,
        interviewCounts,
        minFitScore,
        minValueScore,
        postedWithinDays,
        datePolicyVersion: 1,
        includeUnknownPosted,
        sort,
        viewMode,
      } satisfies JobFilters));
      setFilterStorageAvailable(true);
    } catch {
      setFilterStorageAvailable(false);
    }
  }, [query, source, excludedSources, technologies, excludedTech, experienceTypes, minYears, maxYears, codingTests, interviewCounts, minFitScore, minValueScore, postedWithinDays, includeUnknownPosted, sort, viewMode]);
  const startCrawl = useMutation({
    mutationFn: async (sourceNames: string[]) => {
      const attempts = await Promise.all(sourceNames.map(async (sourceName) => {
        const response = await fetch(`${API_URL}/api/crawl/${sourceName}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            max_jobs: ["wanted", "jobplanet"].includes(sourceName) ? 5000 : 1000,
            urls: [],
            headless: false,
          }),
        });
        const body = await response.json();
        return { sourceName, response, body };
      }));
      const failures = attempts.filter(({ response }) => !response.ok);
      if (failures.length) {
        throw new Error(failures.map(({ sourceName, body }) => `${sourceLabels[sourceName]}: ${body.detail ?? "시작 실패"}`).join(" · "));
      }
      return attempts.map(({ body }) => body);
    },
    onSuccess: (_result, sourceNames) => {
      setNotice(`${sourceNames.length}개 사이트의 백그라운드 수집·분석을 시작했습니다.`);
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "수집 시작 실패"),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["crawl-runs"] }),
  });

  const importRocket = useMutation({
    mutationFn: async ({ file, url }: { file: File; url: string }) => {
      const response = await fetch(`${API_URL}/api/crawl/rocketpunch/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ html: await file.text(), url }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "HTML 가져오기에 실패했습니다.");
      return body;
    },
    onSuccess: () => {
      setNotice("로켓펀치 공고를 저장하고 분석했습니다.");
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["job-map"] });
      void queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "HTML 가져오기 실패"),
  });

  const collectPrograms = useMutation({
    mutationFn: () => postJson<EcosystemCrawlRun[]>("/api/ecosystem/crawl"),
    onSuccess: (runs) => {
      setNotice(`${runs.length}개 기관의 공개 투자·배치 기회 수집을 시작했습니다.`);
      void queryClient.invalidateQueries({ queryKey: ["ecosystem-runs"] });
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "프로그램 수집 시작 실패"),
  });

  const instantRecommendation = useMutation({
    mutationFn: () => postJson<DailyRecommendationResponse>(
      "/api/daily-recommendations/generate",
      { notify_slack: false },
    ),
    onSuccess: (result) => {
      if (result.date) {
        queryClient.setQueryData(["daily-recommendations", result.date], result);
        queryClient.setQueryData<DailyRecommendationDate[]>(
          ["daily-recommendation-dates"],
          (current = []) => [
            {
              date: result.date!,
              generated_at: result.generated_at ?? new Date().toISOString(),
              item_count: result.items.length,
              slack_status: result.slack_status ?? "not_requested",
            },
            ...current.filter((item) => item.date !== result.date),
          ],
        );
        try {
          window.localStorage.setItem(DAILY_LAST_SEEN_KEY, result.date);
        } catch {
          // The recommendation still works when browser storage is unavailable.
        }
        setDailyLastSeen(result.date);
      }
      setDailyOpen(true);
      setNotice(`현재 수집된 공고에서 추천 ${result.items.length}개를 다시 선별했습니다.`);
      void queryClient.invalidateQueries({ queryKey: ["daily-recommendation-dates"] });
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "즉시 추천 생성 실패"),
  });

  const visibility = useMutation({
    mutationFn: async ({ jobIds, hidden }: { jobIds: number[]; hidden: boolean }) => {
      const response = await fetch(`${API_URL}/api/jobs/visibility`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: jobIds, hidden }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "숨김 상태 변경에 실패했습니다.");
      return body;
    },
    onSuccess: (result, variables) => {
      const target = variables.jobIds.length > 1 ? "선택한 공고를" : "공고를";
      setNotice(result.hidden ? `${target} 숨겼습니다.` : `${target} 복원했습니다.`);
      setSelected([]);
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["job-map"] });
      void queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "숨김 처리 실패"),
  });

  const favorite = useMutation({
    mutationFn: async ({ jobId, isFavorite }: { jobId: number; isFavorite: boolean }) => {
      const response = await fetch(`${API_URL}/api/jobs/${jobId}/favorite`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_favorite: isFavorite }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "관심 공고 저장에 실패했습니다.");
      return body as { job_id: number; is_favorite: boolean };
    },
    onMutate: async ({ jobId, isFavorite }) => {
      await queryClient.cancelQueries({ queryKey: ["jobs"] });
      await queryClient.cancelQueries({ queryKey: ["job", jobId] });
      const snapshots = queryClient.getQueriesData<JobResponse>({ queryKey: ["jobs"] });
      for (const [key, data] of snapshots) {
        if (!data) continue;
        queryClient.setQueryData<JobResponse>(key, {
          ...data,
          items: data.items.map((job) => job.id === jobId ? { ...job, is_favorite: isFavorite } : job),
        });
      }
      const detail = queryClient.getQueryData<JobDetail>(["job", jobId]);
      if (detail) queryClient.setQueryData<JobDetail>(["job", jobId], { ...detail, is_favorite: isFavorite });
      return { snapshots, detail };
    },
    onError: (error, { jobId }, context) => {
      for (const [key, data] of context?.snapshots ?? []) queryClient.setQueryData(key, data);
      if (context?.detail) queryClient.setQueryData(["job", jobId], context.detail);
      setNotice(error instanceof Error ? error.message : "관심 공고 저장 실패");
    },
    onSettled: (_data, _error, { jobId }) => {
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["job-map"] });
      void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const application = useMutation({
    mutationFn: async ({ jobId, status }: { jobId: number; status: string }) => {
      const response = await fetch(`${API_URL}/api/jobs/${jobId}/application`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "지원 상태 변경에 실패했습니다.");
      return body as { job_id: number; status: string; applied_at: string | null };
    },
    onSuccess: (result) => {
      setNotice(result.status === "not_reviewed" ? "지원 완료 표시를 해제했습니다." : "지원 완료로 표시했습니다.");
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["job-map"] });
      void queryClient.invalidateQueries({ queryKey: ["job", result.job_id] });
      void queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "지원 상태 변경 실패"),
  });

  const techOptions = useMemo(() => Object.keys(stats.data?.tech_counts ?? {}), [stats.data]);
  const includedTechOptions = useMemo(
    () => Array.from(new Set([...technologies, ...techOptions])).filter(
      (item) => !excludedTech.some(
        (excluded) => excluded.toLocaleLowerCase() === item.toLocaleLowerCase()
      )
    ),
    [excludedTech, techOptions, technologies],
  );
  const exclusionOptions = useMemo(
    () => Array.from(new Set([...DEFAULT_EXCLUDED_TECH, ...COMMON_EXCLUDED_TECH, ...techOptions]))
      .filter((item) => !excludedTech.some((excluded) => excluded.toLocaleLowerCase() === item.toLocaleLowerCase())),
    [excludedTech, techOptions],
  );
  const aiModelOptions = useMemo(
    () => Array.from(new Set([aiModel, DEFAULT_AI_MODEL, ...(aiStatus.data?.models ?? [])])).filter(Boolean),
    [aiModel, aiStatus.data?.models],
  );
  const selectedJobs = (jobs.data?.items ?? []).filter((job) => selected.includes(job.id));
  const currentResults = displayMode === "map" ? mapJobs : jobs;
  const totalResultCount = currentResults.data?.total ?? 0;
  const visibleResultCount = currentResults.data?.items.length ?? 0;
  const restoringSelection = selectedJobs.length > 0 && selectedJobs.every((job) => job.is_hidden);
  const viewTitle = viewMode === "recent" ? "최근 7일 신규 수집" : viewMode === "favorites" ? "관심 공고" : viewMode === "applied" ? "지원 완료 공고" : viewMode === "hidden" ? "숨긴 공고" : "개발 공고 탐색";
  const resultScope = viewMode === "recent" ? "게시일과 무관하게 최근 7일 안에 처음 수집한 공고" : viewMode === "favorites" ? "관심 공고" : viewMode === "applied" ? "지원 완료 공고" : viewMode === "hidden" ? "숨긴 공고" : "전체 일치 공고";
  const emptyCopy = viewMode === "favorites"
    ? { title: "관심 공고가 없습니다", body: "공고 목록의 빈 하트를 눌러 관심 공고로 저장해 보세요." }
    : viewMode === "recent"
      ? { title: "최근 7일 신규 수집 공고가 없습니다", body: "게시일이 오래된 공고도 새로 발견되면 이곳에 7일 동안 표시됩니다." }
    : viewMode === "applied"
      ? { title: "지원 완료 공고가 없습니다", body: "각 채용 사이트에서 확인한 지원 내역이나 목록의 지원 버튼으로 표시할 수 있습니다." }
    : viewMode === "hidden"
      ? { title: "숨긴 공고가 없습니다", body: "숨긴 공고는 이곳에서 다시 복원할 수 있습니다." }
      : { title: "조건에 맞는 공고가 없습니다", body: "필터를 바꾸거나 수집을 실행해 보세요." };
  const changeViewMode = (nextView: JobView) => {
    setViewMode(nextView);
    if (nextView === "recent") setSort("collected");
    else if (viewMode === "recent" && sort === "collected") setSort("latest");
    setSelected([]);
    setCompareOpen(false);
  };
  const toggleSelected = (id: number) => {
    setSelected((current) => {
      if (current.includes(id)) return current.filter((value) => value !== id);
      if (current.length >= 4) {
        setNotice("비교는 최대 4개까지 가능합니다.");
        return current;
      }
      return [...current, id];
    });
  };
  const toggleExperience = (value: string) => setExperienceTypes((current) =>
    current.includes(value) ? current.filter((item) => item !== value) : [...current, value]
  );
  const toggleTechnology = (value: string) => {
    setTechnologies((current) => current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value]
    );
    setExcludedTech((current) => current.filter(
      (item) => item.toLocaleLowerCase() !== value.toLocaleLowerCase()
    ));
  };
  const toggleCodingTest = (value: string) => setCodingTests((current) =>
    current.includes(value) ? current.filter((item) => item !== value) : [...current, value]
  );
  const toggleInterviewCount = (value: string) => setInterviewCounts((current) =>
    current.includes(value) ? current.filter((item) => item !== value) : [...current, value]
  );
  const addExcludedTech = (value: string) => {
    if (!value) return;
    setExcludedTech((current) => current.some((item) => item.toLocaleLowerCase() === value.toLocaleLowerCase()) ? current : [...current, value]);
    setTechnologies((current) => current.filter(
      (item) => item.toLocaleLowerCase() !== value.toLocaleLowerCase()
    ));
  };
  const removeExcludedTech = (value: string) => setExcludedTech((current) => current.filter((item) => item !== value));
  const changeMinimumYears = (value: string) => {
    setMinYears(value);
    if (value && maxYears && Number(value) > Number(maxYears)) setMaxYears(value);
  };
  const changeMaximumYears = (value: string) => {
    setMaxYears(value);
    if (value && minYears && Number(value) < Number(minYears)) setMinYears(value);
  };
  const resetFilters = () => {
    const defaults = freshDefaultFilters();
    setQuery(defaults.query);
    setSource(defaults.source);
    setExcludedSources(defaults.excludedSources);
    setTechnologies(defaults.technologies);
    setExcludedTech(defaults.excludedTech);
    setExperienceTypes(defaults.experienceTypes);
    setMinYears(defaults.minYears);
    setMaxYears(defaults.maxYears);
    setCodingTests(defaults.codingTests);
    setInterviewCounts(defaults.interviewCounts);
    setMinFitScore(defaults.minFitScore);
    setMinValueScore(defaults.minValueScore);
    setPostedWithinDays(defaults.postedWithinDays);
    setIncludeUnknownPosted(defaults.includeUnknownPosted);
    setSort(defaults.sort);
    setSelected([]);
    setNotice("필터를 기본값으로 초기화했습니다.");
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark">G</div>
          <div><strong>get-job</strong><span>공고별 이력서 추천기</span></div>
        </div>
        <div className="header-actions">
          {notice && <span className="notice">{notice}</span>}
          <button className="instant-recommend-button" disabled={dailyDates.isLoading || instantRecommendation.isPending || hasTodayRecommendations} title={hasTodayRecommendations ? "오늘의 추천에 이미 반영되었습니다." : "현재 DB 공고에서 오늘 추천을 선별합니다."} onClick={() => instantRecommendation.mutate()}>
            {dailyDates.isLoading ? "추천 확인 중…" : instantRecommendation.isPending ? "선별 중…" : hasTodayRecommendations ? "✓ 오늘 추천 완료" : "✦ 지금 추천받기"}
          </button>
          <button className={hasUnreadDailyRecommendations ? "daily-nav-button unread" : "daily-nav-button"} onClick={openDailyRecommendations} aria-label="오늘의 추천 공고와 날짜별 히스토리 열기">
            <span aria-hidden="true">🔔</span><b>오늘의 추천</b>
            {hasUnreadDailyRecommendations && <i>{dailyDates.data?.[0]?.item_count ?? 0}</i>}
          </button>
          <button className={ecosystemPrograms.data?.new_last_7_days ? "ecosystem-nav-button unread" : "ecosystem-nav-button"} onClick={() => { setEcosystemOpen(true); setDailyOpen(false); setCollectionOpen(false); setAdvisorOpen(false); }} aria-label="초기 투자사와 신규 창업 프로그램 보기">
            <span aria-hidden="true">◈</span><b>창업 프로그램</b>
            {!!ecosystemPrograms.data?.new_last_7_days && <i>{ecosystemPrograms.data.new_last_7_days}</i>}
          </button>
          <AIModelPicker models={aiModelOptions} value={aiModel} status={aiStatus.data} refreshing={aiStatus.isFetching} onChange={setAiModel} onRefresh={() => void aiStatus.refetch()} />
          <button className="advisor-button" onClick={() => setAdvisorOpen(true)}>✦ 공고 추천받기</button>
          <button className="analysis-action-button" onClick={() => setAnalysisBudgetOpen((open) => !open)}>AI 분석·예산</button>
          <a className="analysis-action-button system-guide-link" href="/system-guide/index.html" target="_blank" rel="noreferrer">시스템 가이드 ↗</a>
          <button className="sync-button" onClick={() => setCollectionOpen(true)}>
            <span className={Object.values(latestRuns).some((run) => run.status === "running") ? "sync-dot spinning" : "sync-dot"}>↻</span>
            수집·분석
          </button>
        </div>
      </header>

      {analysisBudgetOpen && <AnalysisBudgetPanel onClose={() => setAnalysisBudgetOpen(false)} onEvidence={(id) => setEvidenceJobId(id)} />}

      {ecosystemOpen ? (
        <EcosystemPage
          organizations={ecosystemOrganizations.data ?? []}
          organizationsLoading={ecosystemOrganizations.isLoading}
          programs={ecosystemPrograms.data?.items ?? []}
          programsLoading={ecosystemPrograms.isLoading}
          newCount={ecosystemPrograms.data?.new_last_7_days ?? 0}
          runs={ecosystemRuns.data ?? []}
          collecting={collectPrograms.isPending}
          onCollect={() => collectPrograms.mutate()}
          onClose={() => setEcosystemOpen(false)}
        />
      ) : dailyOpen ? (
        <DailyRecommendationsPage
          dates={dailyDates.data ?? []}
          datesLoading={dailyDates.isLoading}
          onClose={() => setDailyOpen(false)}
          onEvidence={(jobId) => setEvidenceJobId(jobId)}
          onGenerate={() => instantRecommendation.mutate()}
          generating={instantRecommendation.isPending}
          todayGenerated={hasTodayRecommendations}
          onOpenAdvisor={() => setAdvisorOpen(true)}
        />
      ) : <main className="page">
        <section className="hero-row">
          <div>
            <p className="eyebrow">OPPORTUNITY COMMAND CENTER</p>
            <h1>공고를 고르면<br /><em>이력서까지 골라드려요.</em></h1>
            <p className="hero-copy">Python 주력 경력과 Node.js·TypeScript 백엔드 실무를 함께 비교해<br />지원할 공고와 제출할 이력서 유형을 한 번에 보여줍니다.</p>
          </div>
          <div className="signal-panel">
            <div className="signal-head"><span>수집 신호</span><span className="live"><i />LIVE</span></div>
            <div className="source-bars">
              {Object.entries(stats.data?.source_counts ?? {}).map(([name, count]) => (
                <div className="source-bar" key={name}>
                  <span>{sourceLabels[name] ?? name}</span>
                  <div><i style={{ width: `${Math.max(6, (count / Math.max(1, stats.data?.total ?? 1)) * 100)}%` }} /></div>
                  <b>{count}</b>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="stat-grid">
          <Stat label="전체 공고" value={stats.data?.total ?? 0} note="누적 수집" />
          <Stat label="활성 공고" value={stats.data?.active ?? 0} note="현재 지원 가능" accent />
          <Stat label="최근 수집" value={stats.data?.new_last_7_days ?? 0} note="게시일 무관 · 7일" />
          <Stat label="비교 바구니" value={selected.length} note="최대 4개" />
        </section>

        <section className="workspace">
          <div className="workspace-head">
            <div><p className="section-kicker">JOB LIBRARY</p><h2>{viewTitle}</h2></div>
            <div className="display-toggle" aria-label="공고 표시 방식">{(["list", "map"] as const).map((mode) => <button type="button" key={mode} aria-pressed={displayMode === mode} onClick={() => setDisplayMode(mode)}>{mode === "list" ? "목록" : "지도"}</button>)}</div>
          </div>
          <nav className="job-view-tabs" aria-label="공고 보관함">
            <button type="button" role="tab" aria-selected={viewMode === "all"} className={viewMode === "all" ? "active" : ""} onClick={() => changeViewMode("all")}><span>전체 공고</span><b>{(stats.data?.active ?? 0).toLocaleString()}</b></button>
            <button type="button" role="tab" aria-selected={viewMode === "recent"} className={viewMode === "recent" ? "active recent" : "recent"} onClick={() => changeViewMode("recent")}><span>✦ 최근 수집</span><b>{(stats.data?.new_last_7_days ?? 0).toLocaleString()}</b></button>
            <button type="button" role="tab" aria-selected={viewMode === "favorites"} className={viewMode === "favorites" ? "active favorites" : "favorites"} onClick={() => changeViewMode("favorites")}><span>♥ 관심 공고</span><b>{(stats.data?.favorite ?? 0).toLocaleString()}</b></button>
            <button type="button" role="tab" aria-selected={viewMode === "applied"} className={viewMode === "applied" ? "active applied" : "applied"} onClick={() => changeViewMode("applied")}><span>✓ 지원 완료</span><b>{(stats.data?.applied ?? 0).toLocaleString()}</b></button>
            <button type="button" role="tab" aria-selected={viewMode === "hidden"} className={viewMode === "hidden" ? "active hidden" : "hidden"} onClick={() => changeViewMode("hidden")}><span>숨긴 공고</span><b>{(stats.data?.hidden ?? 0).toLocaleString()}</b></button>
          </nav>
          <div className={viewMode === "hidden" ? "filters hidden-view-filters" : "filters"}>
            <label className="search-field"><span>⌕</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="회사 또는 포지션 검색" /></label>
            <Select ariaLabel="공고 출처" value={source} onChange={(value) => {
              setSource(value);
              setExcludedSources((current) => current.filter((item) => item !== value));
            }} options={sources.map((value) => ({ value, label: sourceLabels[value] }))} />
            <details className="multi-select-field">
              <summary><span>{excludedSources.length ? `출처 ${excludedSources.length}개 제외` : "출처 제외"}</span><b>⌄</b></summary>
              <div className="multi-select-menu">
                <div className="multi-option-list">
                  {sources.filter((value) => value !== "all").map((value) => <label className="filter-check" key={value}>
                    <input type="checkbox" checked={excludedSources.includes(value)} onChange={() => {
                      setExcludedSources((current) => current.includes(value)
                        ? current.filter((item) => item !== value) : [...current, value]);
                      if (source === value) setSource("all");
                    }} /><span>✓</span><b>{sourceLabels[value]}</b>
                  </label>)}
                </div>
                {excludedSources.length > 0 && <button type="button" onClick={() => setExcludedSources([])}>출처 제외 초기화</button>}
              </div>
            </details>
            {viewMode !== "hidden" && <TechMultiSelect values={technologies} options={includedTechOptions} onToggle={toggleTechnology} onClear={() => setTechnologies([])} />}
            <Select ariaLabel="게시 기간" value={postedWithinDays} onChange={setPostedWithinDays} options={POSTED_PERIOD_OPTIONS} />
            <Select ariaLabel="정렬 방식" value={sort} onChange={setSort} options={SORT_OPTIONS} />
            {postedWithinDays && <div className="filter-block posting-date-filter">
              <label className="filter-check"><input type="checkbox" checked={includeUnknownPosted} onChange={(event) => setIncludeUnknownPosted(event.target.checked)} /><span>✓</span><b>게시일 미확인 공고 포함</b></label>
              <p>{includeUnknownPosted
                ? "선택 기간에 게시된 공고와 게시일 미확인 공고를 표시합니다. 미확인 공고의 최근 게시 여부는 알 수 없습니다."
                : "게시일이 확인된 공고만 표시합니다. 게시일 미확인 공고는 제외되므로 결과가 적을 수 있습니다."}</p>
            </div>}
            {viewMode !== "hidden" && <div className="filter-advanced">
              <div className="filter-block">
                <div className="filter-label"><strong>경력 유형</strong><span>복수 선택 가능</span></div>
                <div className="experience-chips">
                  {EXPERIENCE_OPTIONS.map((option) => <button type="button" aria-pressed={experienceTypes.includes(option.value)} className={experienceTypes.includes(option.value) ? "active" : ""} key={option.value} onClick={() => toggleExperience(option.value)}>{option.label}</button>)}
                </div>
              </div>
              <div className="filter-block">
                <div className="filter-label"><strong>요구 연차 범위</strong><span>공고 범위와 겹치면 표시</span></div>
                <div className="year-range">
                  <select aria-label="최소 요구 연차" value={minYears} onChange={(event) => changeMinimumYears(event.target.value)}><option value="">최소 전체</option>{YEAR_OPTIONS.map((year) => <option value={year} key={year}>{year}년</option>)}</select>
                  <span>~</span>
                  <select aria-label="최대 요구 연차" value={maxYears} onChange={(event) => changeMaximumYears(event.target.value)}><option value="">최대 전체</option>{YEAR_OPTIONS.map((year) => <option value={year} key={year}>{year}년</option>)}</select>
                </div>
              </div>
              <div className="filter-block process-filter">
                <div className="filter-label"><strong>채용 절차</strong><span>복수 선택 · 선택 없음은 전체</span></div>
                <div className="process-check-groups">
                  <fieldset><legend>코딩테스트</legend><div className="filter-check-list">{CODING_TEST_OPTIONS.map((option) => <label className="filter-check" key={option.value}><input type="checkbox" checked={codingTests.includes(option.value)} onChange={() => toggleCodingTest(option.value)} /><span>✓</span><b>{option.label}</b></label>)}</div></fieldset>
                  <fieldset><legend>면접 횟수</legend><div className="filter-check-list">{INTERVIEW_COUNT_OPTIONS.map((option) => <label className="filter-check" key={option.value}><input type="checkbox" checked={interviewCounts.includes(option.value)} onChange={() => toggleInterviewCount(option.value)} /><span>✓</span><b>{option.label}</b></label>)}</div></fieldset>
                </div>
              </div>
              <div className="filter-block score-filter">
                <div className="filter-label"><strong>최소 점수</strong><span>미분석·기준 미만 공고 제외</span></div>
                <div className="score-filter-controls">
                  <label><span>적합도</span><select aria-label="최소 적합도" value={minFitScore} onChange={(event) => setMinFitScore(event.target.value)}><option value="">전체 점수</option>{SCORE_THRESHOLDS.map((score) => <option value={score} key={score}>{score}점 이상</option>)}</select></label>
                  <label><span>지원가치</span><select aria-label="최소 지원가치" value={minValueScore} onChange={(event) => setMinValueScore(event.target.value)}><option value="">전체 점수</option>{SCORE_THRESHOLDS.map((score) => <option value={score} key={score}>{score}점 이상</option>)}</select></label>
                </div>
              </div>
              <div className="filter-block exclude-filter">
                <div className="filter-label"><strong>기술 스택 제외</strong><span>기본 제외 없음 · Java·Spring 필수 여부는 점수에 반영</span></div>
                <div className="exclude-controls">
                  <select aria-label="제외할 기술 스택 추가" value="" onChange={(event) => addExcludedTech(event.target.value)}><option value="">+ 제외 기술 추가</option>{exclusionOptions.map((item) => <option value={item} key={item}>{item}</option>)}</select>
                  <div className="excluded-tech-chips">
                    {excludedTech.length ? excludedTech.map((item) => <button type="button" aria-label={`${item} 제외 해제`} title="클릭해서 제외 해제" key={item} onClick={() => removeExcludedTech(item)}><span>{item}</span><b>×</b></button>) : <span className="no-exclusion">제외 기술 없음</span>}
                  </div>
                </div>
              </div>
            </div>}
            <div className={filterStorageAvailable ? "filter-storage" : "filter-storage unavailable"} role="status">
              <span><i>{filterStorageAvailable ? "✓" : "!"}</i>{viewMode === "hidden" ? "숨긴 공고에서는 검색·사이트·게시 기간·정렬만 적용됩니다." : filterStorageAvailable ? "필터 선택이 이 브라우저에 자동 저장됩니다." : "브라우저 저장소를 사용할 수 없어 현재 탭에서만 유지됩니다."}</span>
              <button type="button" onClick={resetFilters}>필터 초기화</button>
            </div>
          </div>
          <div className="result-summary" role="status" aria-live="polite" aria-busy={currentResults.isLoading || currentResults.isFetching}>
            <div><span>FILTER RESULTS</span><strong>{currentResults.isLoading ? "계산 중…" : currentResults.isError ? "집계 실패" : `총 ${totalResultCount.toLocaleString()}개`}</strong>{currentResults.isFetching && !currentResults.isLoading && <i>갱신 중</i>}</div>
            {!currentResults.isLoading && !currentResults.isError && <p>{visibleResultCount < totalResultCount ? `${resultScope} ${totalResultCount.toLocaleString()}개 중 현재 ${visibleResultCount.toLocaleString()}개를 표시합니다.` : `${resultScope} ${visibleResultCount.toLocaleString()}개를 모두 표시합니다.`}</p>}
          </div>
          <div className="score-guide"><span><b>적합도</b> 지금 이력서로 필수업무를 수행할 수 있는 정도</span><span><b>지원가치</b> 적합도에 커리어 방향·현실적인 성장 기회를 더한 지원 우선순위</span><button className="score-info-button" aria-label="적합도와 지원가치 설명 보기" onClick={() => setScoreInfoOpen(true)}><i>i</i> 점수 설명</button></div>

          {displayMode === "map" ? <Suspense fallback={<LoadingRows />}><JobMap data={mapJobs.data} loading={mapJobs.isLoading || mapJobs.isFetching} error={mapJobs.isError} onEvidence={setEvidenceJobId} /></Suspense> : jobs.isLoading ? <LoadingRows /> : jobs.isError ? <Empty title="API에 연결할 수 없습니다" body="백엔드가 실행 중인지 확인해 주세요." /> : jobs.data?.items.length ? (
            <div className="job-table-wrap">
              <table className="job-table">
                <thead><tr><th>관심</th><th>지원</th><th>숨김</th><th>비교</th><th>포지션</th><th>기술 스택</th><th>경력·근무지</th><th>적합도 / 추천 이력서</th><th>마감</th><th>게시일</th><th>링크</th></tr></thead>
                <tbody>{jobs.data.items.map((job) => <JobRow key={job.id} job={job} checked={selected.includes(job.id)} favoritePending={favorite.isPending && favorite.variables?.jobId === job.id} applicationPending={application.isPending && application.variables?.jobId === job.id} visibilityPending={visibility.isPending && visibility.variables?.jobIds.includes(job.id)} onToggle={() => toggleSelected(job.id)} onFavorite={() => favorite.mutate({ jobId: job.id, isFavorite: !job.is_favorite })} onApplication={() => application.mutate({ jobId: job.id, status: SUBMITTED_APPLICATION_STATUSES.has(job.application_status) ? "not_reviewed" : "applied" })} onVisibility={() => visibility.mutate({ jobIds: [job.id], hidden: !job.is_hidden })} onEvidence={() => setEvidenceJobId(job.id)} />)}</tbody>
              </table>
            </div>
          ) : <Empty title={emptyCopy.title} body={emptyCopy.body} />}
        </section>
      </main>}

      {!dailyOpen && selected.length > 0 && !compareOpen && (
        <div className="selection-bar" role="status">
          <div><strong>{selected.length}개 공고 선택</strong><span>최대 4개까지 나란히 비교할 수 있어요.</span></div>
          <div><button className="selection-clear" onClick={() => setSelected([])}>비우기</button><button className="selection-visibility" disabled={visibility.isPending} onClick={() => visibility.mutate({ jobIds: selected, hidden: !restoringSelection })}>{restoringSelection ? "선택 복원" : "선택 숨기기"}</button><button className="selection-open" onClick={() => setCompareOpen(true)}>선택한 공고 비교</button></div>
        </div>
      )}

      {!dailyOpen && selected.length > 0 && compareOpen && (
        <aside className="compare-dock">
          <div className="compare-title"><div><p>COMPARE</p><h2>{selected.length}개 공고 비교</h2></div><button onClick={() => setCompareOpen(false)}>목록으로 돌아가기</button></div>
          <div className="compare-grid">
            {comparison.map((result, index) => result.data ? <CompareCard key={result.data.id} job={result.data} onClose={() => { toggleSelected(selected[index]); if (selected.length === 1) setCompareOpen(false); }} /> : <div className="compare-loading" key={selected[index]}>불러오는 중…</div>)}
          </div>
        </aside>
      )}

      {evidenceJobId != null && (
        <EvidenceModal
          job={evidence.data}
          loading={evidence.isLoading}
          aiStatus={aiStatus.data}
          aiModel={aiModel}
          onClose={() => setEvidenceJobId(null)}
        />
      )}

      {collectionOpen && (
        <CollectionPanel
          latestRuns={latestRuns}
          pending={startCrawl.isPending}
          importing={importRocket.isPending}
          onStart={(sourceNames) => startCrawl.mutate(sourceNames)}
          onImport={(file, url) => importRocket.mutate({ file, url })}
          onClose={() => setCollectionOpen(false)}
        />
      )}

      {advisorOpen && (
        <RecommendationPanel
          aiStatus={aiStatus.data}
          aiModel={aiModel}
          onClose={() => setAdvisorOpen(false)}
          onEvidence={(jobId) => setEvidenceJobId(jobId)}
        />
      )}

      {scoreInfoOpen && <ScoreInfoModal onClose={() => setScoreInfoOpen(false)} />}
    </div>
  );
}

function DailyRecommendationsPage({ dates, datesLoading, onClose, onEvidence, onGenerate, generating, todayGenerated, onOpenAdvisor }: {
  dates: DailyRecommendationDate[];
  datesLoading: boolean;
  onClose: () => void;
  onEvidence: (jobId: number) => void;
  onGenerate: () => void;
  generating: boolean;
  todayGenerated: boolean;
  onOpenAdvisor: () => void;
}) {
  const [selectedDate, setSelectedDate] = useState("");
  useEffect(() => {
    if (!selectedDate && dates[0]?.date) setSelectedDate(dates[0].date);
    if (selectedDate && dates.length && !dates.some((item) => item.date === selectedDate)) {
      setSelectedDate(dates[0].date);
    }
  }, [dates, selectedDate]);
  const recommendations = useQuery({
    queryKey: ["daily-recommendations", selectedDate],
    queryFn: () => getJson<DailyRecommendationResponse>(`/api/daily-recommendations?date=${encodeURIComponent(selectedDate)}`),
    enabled: Boolean(selectedDate),
  });
  const selectedSummary = dates.find((item) => item.date === selectedDate);
  const slackLabel = selectedSummary?.slack_status === "sent"
    ? "Slack 전송 완료"
    : selectedSummary?.slack_status === "failed"
      ? "Slack 전송 실패"
      : selectedSummary?.slack_status === "disabled"
        ? "Slack 알림 꺼짐"
        : "추천 저장 완료";

  return <main className="daily-page">
    <section className="daily-hero">
      <div><p>DAILY OPPORTUNITY DIGEST</p><h1>오늘의 추천 공고</h1><span>매일 수집이 끝난 뒤 활성 공고 중 적합도와 지원가치가 높은 공고를 저장합니다.</span></div>
      <button onClick={onClose}>← 전체 공고로</button>
    </section>
    <section className="daily-action-strip" aria-label="즉시 추천과 리포트">
      <div><strong>현재 DB에서 바로 큐레이션</strong><span>재수집 없이 지금 저장된 활성 공고를 다시 점수순으로 선별합니다. Slack은 자동 전송하지 않습니다.</span></div>
      <div>
        <button className="daily-generate-button" disabled={datesLoading || generating || todayGenerated} title={todayGenerated ? "오늘의 추천에 이미 반영되었습니다." : "현재 DB 공고에서 오늘 추천을 선별합니다."} onClick={onGenerate}>{datesLoading ? "추천 확인 중…" : generating ? "추천 선별 중…" : todayGenerated ? "✓ 오늘 추천 완료" : "✦ 지금 바로 추천받기"}</button>
        <button className="daily-chat-button" onClick={onOpenAdvisor}>채팅으로 조건 추천</button>
        {selectedDate && <a className="daily-report-button" href={`${API_URL}/api/daily-recommendations/report?date=${encodeURIComponent(selectedDate)}`}>Markdown 리포트 저장</a>}
      </div>
    </section>
    <section className="daily-layout">
      <aside className="daily-history" aria-label="날짜별 추천 히스토리">
        <div><p>HISTORY</p><h2>날짜별 추천</h2></div>
        {datesLoading ? <div className="daily-history-loading">히스토리 불러오는 중…</div> : dates.length ? dates.map((item) => (
          <button className={selectedDate === item.date ? "active" : ""} key={item.date} onClick={() => setSelectedDate(item.date)}>
            <span>{new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "long", day: "numeric", weekday: "short" }).format(new Date(`${item.date}T00:00:00`))}</span>
            <b>{item.item_count}개</b>
          </button>
        )) : <p className="daily-history-empty">아직 생성된 추천이 없습니다. 일일 수집 후 자동으로 쌓입니다.</p>}
      </aside>
      <div className="daily-results">
        <div className="daily-results-head">
          <div><p>{selectedDate || "추천 대기"}</p><h2>{selectedDate ? "지원 우선순위" : "첫 추천을 기다리고 있습니다"}</h2></div>
          {selectedSummary && <span className={`daily-slack-state ${selectedSummary.slack_status}`}>{slackLabel}</span>}
        </div>
        {recommendations.isLoading ? <LoadingRows /> : recommendations.isError ? <Empty title="추천을 불러올 수 없습니다" body="백엔드 연결 상태를 확인해 주세요." /> : recommendations.data?.items.length ? (
          <div className="daily-card-list">{recommendations.data.items.map((job) => <article className="daily-job-card" key={job.job_id}>
            <span className="daily-rank">{String(job.rank).padStart(2, "0")}</span>
            <div className="daily-job-main"><div><span className={`source-pill ${job.source}`}>{sourceLabels[job.source] ?? job.source}</span><span>{job.company}</span></div><h3>{job.title}</h3><p>{job.experience_text || "경력 정보 없음"} · {job.location || "근무지 미상"}</p><div className="tech-list">{job.tech_stack.slice(0, 7).map((tech) => <span key={tech}>{tech}</span>)}</div></div>
            <div className="daily-job-score"><div><span>적합도</span><strong>{formatScore(job.fit_score)}</strong></div><div><span>지원가치</span><strong>{formatScore(job.application_value_score)}</strong></div></div>
            <div className="daily-job-actions"><button onClick={() => onEvidence(job.job_id)}>근거 보기</button><a href={job.url} target="_blank" rel="noreferrer">공고 열기 ↗</a></div>
          </article>)}</div>
        ) : <Empty title="이 날짜의 추천 공고가 없습니다" body="점수 기준을 충족한 새 공고가 없거나 아직 일일 수집 전입니다." />}
      </div>
    </section>
  </main>;
}

function EcosystemPage({ organizations, organizationsLoading, programs, programsLoading, newCount, runs, collecting, onCollect, onClose }: {
  organizations: EcosystemOrganization[];
  organizationsLoading: boolean;
  programs: EcosystemProgram[];
  programsLoading: boolean;
  newCount: number;
  runs: EcosystemCrawlRun[];
  collecting: boolean;
  onCollect: () => void;
  onClose: () => void;
}) {
  const latestRuns = useMemo(() => {
    const latest: Record<string, EcosystemCrawlRun> = {};
    for (const run of runs) if (!latest[run.organization_slug]) latest[run.organization_slug] = run;
    return latest;
  }, [runs]);
  return <main className="ecosystem-page">
    <section className="ecosystem-hero">
      <div><p>FOUNDER × INVESTOR HYPOTHESIS</p><h1>나와 맞을 가능성이 있는<br /><em>투자사와 IR·배치 기회</em></h1><span>get-job의 현재 단계와 제품 특성을 기준으로 AC·VC·엔젤 후보를 1차 정렬하고, 공개 IR·상담·데모데이를 매일 확인합니다.</span></div>
      <div><button onClick={onClose}>← 전체 공고로</button><button className="ecosystem-collect-button" disabled={collecting} onClick={onCollect}>{collecting ? "수집 시작 중…" : "↻ 투자·배치 수집"}</button></div>
    </section>
    <section className="ecosystem-summary">
      <article><span>매칭 투자·지원 기관</span><strong>{organizationsLoading ? "—" : organizations.length}</strong><small>제품·단계 1차 가설 순</small></article>
      <article><span>지원 가능한 기회</span><strong>{programsLoading ? "—" : programs.length}</strong><small>투자 검토·배치·교육·데모데이</small></article>
      <article className="accent"><span>최근 7일 신규</span><strong>{newCount}</strong><small>새로 발견된 프로그램</small></article>
    </section>
    <aside className="ecosystem-methodology"><strong>이 점수는 투자 가능성 예측이 아닙니다.</strong><span>현재 저장소의 제품 설명을 바탕으로 초기 단계·소프트웨어·AI·B2C/생산성 도구 성향을 대조한 1차 가설입니다. VCS 근거가 표시된 기관은 ICT서비스 + AI·빅데이터 + 창업초기 + 업력 0~3년 공식 검색조건에 포함됐다는 뜻이며, 나머지는 공개 포지셔닝을 바탕으로 한 우선 조사 순서입니다. 실제 판단 전 포트폴리오·투자단계·티켓·담당 심사역 검증이 필요합니다.</span></aside>
    <section className="ecosystem-section">
      <div className="ecosystem-section-head"><div><p>NEW OPPORTUNITIES</p><h2>확인할 투자·IR·행사 기회</h2></div><span>공개 페이지에서만 수집 · 로그인·신청 자동화 없음</span></div>
      {programsLoading ? <LoadingRows /> : programs.length ? <div className="program-grid">{programs.map((program) => {
        const isNew = isNewlyCollected(program.first_seen_at);
        return <article className="program-card" key={program.id}>
          <div><span className="program-org">{program.organization_name} · {program.organization_type}</span>{isNew && <span className="new-pill">신규</span>}</div>
          <h3>{program.title}</h3>
          <p>{program.summary || "공개 모집 페이지에서 확인된 프로그램입니다."}</p>
          <footer><span className={`program-kind ${program.program_type}`}>{program.program_type === "batch" ? "투자·배치" : program.program_type === "investment" ? "투자 검토" : program.program_type === "education" ? "교육" : program.program_type === "demo_day" ? "IR·데모데이" : "프로그램"}</span><span>{program.deadline_text ? `기준일 ${program.deadline_text}` : program.is_open ? "공고 내용 확인" : "종료 여부 확인"}</span><a href={program.url} target="_blank" rel="noreferrer">{program.organization_slug.startsWith("vcs-") ? "공고 보기 ↗" : "지원하기 ↗"}</a></footer>
        </article>;
      })}</div> : <Empty title="아직 지원 가능한 투자·배치 기회가 없습니다" body="수집을 실행하면 프라이머·뉴키즈인베스트먼트·디캠프·블루포인트의 공개 지원 페이지부터 확인합니다." />}
    </section>
    <section className="ecosystem-section organization-section">
      <div className="ecosystem-section-head"><div><p>HYPOTHESIS-RANKED DIRECTORY</p><h2>우선 검토할 투자사·지원기관</h2></div><span>현재 제품: 로컬 우선 AI 채용 탐색 · 초기 단계 가정</span></div>
      {organizationsLoading ? <LoadingRows /> : <div className="organization-grid">{organizations.map((organization) => {
        const run = latestRuns[organization.slug];
        const priorityBand = organization.fit_score >= 90 ? "우선 검토 A" : organization.fit_score >= 80 ? "우선 검토 B" : organization.fit_score >= 70 ? "추가 검토 C" : "조건부 검토";
        return <article className="organization-card" key={organization.slug}><div><span className="organization-type">{organization.organization_type}</span><span className="fit-score">{priorityBand}</span><span className={organization.monitored ? "monitor-state active" : "monitor-state"}>{organization.monitored ? "공개 페이지 감시" : "목록만 제공"}</span></div><h3>{organization.name}</h3><p className="organization-fit-reason">{organization.fit_reason || organization.summary}</p>{organization.focus_tags.length ? <div className="organization-tags">{organization.focus_tags.map((tag) => <span key={tag}>{tag}</span>)}</div> : null}<footer><span>{organization.operating_scale ? `VCS 운용규모 ${organization.operating_scale}` : run?.status === "running" ? "수집 중" : run?.finished_at ? `마지막 확인 ${new Intl.DateTimeFormat("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(run.finished_at))}` : "아직 수집 전"}</span><a href={organization.source_url || organization.program_url || organization.website_url} target="_blank" rel="noreferrer">{organization.source_url ? "VCS 근거 ↗" : organization.program_url ? "지원 페이지 ↗" : "공식 사이트 ↗"}</a></footer></article>;
      })}</div>}
    </section>
  </main>;
}

function CollectionPanel({ latestRuns, pending, importing, onStart, onImport, onClose }: {
  latestRuns: Record<string, CrawlRun>;
  pending: boolean;
  importing: boolean;
  onStart: (sources: string[]) => void;
  onImport: (file: File, url: string) => void;
  onClose: () => void;
}) {
  const [rocketFile, setRocketFile] = useState<File | null>(null);
  const [rocketUrl, setRocketUrl] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>(
    automaticSources.filter((source) => source !== "saramin")
  );
  const resultQueries = useQueries({
    queries: automaticSources.map((source) => {
      const run = latestRuns[source];
      return {
        queryKey: ["crawl-run-results", run?.id ?? source],
        queryFn: () => getJson<CrawlResultItem[]>(`/api/crawl/runs/${run?.id}/results`),
        enabled: Boolean(run?.finished_at && run.status !== "failed"),
        staleTime: Infinity,
      };
    }),
  });
  const selectedRunning = selectedSources.some(
    (source) => latestRuns[source]?.status === "running"
  );
  const toggleSource = (source: string) => setSelectedSources((current) =>
    current.includes(source) ? current.filter((item) => item !== source) : [...current, source]
  );
  const allSelected = selectedSources.length === automaticSources.length;
  return <aside className="collection-panel" aria-label="사이트별 수집 및 분석">
    <div className="collection-head"><div><p>COLLECTION CENTER</p><h2>사이트별 수집·분석</h2><span>작업은 백그라운드에서 실행됩니다. 이 창을 닫아도 계속 진행돼요.</span></div><button aria-label="수집 창 닫기" onClick={onClose}>×</button></div>
    <div className="collection-actions">
      <button className="collect-all" disabled={pending || selectedRunning || selectedSources.length === 0} onClick={() => onStart(selectedSources)}>↻ 선택한 {selectedSources.length}개 사이트 수집 시작</button>
      <button className="select-all" onClick={() => setSelectedSources(allSelected ? [] : [...automaticSources])}>{allSelected ? "전체 해제" : "전체 선택"}</button>
      <small>체크한 사이트는 동시에 시작되고 각각 백그라운드에서 진행됩니다.</small>
    </div>
    <div className="source-run-grid">
      {automaticSources.map((source, index) => {
        const run = latestRuns[source];
        const running = run?.status === "running";
        const progress = crawlProgress(run);
        const resultItems = resultQueries[index].data ?? [];
        return <article className={selectedSources.includes(source) ? "source-run-card selected-source" : "source-run-card"} key={source}>
          <div className="source-run-head"><label className="source-check"><input type="checkbox" aria-label={`${sourceLabels[source]} 수집 선택`} checked={selectedSources.includes(source)} disabled={running} onChange={() => toggleSource(source)} /><span>✓</span><b className={`source-pill ${source}`}>{sourceLabels[source]}</b></label><RunStatus run={run} /></div>
          <div className={running && progress == null ? "crawl-progress indeterminate" : "crawl-progress"} role="progressbar" aria-label={`${sourceLabels[source]} 수집 진행률`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress ?? undefined}><i style={{ width: `${progress ?? 35}%` }} /></div>
          <p>{run ? running ? `페이지 ${run.pages_visited.toLocaleString()} · 발견 ${run.jobs_found ? run.jobs_found.toLocaleString() : "탐색 중"}` : `발견 ${run.jobs_found.toLocaleString()} · 신규 ${run.jobs_created.toLocaleString()} · 갱신 ${run.jobs_updated.toLocaleString()} · 실패 ${run.jobs_failed.toLocaleString()}` : source === "saramin" ? "공식 API 승인 키 설정 후 수집할 수 있습니다." : "아직 실행 이력이 없습니다."}</p>
          {run && <CrawlRunTiming run={run} />}
          {run?.error && <small className="run-error">{run.error}</small>}
          {run?.finished_at && run.status !== "failed" && <CrawlResultSummary items={resultItems} loading={resultQueries[index].isLoading} />}
          <button disabled={pending || running} onClick={() => onStart([source])}>{running ? "수집·분석 중…" : "이 사이트만 다시 수집"}</button>
        </article>;
      })}
      <article className="source-run-card rocket-import">
        <div><span className="source-pill rocketpunch">로켓펀치</span><span className="run-state manual">저장 HTML</span></div>
        <p>사이트 정책에 따라 저장한 공고 HTML을 안전하게 가져옵니다.</p>
        <input value={rocketUrl} onChange={(event) => setRocketUrl(event.target.value)} placeholder="공개 공고 URL" />
        <label className="file-field"><input type="file" accept="text/html,.html,.htm" onChange={(event) => setRocketFile(event.target.files?.[0] ?? null)} /><span>{rocketFile?.name ?? "HTML 파일 선택"}</span></label>
        <button disabled={importing || !rocketFile || !rocketUrl.trim()} onClick={() => rocketFile && onImport(rocketFile, rocketUrl.trim())}>{importing ? "가져오기·분석 중…" : "HTML 가져오기·분석"}</button>
      </article>
    </div>
  </aside>;
}

const CRAWL_TIME_FORMAT = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function CrawlRunTiming({ run }: { run: CrawlRun }) {
  const timestamp = (value: string) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? <span>시간 기록 없음</span>
      : <time dateTime={value}>{CRAWL_TIME_FORMAT.format(date)}</time>;
  };
  return <section className="crawl-run-timing" aria-label="최근 수집 시작 및 종료 시각">
    <span>최근 수집 · 한국 시간 (KST)</span>
    <dl>
      <div><dt>시작</dt><dd>{timestamp(run.started_at)}</dd></div>
      <div><dt>종료</dt><dd>{run.finished_at ? timestamp(run.finished_at) : run.status === "running" ? "수집 중…" : "종료 기록 없음"}</dd></div>
    </dl>
  </section>;
}

function crawlProgress(run?: CrawlRun): number | null {
  if (!run) return 0;
  if (run.status !== "running") return 100;
  if (!run.jobs_found) return null;
  return Math.min(95, Math.max(3, Math.round(run.pages_visited / (run.jobs_found + 1) * 100)));
}

function CrawlResultSummary({ items, loading }: { items: CrawlResultItem[]; loading: boolean }) {
  if (loading) return <div className="crawl-result-loading">완료 결과 정리 중…</div>;
  const counts = items.reduce((result, item) => {
    result[item.status] += 1;
    return result;
  }, { created: 0, updated: 0, seen: 0 });
  return <div className="crawl-results">
    <div><strong>수집 완료</strong><span>신규 {counts.created} · 갱신 {counts.updated} · 재확인 {counts.seen}</span></div>
    {items.slice(0, 2).map((item) => <a href={item.url} target="_blank" rel="noreferrer" key={item.id}><b>{item.title}</b><span>{item.company}</span></a>)}
    {items.length > 0 ? <details><summary>수집한 공고 {items.length}건 모두 보기</summary><div>{items.map((item) => <a href={item.url} target="_blank" rel="noreferrer" key={item.id}><b>{item.title}</b><span>{item.company} · {item.status === "created" ? "신규" : item.status === "updated" ? "갱신" : "재확인"}</span></a>)}</div></details> : <p>이번 실행에서 대상 직무로 저장된 공고가 없습니다.</p>}
  </div>;
}

function RunStatus({ run }: { run?: CrawlRun }) {
  if (!run) return <span className="run-state idle">대기</span>;
  const labels = { running: "진행 중", succeeded: "완료", partial: "일부 완료", failed: "실패" };
  return <span className={`run-state ${run.status}`}>{labels[run.status]}</span>;
}

function Stat({ label, value, note, accent = false }: { label: string; value: number; note: string; accent?: boolean }) {
  return <article className={accent ? "stat-card accent" : "stat-card"}><span>{label}</span><strong>{value.toLocaleString()}</strong><small>{note}</small></article>;
}

function Select({ ariaLabel, value, onChange, options }: { ariaLabel: string; value: string; onChange: (value: string) => void; options: { value: string; label: string }[] }) {
  return <label className="select-field"><select aria-label={ariaLabel} value={value} onChange={(e) => onChange(e.target.value)}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select><span>⌄</span></label>;
}

function TechMultiSelect({ values, options, onToggle, onClear }: {
  values: string[];
  options: string[];
  onToggle: (value: string) => void;
  onClear: () => void;
}) {
  const [search, setSearch] = useState("");
  const visibleOptions = useMemo(() => {
    const keyword = search.trim().toLocaleLowerCase();
    return keyword
      ? options.filter((option) => option.toLocaleLowerCase().includes(keyword))
      : options;
  }, [options, search]);
  return <details className="multi-select-field">
    <summary><span>{values.length ? `기술 ${values.length}개 선택` : "전체 기술"}</span><b>⌄</b></summary>
    <div className="multi-select-menu">
      <input aria-label="기술 스택 검색" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="기술 검색" />
      <div className="multi-option-list">
        {visibleOptions.length ? visibleOptions.map((option) => <label className="filter-check" key={option}><input type="checkbox" checked={values.includes(option)} onChange={() => onToggle(option)} /><span>✓</span><b>{option}</b></label>) : <p>일치하는 기술이 없습니다.</p>}
      </div>
      {values.length > 0 && <button type="button" onClick={onClear}>기술 선택 초기화</button>}
    </div>
  </details>;
}

function AIModelPicker({ models, value, status, refreshing, onChange, onRefresh }: {
  models: string[];
  value: string;
  status?: AIStatus;
  refreshing: boolean;
  onChange: (value: string) => void;
  onRefresh: () => void;
}) {
  return <div className={`ai-model-picker ${status?.available ? "connected" : "offline"}`} title={status?.message ?? "로컬 AI 상태 확인 중"}>
    <i />
    <label><span>{status?.provider === "codex" ? "CODEX GPT" : status?.local_only === false ? "REMOTE MODEL" : "LOCAL MODEL"}</span><select aria-label="분석에 사용할 AI 모델" value={value} onChange={(event) => onChange(event.target.value)}>{models.map((model) => <option value={model} key={model}>{model === "auto" ? `자동${status?.active_model ? ` · ${status.active_model}` : ""}` : `${model}${status?.models.length && !status.models.includes(model) ? " · 미연결" : ""}`}</option>)}</select></label>
    <button aria-label="로컬 AI 모델 목록 새로고침" className={refreshing ? "refreshing" : ""} onClick={onRefresh}>↻</button>
  </div>;
}

function ScoreInfoModal({ onClose }: { onClose: () => void }) {
  return <div className="score-info-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="score-info-modal" role="dialog" aria-modal="true" aria-labelledby="score-info-title">
      <div className="score-info-head"><div><p>SCORE GUIDE</p><h2 id="score-info-title">적합도와 지원가치는 무엇이 다른가요?</h2></div><button aria-label="점수 설명 닫기" onClick={onClose}>×</button></div>
      <div className="score-info-grid">
        <article><span className="score-info-number">01</span><h3>적합도 · 지금 수행할 수 있는가</h3><p>현재 이력서의 실제 근거로 이 공고의 역할과 필수업무를 바로 수행할 수 있는 정도입니다.</p><dl><div><dt>직무 방향</dt><dd>18%</dd></div><div><dt>필수 기술</dt><dd>22%</dd></div><div><dt>우대·인접 기술</dt><dd>8%</dd></div><div><dt>경력 조건</dt><dd>12%</dd></div><div><dt>업무 경험 근거</dt><dd>14%</dd></div><div><dt>운영·데이터</dt><dd>9%</dd></div><div><dt>설계·오너십</dt><dd>7%</dd></div><div><dt>품질·협업</dt><dd>5%</dd></div><div><dt>공고 근거 품질</dt><dd>5%</dd></div></dl><small>필수 기술은 공고의 강조도와 이력서 성과 근거 깊이까지 가중합니다. 기술 격차와 근거 부족은 연속 감점하고, 명확한 직무 불일치에만 상한을 둡니다.</small></article>
        <article><span className="score-info-number">02</span><h3>지원가치 · 먼저 지원할 만한가</h3><p>현재 적합도뿐 아니라 내 커리어 방향과 현실적인 성장 여지를 함께 본 지원 우선순위입니다.</p><dl><div><dt>적합도</dt><dd>62%</dd></div><div><dt>직무·업무 방향성</dt><dd>23%</dd></div><div><dt>현실적인 성장 기회</dt><dd>10%</dd></div><div><dt>공고 근거 품질</dt><dd>5%</dd></div></dl><small>점수는 0.1점 단위로 표시합니다. 동점이면 서류 경쟁력, 다른 핵심 점수, 최신 공고 순서로 정렬합니다. 연봉·통근·회사 안정성은 현재 포함되지 않습니다.</small></article>
      </div>
      <div className="score-info-example"><b>읽는 법</b><p><strong>적합도</strong>는 “내가 지금 잘할 수 있나?”, <strong>지원가치</strong>는 “여기에 먼저 지원할 이유가 충분한가?”에 답합니다. 두 점수가 다르면 근거 버튼에서 직무 방향과 기술 격차를 확인하세요.</p></div>
    </section>
  </div>;
}

function JobRow({ job, checked, favoritePending, applicationPending, visibilityPending, onToggle, onFavorite, onApplication, onVisibility, onEvidence }: { job: Job; checked: boolean; favoritePending: boolean; applicationPending: boolean; visibilityPending: boolean; onToggle: () => void; onFavorite: () => void; onApplication: () => void; onVisibility: () => void; onEvidence: () => void }) {
  const deadline = deadlineDisplay(job.deadline_at, job.is_active);
  const isNew = isNewlyCollected(job.first_seen_at);
  const isApplied = SUBMITTED_APPLICATION_STATUSES.has(job.application_status);
  const applicationLabel = APPLICATION_STATUS_LABELS[job.application_status] ?? "지원 완료";
  return <tr className={[checked ? "selected" : "", job.is_hidden ? "hidden-job" : "", job.is_favorite ? "favorite-job" : ""].filter(Boolean).join(" ")}>
    <td><button type="button" className={job.is_favorite ? "favorite-button active" : "favorite-button"} aria-label={job.is_favorite ? `${job.title} 관심 공고 해제` : `${job.title} 관심 공고 저장`} aria-pressed={job.is_favorite} title={job.is_favorite ? "관심 공고 해제" : "관심 공고 저장"} disabled={favoritePending} onClick={onFavorite}>{job.is_favorite ? "♥" : "♡"}</button></td>
    <td><button type="button" className={isApplied ? "application-button active" : "application-button"} aria-label={isApplied ? `${job.title} 지원 완료 표시 해제` : `${job.title} 지원 완료로 표시`} aria-pressed={isApplied} title={isApplied ? "지원 완료 표시 해제" : "지원 완료로 표시"} disabled={applicationPending} onClick={onApplication}><span>{isApplied ? "✓" : "○"}</span><b>{isApplied ? "완료" : "미지원"}</b></button></td>
    <td><button type="button" className={job.is_hidden ? "visibility-button restore" : "visibility-button"} aria-label={job.is_hidden ? `${job.title} 숨김 해제` : `${job.title} 숨기기`} title={job.is_hidden ? "숨김 해제" : "이 공고 숨기기"} disabled={visibilityPending} onClick={onVisibility}><span>{job.is_hidden ? "↶" : "⊘"}</span><b>{job.is_hidden ? "복원" : "숨김"}</b></button></td>
    <td><button aria-label={`${job.title} 비교 선택`} className={checked ? "check checked" : "check"} onClick={onToggle}>{checked ? "✓" : ""}</button></td>
    <td><div className="position-cell"><div><span className={`source-pill ${job.source}`}>{sourceLabels[job.source] ?? job.source}</span>{job.duplicate_count > 1 && <span className="duplicate-pill">{job.duplicate_count}개 소스 묶음</span>}{isNew && <span className="new-pill" title="최근 7일 내 수집된 공고">신규</span>}{isApplied && <span className={`applied-pill ${job.application_status}`}>{applicationLabel}</span>}{job.is_hidden && <span className="hidden-pill">숨김</span>}</div><strong>{job.title}</strong><small>{job.company}</small></div></td>
    <td><div className="tech-list">{job.tech_stack.slice(0, 4).map((item) => <span key={item}>{item}</span>)}{job.tech_stack.length > 4 && <span>+{job.tech_stack.length - 4}</span>}</div></td>
    <td><div className="meta-cell"><span>{job.experience_text || "경력 정보 없음"}</span><small>{job.location || "근무지 미상"}</small>{job.availability_check && <small title={`확인: ${new Date(job.availability_check.checked_at).toLocaleString("ko-KR")}`}>{job.availability_check.status === "open" ? "모집 중 확인" : job.availability_check.status === "closed" ? "마감 확인" : job.availability_check.status === "old" ? "올해 이전 게시" : "모집 상태 미확인"}</small>}<small className="hiring-process-summary" title={job.hiring_process.join(" → ") || "공고에 채용 절차가 명시되지 않았습니다."}>{hiringProcessSummary(job)}</small></div></td>
    <td><div className="score-cell"><div><span>적합</span><strong>{formatScore(job.total_fit_score)}</strong></div><div><span>가치</span><strong>{formatScore(job.application_value_score)}</strong></div><b>{job.recommendation_grade || job.grade || "미분석"}</b><button className="evidence-button" onClick={onEvidence} disabled={job.total_fit_score == null}>근거</button>{job.recommended_resume_type && <button className="resume-result-chip" onClick={onEvidence}>제출: {job.recommended_resume_type.replace(" 이력서", "")}</button>}</div></td>
    <td><div className={`deadline-cell ${deadline.tone}`}>{job.deadline_at ? <time dateTime={job.deadline_at}>{deadline.date}</time> : <span>{deadline.date}</span>}<strong>{deadline.countdown}</strong></div></td>
    <td><time>{new Intl.DateTimeFormat("ko-KR", { year: "2-digit", month: "2-digit", day: "2-digit" }).format(new Date(job.posted_at ?? job.first_seen_at))}</time></td>
    <td><div className={job.duplicate_postings.length > 1 ? "row-actions bundled" : "row-actions"}>{job.duplicate_postings.length > 1 ? job.duplicate_postings.map((posting) => <a className={posting.is_active ? "source-open-link" : "source-open-link closed"} aria-label={`${job.title} ${sourceLabels[posting.source] ?? posting.source} 원문 열기`} href={posting.url} target="_blank" rel="noreferrer" key={posting.id}>{sourceLabels[posting.source] ?? posting.source} ↗</a>) : <a className="open-link" aria-label={`${job.title} 원문 열기`} href={job.url} target="_blank" rel="noreferrer">↗</a>}</div></td>
  </tr>;
}

function EvidenceModal({ job, loading, aiStatus, aiModel, onClose }: { job?: JobDetail; loading: boolean; aiStatus?: AIStatus; aiModel: string; onClose: () => void }) {
  const aiEvidence = useQuery({
    queryKey: ["ai-evidence", job?.id, aiModel],
    queryFn: () => postJson<AIJobEvidence>(`/api/ai/jobs/${job!.id}/evidence?model=${encodeURIComponent(aiModel)}`),
    enabled: false,
    staleTime: 10 * 60_000,
    retry: false,
  });
  const interviewPrep = useMutation<AIInterviewPrep, Error, boolean>({
    mutationFn: (refresh) => postJson<AIInterviewPrep>(
      `/api/ai/jobs/${job!.id}/interview-prep?model=${encodeURIComponent(aiModel)}&refresh=${refresh}`,
    ),
  });
  return <aside className="evidence-modal" aria-label="적합도 산정 근거">
    <div className="evidence-head">
      <div><p>FIT EVIDENCE</p><h2>{job?.title ?? "적합도 근거 불러오는 중"}</h2>{job && <span>{job.company} · {job.candidate_years_experience ?? "—"}년 경력 프로필</span>}</div>
      <button aria-label="적합도 근거 닫기" onClick={onClose}>×</button>
    </div>
    {loading || !job ? <div className="evidence-loading">계산 근거를 불러오는 중…</div> : <>
      <div className="evidence-summary">
        <div className="evidence-score-grid"><div><span>적합도</span><strong>{formatScore(job.total_fit_score)}</strong></div><div><span>지원가치</span><strong>{formatScore(job.application_value_score)}</strong></div><div><span>서류 경쟁력</span><strong>{formatScore(job.application_probability_score)}</strong></div></div>
        <div><span>분석 요약 · 신뢰도 {job.score_confidence ?? "—"}</span><p>{job.score_summary ?? job.candidate_summary ?? "등록된 후보자 프로필"}</p><small>{job.score_formula}</small><div className="score-definitions"><p><b>적합도</b> {job.score_definitions.fit}</p><p><b>지원가치</b> {job.score_definitions.value}</p><p><b>서류 경쟁력</b> {job.score_definitions.probability}</p></div></div>
      </div>
      <section className="risk-section"><h3>지원 판단</h3><p><b>{job.recommendation_grade ?? "미분석"}</b> · 백엔드 업무 비중 {job.backend_work_share == null ? "미확인" : `약 ${job.backend_work_share}%`} · Java/Spring {job.java_spring_status ?? "미확인"}</p><p>Node.js·TypeScript 전환 가능성: {job.node_typescript_transition ?? "미확인"}</p>{job.tech_stack.includes("Go") && <p>Go 전환 가능성: {job.go_transition ?? "미확인"}</p>}{job.recommendation_reasons.slice(0, 4).map((reason) => <p key={reason}>{reason}</p>)}</section>
      <CompanyFactsSection company={job.company} profile={job.company_profile} />
      {job.resume_recommendation && <ResumeRecommendationSection recommendation={job.resume_recommendation} />}
      <AnalysisPipeline key={job.id} jobId={job.id} />
      <section className="local-ai-evidence">
        <div className="evidence-section-title"><h3>추가 교차검토 · 선택 모델</h3><button disabled={!aiStatus?.available || aiEvidence.isFetching} onClick={() => void aiEvidence.refetch()}>추가 호출 실행</button></div>
        {!aiEvidence.data && !aiEvidence.isFetching && <p className="local-ai-privacy">{aiModel}로 별도 호출합니다. 위의 저비용 분석 예산에는 포함되지 않습니다.</p>}
        {!aiStatus?.available ? <p className="local-ai-unavailable">{aiStatus?.message ?? "로컬 AI 상태를 확인하는 중입니다."} 외부 유료 API로 자동 전환하지 않습니다.</p> : aiEvidence.isLoading ? <p className="local-ai-loading">이력서와 공고 근거를 로컬 모델로 교차검토하는 중…</p> : aiEvidence.isError ? <p className="local-ai-unavailable">{aiEvidence.error instanceof Error ? aiEvidence.error.message : "로컬 AI 분석을 완료하지 못했습니다."} 규칙 기반 점수는 그대로 유지됩니다.</p> : aiEvidence.data && <>
          <p className="local-ai-summary">{aiEvidence.data.summary}</p>
          <div className="local-ai-columns">
            <div><h4>AI가 확인한 강점</h4>{aiEvidence.data.strengths.length ? aiEvidence.data.strengths.map((strength) => <article className="match-card" key={strength.title}><div><strong>{strength.title}</strong><span className="strong-chip">근거 확인</span></div><EvidenceLines label="내 이력서" lines={[strength.profile_evidence]} /><EvidenceLines label="공고 근거" lines={[strength.job_evidence]} /></article>) : <p className="evidence-empty">추가로 확인된 강점이 없습니다.</p>}</div>
            <div><h4>AI가 확인한 보완점</h4>{aiEvidence.data.gaps.length ? aiEvidence.data.gaps.map((gap) => <article className={`gap-card ${gap.severity}`} key={gap.title}><div><strong>{gap.title}</strong><span>{gap.severity === "high" ? "큰 격차" : gap.severity === "medium" ? "보완 필요" : "확인 필요"}</span></div><p>{gap.explanation}</p></article>) : <p className="evidence-empty">추가로 확인된 격차가 없습니다.</p>}</div>
          </div>
          <p className="local-ai-recommendation"><b>지원 제안</b>{aiEvidence.data.recommendation}</p>
          <small className="local-ai-privacy">{aiEvidence.data.provider === "codex" ? "사용자가 허용한 ChatGPT 계정의 Codex GPT로 처리되었습니다." : aiEvidence.data.local_only ? "이 분석은 로컬 AI로만 처리되었습니다." : "사용자가 명시적으로 허용한 외부 AI 연결입니다."}</small>
        </>}
      </section>
      <section className="interview-prep-section">
        <div className="interview-prep-head">
          <div><p>LLM INTERVIEW COACH</p><h3>이 공고 면접 준비 팩</h3><span>공고·이력서·규칙 점수를 근거로 예상 질문과 답변 골격을 만듭니다.</span></div>
          <button type="button" disabled={!aiStatus?.available || interviewPrep.isPending} onClick={() => interviewPrep.mutate(Boolean(interviewPrep.data))}>{interviewPrep.isPending ? "생성 중…" : interviewPrep.data ? "다시 생성" : "면접 팩 생성"}</button>
        </div>
        {!aiStatus?.available ? <p className="interview-prep-empty">AI 연결 후 사용할 수 있습니다. 외부 API로 자동 전환하지 않습니다.</p> : interviewPrep.isError ? <p className="interview-prep-error">{interviewPrep.error instanceof Error ? interviewPrep.error.message : "면접 준비 팩을 만들지 못했습니다."}</p> : !interviewPrep.data ? <p className="interview-prep-empty">필요할 때만 생성하며, 같은 공고·프로필·모델 결과는 로컬 DB 캐시를 재사용합니다.</p> : <>
          <article className="opening-pitch"><span>60초 자기소개 초안</span><p>{interviewPrep.data.opening_pitch}</p></article>
          <div className="interview-question-list">{interviewPrep.data.questions.map((item, index) => <article className="interview-question" key={`${item.category}-${item.question}`}>
            <div><span>{INTERVIEW_CATEGORY_LABELS[item.category]}</span><b>Q{index + 1}</b></div>
            <h4>{item.question}</h4>
            <p className="question-intent">왜 묻나 · {item.why_asked}</p>
            <div className="question-columns"><div><strong>답변 골격</strong><ol>{item.answer_outline.map((line) => <li key={line}>{line}</li>)}</ol></div><div><strong>쓸 수 있는 내 근거</strong>{item.resume_evidence.length ? <ul>{item.resume_evidence.map((line) => <li key={line}>{line}</li>)}</ul> : <p>직접 연결할 이력서 근거가 부족합니다.</p>}</div></div>
            {item.follow_ups.length > 0 && <div className="follow-up-list"><strong>예상 꼬리질문</strong>{item.follow_ups.map((line) => <span key={line}>{line}</span>)}</div>}
            {item.caution && <p className="question-caution">주의 · {item.caution}</p>}
          </article>)}</div>
          <div className="interview-action-grid"><article><h4>면접 전 복습</h4><ul>{interviewPrep.data.study_topics.map((item) => <li key={item}>{item}</li>)}</ul></article><article><h4>회사에 되물을 질문</h4><ul>{interviewPrep.data.questions_to_ask.map((item) => <li key={item}>{item}</li>)}</ul></article></div>
          <small className="local-ai-privacy">{interviewPrep.data.cached ? "입력이 같아 저장된 분석을 재사용했습니다." : "새 분석을 생성해 로컬 DB에 캐시했습니다."} · {interviewPrep.data.model}</small>
        </>}
      </section>
      <section className="breakdown-section"><div className="evidence-section-title"><h3>점수 산정 기준</h3><span>{job.scoring_version}</span></div>
        <div className="breakdown-grid">{job.score_breakdown.map((item) => <div className={item.weight < 0 ? "breakdown-item penalty" : "breakdown-item"} key={item.label}><div><span>{item.label}</span><b>{item.weight < 0 ? `−${formatScore(item.score)}점` : `${item.weight}%`}</b></div><i><em style={{ width: `${Math.min(100, item.score)}%` }} /></i><small>{item.weight < 0 ? item.reason : `${formatScore(item.score)} / 100 · ${item.reason ?? ""}`}</small><EvidenceLines label="내 이력서" lines={item.profile_evidence} /><EvidenceLines label="공고 근거" lines={item.job_evidence} /></div>)}</div>
      </section>
      <div className="evidence-columns">
        <section><div className="evidence-section-title"><h3>강점 매칭</h3><span>{job.matching_reasons.length}개</span></div>
          <div className="evidence-list">{job.matching_reasons.length ? job.matching_reasons.map((reason) => <article className="match-card" key={reason.skill}><div><strong>{reason.skill}</strong><span className={reason.strength === "partial" ? "partial-chip" : "strong-chip"}>{reason.strength === "partial" ? "부분 경험" : "강점"}</span></div><EvidenceLines label="내 이력서" lines={reason.profile_evidence} /><EvidenceLines label="공고 근거" lines={reason.job_evidence} /></article>) : <p className="evidence-empty">직접 일치하는 기술이 없습니다.</p>}</div>
        </section>
        <section><div className="evidence-section-title"><h3>약점·보완점</h3><span>{job.missing_skills.length}개</span></div>
          <div className="evidence-list">{job.missing_skills.length ? job.missing_skills.map((gap) => <article className={`gap-card ${gap.severity}`} key={`${gap.skill}-${gap.profile_note}`}><div><strong>{gap.skill}</strong><span>{gap.severity === "high" ? "큰 격차" : gap.severity === "medium" ? "보완 필요" : "확인 필요"}</span></div><p>{gap.profile_note}</p><EvidenceLines label="공고 근거" lines={gap.job_evidence} /></article>) : <p className="evidence-empty">뚜렷한 기술 격차가 없습니다.</p>}</div>
        </section>
      </div>
      {job.risk_notes.length > 0 && <section className="risk-section"><h3>지원 리스크</h3>{job.risk_notes.map((risk) => <p key={risk}>⚠ {risk}</p>)}</section>}
      <div className="evidence-foot"><span>추천 이력서: {job.resume_recommendation?.recommended_label ?? job.recommended_resume_version ?? "분석 전"}</span><a href={job.url} target="_blank" rel="noreferrer">원문 공고 확인 ↗</a></div>
    </>}
  </aside>;
}

function ResumeRecommendationSection({ recommendation }: { recommendation: ResumeRecommendation }) {
  const confidenceLabel = recommendation.confidence === "high" ? "높은 확신" : recommendation.confidence === "medium" ? "보통 확신" : "비슷한 후보 있음";
  return <section className="resume-recommendation-section">
    <div className="resume-recommendation-head">
      <div><p>RESUME MATCH</p><h3>이 공고에는 어떤 이력서를 낼까요?</h3><span>{recommendation.criteria}</span></div>
      <div className="resume-decision"><b>{recommendation.decision.label}</b><span>{confidenceLabel}</span></div>
    </div>
    <p className="resume-decision-reason">{recommendation.decision.reason}</p>
    <div className="resume-option-grid">
      {recommendation.resumes.map((resume) => <article className={resume.is_recommended ? "resume-option recommended" : "resume-option"} key={resume.id}>
        <div className="resume-option-title"><div><span>{resume.is_recommended ? "1순위" : `${resume.rank}순위`}</span><h4>{resume.short_label}</h4></div><strong>{formatScore(resume.score)}</strong></div>
        <p>{resume.summary}</p>
        <div className="resume-score-bars">{resume.breakdown.map((item) => <div key={item.label}><span>{item.label}</span><i><em style={{ width: `${item.score / item.max_score * 100}%` }} /></i><b>{item.score}/{item.max_score}</b></div>)}</div>
        <div className="resume-copy-block"><h5>추천 근거</h5><ul>{resume.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>
        {resume.is_recommended && <>
          <div className="resume-copy-block"><h5>살릴 성과</h5>{resume.matched_evidence.length ? <ul>{resume.matched_evidence.map((item) => <li key={item}>{item}</li>)}</ul> : <p>프로필에 연결할 성과 근거를 추가해 주세요.</p>}</div>
          <div className="resume-copy-block edits"><h5>지원 전에 손볼 부분</h5><ol>{resume.suggested_edits.map((item) => <li key={item}>{item}</li>)}</ol></div>
        </>}
        {resume.file_url ? <a className="resume-open-button" href={`${API_URL}${resume.file_url}`} target="_blank" rel="noreferrer">이 이력서 열기 ↗</a> : <span className="resume-file-missing">로컬 PDF를 찾지 못했습니다</span>}
      </article>)}
    </div>
  </section>;
}

function RecommendationPanel({ aiStatus, aiModel, onClose, onEvidence }: { aiStatus?: AIStatus; aiModel: string; onClose: () => void; onEvidence: (jobId: number) => void }) {
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<{ question: string; response: RecommendationResponse }[]>([]);
  const recommendation = useMutation({
    mutationFn: async (question: string) => {
      const response = await fetch(`${API_URL}/api/recommendations/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, limit: 8, ai_model: aiModel }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "추천을 만들지 못했습니다.");
      return body as RecommendationResponse;
    },
    onSuccess: (response, question) => {
      setHistory((current) => [...current, { question, response }]);
      setMessage("");
    },
  });
  const submit = () => {
    const question = message.trim();
    if (question && !recommendation.isPending) recommendation.mutate(question);
  };
  return <aside className="advisor-panel" aria-label="DB 채용 공고 추천 채팅">
    <div className="advisor-head"><div><p>JOB ADVISOR</p><h2>어떤 공고를 찾고 있나요?</h2><span>Codex GPT가 질문을 해석하고 DB의 활성 공고와 이력서 점수를 비교합니다.</span><small className={aiStatus?.available ? "advisor-ai-state connected" : "advisor-ai-state offline"}>{aiStatus?.available ? `● ${aiStatus.provider === "codex" ? "CODEX GPT" : aiStatus.local_only ? "로컬 AI" : "외부 허용 AI"} · ${aiStatus.active_model}` : `○ GPT 미연결 · 규칙 엔진 사용 중 · ${aiStatus?.message ?? "상태 확인 중"}`}</small></div><button aria-label="추천 채팅 닫기" onClick={onClose}>×</button></div>
    <div className="advisor-chat">
      <div className="chat-bubble assistant"><p>예: “Python·Django 백엔드 중 5년 이상이고 AI 제품 경험을 살릴 수 있는 공고 추천해줘” 또는 “Java는 빼고 리모트 공고 찾아줘”</p></div>
      {history.map((turn, turnIndex) => <div className="chat-turn" key={`${turn.question}-${turnIndex}`}>
        <div className="chat-bubble user"><p>{turn.question}</p></div>
        <div className="chat-bubble assistant"><p>{turn.response.answer}</p></div>
        <small className={turn.response.ai_used ? "ai-turn-note used" : "ai-turn-note fallback"}>{turn.response.ai_used ? `${turn.response.ai_provider === "codex" ? "Codex GPT 추천" : "AI 근거 요약"} · ${turn.response.ai_model}` : `규칙 엔진 응답 · GPT 미연결 · ${turn.response.ai_notice}`}</small>
        <div className="advisor-results">{turn.response.items.map((job) => <article key={job.id}><div><span className={`source-pill ${job.source}`}>{sourceLabels[job.source]}</span><b>추천 {formatScore(job.recommendation_score)}</b></div><h3>{job.title}</h3><p>{job.company} · {job.experience_text || "경력 미기재"}</p><div className="recommend-scores"><span>적합도 <b>{formatScore(job.total_fit_score)}</b></span><span>지원가치 <b>{formatScore(job.application_value_score)}</b></span></div><ul>{job.why.map((reason) => <li key={reason}>{reason}</li>)}</ul><div><button onClick={() => onEvidence(job.id)}>상세 근거</button><a href={job.url} target="_blank" rel="noreferrer">원문 ↗</a></div></article>)}</div>
      </div>)}
      {recommendation.isPending && <div className="chat-bubble assistant loading"><p>{aiStatus?.provider === "codex" && aiStatus.available ? "Codex GPT가 질문을 해석하고 DB 공고를 비교하고 있어요…" : "규칙 엔진으로 DB 공고와 이력서 근거를 비교하고 있어요…"}</p></div>}
      {recommendation.isError && <div className="chat-error">{recommendation.error instanceof Error ? recommendation.error.message : "추천 실패"}</div>}
    </div>
    <div className="advisor-input"><textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} placeholder="이런 공고를 추천해줘…" rows={3} /><button disabled={!message.trim() || recommendation.isPending} onClick={submit}>추천 찾기 ↗</button></div>
  </aside>;
}

function EvidenceLines({ label, lines = [] }: { label: string; lines?: string[] }) {
  return <div className="evidence-lines"><span>{label}</span>{lines.map((line, index) => <p key={`${line}-${index}`}>{line}</p>)}</div>;
}

function CompanyFactsSection({ company, profile }: { company: string; profile: CompanyProfile }) {
  const investmentLabel = profile.recent_investment_amount != null
    ? `${formatKrw(profile.recent_investment_amount)}${profile.disclosed_investment_count < profile.recent_investment_count ? " 이상" : ""}`
    : profile.recent_investment_count > 0 ? "금액 비공개" : "공개 내역 없음";
  return <section className="company-facts-section">
    <div className="evidence-section-title"><h3>{company} 회사 현황</h3><span>공개자료 기준 · 최근 3년</span></div>
    <div className="company-fact-grid">
      <article><span>인원 규모</span><strong>{profile.employee_count != null ? `${profile.employee_count.toLocaleString("ko-KR")}명` : "비공개"}</strong><small>{profile.developer_count != null ? `개발 ${profile.developer_count.toLocaleString("ko-KR")}명` : profile.employee_count_source ?? "공개자료 없음"}</small></article>
      <article><span>최근 매출</span><strong>{formatKrw(profile.latest_revenue)}</strong><small>{profile.latest_revenue_year ? `${profile.latest_revenue_year}년 공시` : "매출 비공개·미공시"}</small></article>
      <article className={profile.profitability_status}><span>영업손익</span><strong>{profitabilityLabel(profile.profitability_status)}</strong><small>{profile.latest_revenue_year ? `${profile.latest_revenue_year}년 기준` : "공개자료 없음"}</small></article>
      <article><span>최근 3년 투자</span><strong>{investmentLabel}</strong><small>{profile.recent_investment_count ? `${profile.recent_investment_count}건${profile.investment_stage ? ` · ${profile.investment_stage}` : ""}` : profile.investment_stage ?? "공개자료 없음"}</small></article>
    </div>
    <div className="company-history-grid">
      <div><h4>최근 재무</h4>{profile.financial_history.length ? <div className="company-history-list">{profile.financial_history.map((item) => <div key={`${item.year}-${item.source}`}><b>{item.year}</b><span>매출 {formatKrw(item.revenue)}</span><span className={(item.operating_profit ?? 0) > 0 ? "profit" : (item.operating_profit ?? 0) < 0 ? "loss" : ""}>영업 {formatKrw(item.operating_profit)}</span><small>{item.basis ?? ""} · {item.source}</small></div>)}</div> : <p>최근 3개년 재무정보가 공개되지 않았거나 회사명이 공시 법인과 일치하지 않습니다.</p>}</div>
      <div><h4>최근 투자</h4>{profile.funding_history.length ? <div className="company-history-list funding">{profile.funding_history.map((item, index) => <div key={`${item.date}-${item.round}-${index}`}><b>{item.date?.slice(0, 7) ?? "일자 미공개"}</b><span>{item.round}</span><span>{formatKrw(item.amount)}</span><small>{item.source}</small></div>)}</div> : <p>최근 3년 내 공개된 투자 내역이 없습니다. 투자하지 않았다는 뜻은 아닙니다.</p>}</div>
    </div>
    <div className="company-facts-foot"><span>비공개 값은 추정하지 않습니다. 공시 시점과 현재 상태가 다를 수 있습니다.</span>{profile.source_urls.length > 0 && <div>{profile.source_urls.map((url, index) => <a href={url} target="_blank" rel="noreferrer" key={url}>출처 {index + 1} ↗</a>)}</div>}</div>
  </section>;
}

function CompareCard({ job, onClose }: { job: JobDetail; onClose: () => void }) {
  return <article className="compare-card">
    <button className="compare-close" onClick={onClose}>×</button>
    <span className={`source-pill ${job.source}`}>{sourceLabels[job.source]}</span>
    <h3>{job.title}</h3><p className="compare-company">{job.company}</p>
    <div className="compare-score"><span>적합도</span><strong>{formatScore(job.total_fit_score)}</strong></div>
    <CompareSection title="기술 스택"><div className="tech-list">{job.tech_stack.map((item) => <span key={item}>{item}</span>)}</div></CompareSection>
    <CompareSection title="경력·위치"><p>{job.experience_text || "미상"}</p><p>{job.location || "미상"}</p></CompareSection>
    <CompareSection title="채용 절차"><p>{hiringProcessSummary(job)}</p><BulletList items={job.hiring_process} /></CompareSection>
    <CompareSection title="주요 업무"><BulletList items={job.main_tasks} /></CompareSection>
    <CompareSection title="자격 요건"><BulletList items={job.requirements} /></CompareSection>
    <a className="detail-button" href={job.url} target="_blank" rel="noreferrer">원문 공고 열기 ↗</a>
  </article>;
}

function hiringProcessSummary(job: Job): string {
  const labels: string[] = [];
  if (job.has_coding_test === true) labels.push("코테 있음");
  if (job.has_coding_test === false) labels.push("코테 없음 · 명시");
  if (job.interview_count === 0) labels.push("면접 없음 · 명시");
  if (job.interview_count != null && job.interview_count > 0) labels.push(`면접 ${job.interview_count}회`);
  return labels.length ? labels.join(" · ") : "전형 미확인";
}

function CompareSection({ title, children }: { title: string; children: React.ReactNode }) { return <section className="compare-section"><h4>{title}</h4>{children}</section>; }
function BulletList({ items }: { items: string[] }) { return items.length ? <ul>{items.slice(0, 5).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : <p className="muted">정보 없음</p>; }
function Empty({ title, body }: { title: string; body: string }) { return <div className="empty"><span>◎</span><h3>{title}</h3><p>{body}</p></div>; }
function LoadingRows() { return <div className="loading-rows">{Array.from({ length: 5 }, (_, index) => <i key={index} />)}</div>; }

createRoot(document.getElementById("root")!).render(<StrictMode><QueryClientProvider client={queryClient}><App /></QueryClientProvider></StrictMode>);
