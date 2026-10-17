import { request } from "./configApi";
import type { IntentResult } from "./intentApi";

export interface ExpectedSlot {
  name: string;
  value: string;
}
export interface ExpectedAction {
  route: string;
  intent?: string | null;
  slots?: ExpectedSlot[] | null;
  depends_on?: number[] | null;
}
export interface ExpectedAnswer {
  actions?: ExpectedAction[] | null;
  composition?: "single" | "parallel" | "sequential" | "alternative" | null;
  risk?: { type: string; level: "low" | "medium" | "high" } | null;
  need_clarification?: boolean | null;
}
export interface EvaluationCase {
  case_id: string;
  question: string;
  standard_answer: string;
  tags: string[];
  critical: boolean;
  context?: Record<string, unknown>;
  expected?: ExpectedAnswer | null;
}
export interface Dataset {
  id: number;
  name: string;
  version: string;
  hash: string;
  case_count: number;
  source_filename: string;
  created_at: string;
}
export interface Run {
  id: number;
  name: string;
  dataset_id: number;
  dataset_hash: string;
  release_id: number;
  model_uid: string;
  model_label: string;
  judge_model_uid: string | null;
  judge_label: string;
  repeat_count: number;
  worker_concurrency: number;
  pass_threshold: number;
  status: "queued" | "running" | "completed" | "cancelled" | "failed";
  case_count: number;
  execution_count: number;
  progress: { completed: number };
  parent_run_id: number | null;
  cancel_requested: boolean;
  error: string | null;
  heartbeat_at: string | null;
  created_at: string;
  finished_at: string | null;
  summary?: RunSummary;
}
export interface RunSummary {
  judging: number;
  recorded_tokens: number;
  quality: {
    labelled_cases: number;
    macro_f1: number | null;
    per_route: {
      route: string;
      support: number;
      predicted: number;
      precision: number | null;
      recall: number | null;
      f1: number | null;
    }[];
    confusion: { expected: string; actual: string; count: number }[];
    dimensions: Record<string, { checked: number; passed: number }>;
  };
  total: number;
  passed: number;
  failed: number;
  errors: number;
  review: number;
  not_run: number;
  pass_rate: number;
  final: boolean;
  pending_executions: number;
  completed_executions: number;
  total_executions: number;
  critical_failures: number;
  acceptance: "passed" | "failed" | "incomplete";
  average_latency_ms: number | null;
  p95_latency_ms: number | null;
  stable_cases: number | null;
  stability_rate: number | null;
  by_tag: Record<string, { total: number; passed: number }>;
  issue_counts: Record<string, number>;
}
export type VerdictStatus =
  "pass" | "fail" | "review" | "error" | "not_run" | "cancelled" | "judging";
export interface EvaluationResult extends EvaluationCase {
  id: number | null;
  repeat_index: number;
  status: VerdictStatus;
  auto_status: VerdictStatus;
  actual: IntentResult | null;
  issue_tags: string[];
  reason: string;
  request_id: string | null;
  trace_id: string | null;
  trace_state: "available" | "expired" | "unavailable";
  latency_ms: number | null;
  review_revision: number;
  reviews: {
    decision: string;
    reason: string;
    reviewer: string;
    created_at: string;
  }[];
  verdict: {
    rules?: {
      checked: string[];
      issues: {
        field: string;
        message: string;
        expected?: unknown;
        actual?: unknown;
      }[];
    };
    judge?: { verdict: string; reason: string; tags: string[] };
    judge_error?: string;
    reason?: string;
  };
  repeat_passed?: number;
  repeat_count?: number;
}
export interface RunInput {
  name: string;
  dataset_id: number;
  release_id?: number | null;
  model_uid: string;
  judge_model_uid?: string | null;
  repeat_count: number;
  worker_concurrency: number;
  pass_threshold: number;
  parent_run_id?: number;
  case_ids?: string[];
}
export interface Filters {
  status: string;
  tag: string;
  issue: string;
  keyword: string;
  bad_only: boolean;
  primary_only: boolean;
}
export interface ResultsPage {
  items: EvaluationResult[];
  total: number;
  case_ids: string[];
  tags: string[];
  issue_tags: string[];
}
export interface Comparison {
  left: Run & { summary: RunSummary };
  right: Run & { summary: RunSummary };
  changes: {
    case_id: string;
    question: string;
    before: string;
    after: string;
    change: string;
    left_reason: string;
    right_reason: string;
  }[];
  warning: string | null;
}
export function filterQuery(filters: Filters) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== "") query.set(key, String(value));
  }
  return query;
}
export async function downloadEvaluation(path: string, filename: string) {
  const response = await fetch(`/api/admin/evaluation${path}`);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.message ?? "文件下载失败");
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const evaluationApi = {
  datasets: (offset = 0) =>
    request<{ items: Dataset[]; total: number }>(
      `/evaluation/datasets?offset=${offset}`,
    ),
  dataset: (id: number) =>
    request<Dataset & { cases: EvaluationCase[] }>(
      `/evaluation/datasets/${id}`,
    ),
  createDataset: (name: string, cases: EvaluationCase[]) =>
    request<Dataset>("/evaluation/datasets", "POST", { name, cases }),
  importDataset: async (name: string, file: File) => {
    const query = new URLSearchParams({ name, filename: file.name });
    const response = await fetch(
      `/api/admin/evaluation/datasets/import?${query}`,
      {
        method: "POST",
        headers: {
          "Content-Type":
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
        body: file,
      },
    );
    const data = await response.json();
    if (!response.ok) {
      const details = (data.issues ?? [])
        .map(
          (issue: { field: string; message: string }) =>
            `${issue.field}：${issue.message}`,
        )
        .join("\n");
      throw new Error(
        `${data.message ?? "导入失败"}${details ? `\n${details}` : ""}`,
      );
    }
    return data as Dataset;
  },
  runs: (offset = 0) =>
    request<{ items: Run[]; total: number }>(
      `/evaluation/runs?offset=${offset}`,
    ),
  createRun: (body: RunInput) => request<Run>("/evaluation/runs", "POST", body),
  run: (id: number) =>
    request<Run & { summary: RunSummary }>(`/evaluation/runs/${id}`),
  cancel: (id: number) => request<Run>(`/evaluation/runs/${id}/cancel`, "POST"),
  results: (id: number, filters: Filters, offset = 0) =>
    request<ResultsPage>(
      `/evaluation/runs/${id}/results?${filterQuery(filters)}&offset=${offset}&limit=50`,
    ),
  review: (
    runId: number,
    result: EvaluationResult,
    decision: "pass" | "fail",
    reason: string,
    reviewer: string,
  ) =>
    request(`/evaluation/runs/${runId}/results/${result.id}/review`, "POST", {
      decision,
      reason,
      reviewer,
      expected_revision: result.review_revision,
    }),
  compare: (left: number, right: number) =>
    request<Comparison>(`/evaluation/compare?left=${left}&right=${right}`),
};
