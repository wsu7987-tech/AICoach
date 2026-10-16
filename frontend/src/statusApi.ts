import { request } from "./configApi";

export type TrafficSource = "runtime" | "debug" | "replay" | "evaluation";
export type CheckState = "ready" | "not_ready" | "unavailable";
export interface StatusCheck {
  state: CheckState;
  code: string;
  message: string;
}
export interface ServiceStatus {
  checked_at: string;
  window_start: string;
  source: TrafficSource;
  service_ready: boolean | null;
  runtime_config_ready: boolean | null;
  checks: Record<
    "service" | "release" | "model" | "traffic" | "evaluation",
    StatusCheck
  >;
  active_release_id: number | null;
  active_release: { version: string; note: string; created_at: string } | null;
  default_model: {
    model_uid: string;
    display_name: string;
    model_name: string;
    enabled: boolean;
  } | null;
  requests_24h: number | null;
  errors_24h: number | null;
  cancelled_24h: number | null;
  error_rate: number | null;
  latency_samples: number | null;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  evaluation_queued: number | null;
  evaluation_running: number | null;
}

export const trafficSources: { value: TrafficSource; label: string }[] = [
  { value: "runtime", label: "线上请求" },
  { value: "debug", label: "调试请求" },
  { value: "replay", label: "重放请求" },
  { value: "evaluation", label: "评测请求" },
];

export function loadStatus(source: TrafficSource, signal: AbortSignal) {
  return request<ServiceStatus>(
    `/status/summary?source=${source}`,
    "GET",
    undefined,
    signal,
  );
}
