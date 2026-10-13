export interface FieldIssue {
  field: string;
  message: string;
}
export class ConfigApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public issues: FieldIssue[] = [],
  ) {
    super(message);
  }
}
export interface Route {
  name: string;
  zh: string;
  description: string;
  enabled: boolean;
}
export interface DraftJson {
  schema_version: number;
  routes: Route[];
  intents: unknown[];
  slots: unknown[];
  enums: Record<string, unknown>;
  examples: unknown[];
  prompt_template: Record<string, unknown>;
}
export interface Draft {
  draft_json: DraftJson | null;
  draft_hash: string | null;
  updated_at: string | null;
}
export interface ModelInput {
  name: string;
  version: string;
  provider: string;
  model: string;
  base_url: string;
  params_json: Record<string, unknown>;
  timeout_seconds: number;
  max_retries: number;
  max_concurrency: number;
  structured_output_mode: string;
  credential_ref: string;
}
export interface ModelConfig extends ModelInput {
  id: number;
  enabled: boolean;
  model_config_hash: string;
}
export interface Release {
  id: number;
  version: string;
  note: string;
  default_model_config_id: number;
  config_snapshot_hash: string;
  model_config_hash: string;
  release_fingerprint: string;
  created_at: string;
  snapshot_json?: DraftJson;
}
export interface PublishSummary {
  draft_hash: string;
  config_snapshot_hash: string;
  active_release_id: number | null;
  default_model_config_id: number;
  model_config_hash: string;
  release_fingerprint: string;
  model_changed: boolean;
  changes: { section: string; before: unknown; after: unknown }[];
}
export async function request<T>(
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
  if (!response.ok)
    throw new ConfigApiError(
      data.error_code ?? "HTTP_ERROR",
      data.message ?? `HTTP ${response.status}`,
      data.issues,
    );
  return data as T;
}
export const configApi = {
  draft: () => request<Draft>("/config/draft"),
  save: (draft_json: DraftJson, expected_draft_hash: string | null) =>
    request<Draft>("/config/draft", "PUT", { draft_json, expected_draft_hash }),
  bootstrap: (draft_json: DraftJson) =>
    request<Draft>("/config/bootstrap", "POST", { draft_json }),
  validate: () =>
    request<{ valid: boolean; config_snapshot_hash: string }>(
      "/config/validate",
      "POST",
    ),
  preview: (text: string) =>
    request<{ final_prompt: string; prompt_hash: string }>(
      "/config/prompt-preview",
      "POST",
      { text },
    ),
  models: (offset = 0) =>
    request<ModelConfig[]>(`/model-configs?limit=200&offset=${offset}`),
  createModel: (body: ModelInput) =>
    request<ModelConfig>("/model-configs", "POST", body),
  disableModel: (id: number) =>
    request<ModelConfig>(`/model-configs/${id}/disable`, "POST"),
  releases: (offset = 0) =>
    request<{ items: Release[]; active_release_id: number | null }>(
      `/releases?limit=20&offset=${offset}`,
    ),
  release: (id: number) => request<Release>(`/releases/${id}`),
  summary: (id: number) =>
    request<PublishSummary>(
      `/config/publish-summary?default_model_config_id=${id}`,
    ),
  publish: (summary: PublishSummary, note: string) =>
    request<Release>("/releases", "POST", {
      default_model_config_id: summary.default_model_config_id,
      note,
      expected_draft_hash: summary.draft_hash,
      expected_active_release_id: summary.active_release_id,
    }),
  restore: (id: number, expected_draft_hash: string | null) =>
    request<Draft>(`/releases/${id}/create-draft`, "POST", {
      expected_draft_hash,
    }),
};
