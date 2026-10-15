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
  request_id: string;
  text: string;
  route: string;
  intents: IntentCandidate[];
  slots: SlotValue[];
  risk: RiskInfo | null;
  need_clarification: boolean;
  clarification: string | null;
}

export interface IntentAnalyzeInput {
  text: string;
  model_uid?: string;
  context?: Record<string, unknown>;
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
  const response = await fetch("/api/v1/intent/analyze", {
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
