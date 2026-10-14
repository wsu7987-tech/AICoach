export class ModelApiError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export interface ManagedModel {
  id: number;
  model_uid: string;
  display_name: string;
  model_name: string;
  base_url: string;
  temperature: number | null;
  top_p: number | null;
  timeout_seconds: number;
  max_retries: number;
  max_concurrency: number;
  enabled: boolean;
  credential_configured: boolean;
  credential_hint: string | null;
  last_verified_at: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface ModelList {
  default_model_uid: string | null;
  items: ManagedModel[];
}

export interface ModelCreateInput {
  display_name: string;
  base_url: string;
  api_key: string;
  model_name: string;
  temperature: number;
  top_p: number;
  timeout_seconds: number;
  max_retries: number;
  max_concurrency: number;
}

export interface ModelUpdateInput {
  display_name?: string;
  api_key?: string;
  temperature?: number;
  top_p?: number;
  timeout_seconds?: number;
  max_retries?: number;
  max_concurrency?: number;
}

export interface VerifyResult {
  connected: true;
  model_discovery_supported: boolean;
  models: string[];
  message: string;
}

async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api/admin${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new ModelApiError(
      data.error_code ?? "HTTP_ERROR",
      data.message ?? `请求失败（HTTP ${response.status}）`,
    );
  }
  return data as T;
}

export const modelApi = {
  list: () => request<ModelList>("/models"),
  create: (body: ModelCreateInput) =>
    request<ManagedModel>("/models", "POST", body),
  update: (modelUid: string, body: ModelUpdateInput) =>
    request<ManagedModel>(`/models/${modelUid}`, "PATCH", body),
  verifyNew: (baseUrl: string, apiKey: string, timeoutSeconds: number) =>
    request<VerifyResult>("/models/verify", "POST", {
      base_url: baseUrl,
      api_key: apiKey,
      timeout_seconds: Math.min(timeoutSeconds, 60),
    }),
  verifyExisting: (modelUid: string, apiKey?: string) =>
    request<VerifyResult>(`/models/${modelUid}/verify`, "POST", {
      ...(apiKey ? { api_key: apiKey } : {}),
    }),
  setDefault: (modelUid: string) =>
    request<ManagedModel>(`/models/${modelUid}/default`, "POST"),
  enable: (modelUid: string) =>
    request<ManagedModel>(`/models/${modelUid}/enable`, "POST"),
  disable: (modelUid: string) =>
    request<ManagedModel>(`/models/${modelUid}/disable`, "POST"),
};
