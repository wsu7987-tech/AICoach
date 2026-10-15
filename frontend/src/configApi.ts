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
export interface Intent {
  name: string;
  zh: string;
  route: string;
  description: string;
  enabled: boolean;
  aliases: string[];
  mapping_note?: string | null;
}
export interface Example {
  text: string;
  route: string;
  intent?: string | null;
  enabled?: boolean;
}
export interface PromptTemplate {
  system: string;
  rules: string[];
  include_examples: boolean;
}
export interface SlotDefinition {
  name: string;
  zh: string;
  description: string;
  value_type: "string" | "enum";
  enabled: boolean;
  enum_group?: string | null;
}
export interface EnumValueDefinition {
  canonical: string;
  display: string;
  aliases: string[];
  enabled?: boolean;
}
export interface DraftJson {
  schema_version: number;
  routes: Route[];
  intents: Intent[];
  slots: SlotDefinition[];
  enums: Record<string, EnumValueDefinition[]>;
  examples: Example[];
  prompt_template: PromptTemplate;
}
export interface Draft {
  draft_json: DraftJson | null;
  draft_hash: string | null;
  updated_at: string | null;
}
export interface Release {
  id: number;
  version: string;
  note: string;
  created_by: string;
  created_at: string;
  snapshot_json?: DraftJson;
}
export interface PublishSummary {
  draft_hash: string;
  active_release_id: number | null;
  changes: { section: string; before: unknown; after: unknown }[];
}
export type PromptModule =
  | "routes"
  | "intents"
  | "intent"
  | "slots"
  | "slot"
  | "enum";
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
  previewModule: (
    module: PromptModule,
    targetName?: string,
  ) =>
    request<{ module: PromptModule; content: string }>(
      "/config/prompt-preview/module",
      "POST",
      {
        module,
        ...(module === "intent" ? { intent_name: targetName } : {}),
        ...(module === "slot" ? { slot_name: targetName } : {}),
        ...(module === "enum" ? { enum_group: targetName } : {}),
      },
    ),
  releases: (offset = 0) =>
    request<{ items: Release[]; active_release_id: number | null }>(
      `/releases?limit=20&offset=${offset}`,
    ),
  release: (id: number) => request<Release>(`/releases/${id}`),
  summary: () => request<PublishSummary>("/config/publish-summary"),
  publish: (summary: PublishSummary, note: string) =>
    request<Release>("/releases", "POST", {
      note,
      expected_draft_hash: summary.draft_hash,
      expected_active_release_id: summary.active_release_id,
    }),
  restore: (id: number, expected_draft_hash: string | null) =>
    request<Draft>(`/releases/${id}/create-draft`, "POST", {
      expected_draft_hash,
    }),
};
