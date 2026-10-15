export interface IntentCandidate {
  name: string;
  zh: string;
  confidence: number;
}

export interface SlotValue {
  name: string;
  zh: string;
  value: string;
  start: number;
  end: number;
  confidence: number;
}

export interface RiskInfo {
  type: string;
  zh: string;
  level: "low" | "medium" | "high";
}

export interface IntentResult {
  schema_version: 2;
  request_id: string;
  text: string;
  is_compound: boolean;
  composition: "single" | "parallel" | "sequential" | "alternative";
  actions: IntentAction[];
  risk: RiskInfo | null;
  need_clarification: boolean;
  clarification: string | null;
}

export interface IntentAction {
  action_id: string;
  route: string;
  intent: IntentCandidate | null;
  slots: SlotValue[];
  order: number;
  depends_on: string[];
}

export interface IntentAnalyzeInput {
  text: string;
  model_uid?: string;
  context?: Record<string, unknown>;
}

export interface IntentLatencyAnalysis {
  request_id: string;
  trace_id: string;
  model_uid: string;
  current: {
    provider_latency_ms: number | null;
    attempt_count: number;
    retry_count: number;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
  };
  baseline: {
    sample_size: number;
    average_ms: number | null;
    p50_ms: number | null;
    p95_ms: number | null;
    min_ms: number | null;
    max_ms: number | null;
  };
}

export class IntentApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function analyzeIntent(
  body: IntentAnalyzeInput,
): Promise<IntentResult> {
  const response = await fetch("/api/v2/intent/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new IntentApiError(
      data?.error_code ?? "HTTP_ERROR",
      data?.message ?? `请求失败（HTTP ${response.status}）`,
      response.status,
    );
  }
  return data as IntentResult;
}

export async function getIntentLatencyAnalysis(
  requestId: string,
  modelUid: string,
): Promise<IntentLatencyAnalysis> {
  const query = new URLSearchParams({
    request_id: requestId,
    model_uid: modelUid,
    sample_size: "20",
  });
  const response = await fetch(`/api/admin/intent/latency-analysis?${query}`);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new IntentApiError(
      data?.error_code ?? "HTTP_ERROR",
      data?.message ?? `耗时分析加载失败（HTTP ${response.status}）`,
      response.status,
    );
  }
  return data as IntentLatencyAnalysis;
}
