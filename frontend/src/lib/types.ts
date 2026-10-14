// Mirrors backend/app/schemas.py — keep in sync.

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type RateUnit = "rps" | "rpm";
export type PresetName = "custom" | "smoke" | "baseline" | "load" | "spike" | "stress";
export type TestStatus = "pending" | "running" | "paused" | "completed" | "stopped" | "failed";

export interface KeyValue {
  key: string;
  value: string;
}

export interface BodyConfig {
  type: "none" | "json" | "text";
  content: string;
}

export interface AuthConfig {
  type: "none" | "bearer" | "basic";
  token?: string | null;
  username?: string | null;
  password?: string | null;
}

export interface TestConfig {
  name: string;
  base_url: string;
  path: string;
  method: HttpMethod;
  query: KeyValue[];
  headers: KeyValue[];
  body: BodyConfig;
  auth: AuthConfig;
  timeout_s: number;
  duration_s: number;
  rate_unit: RateUnit;
  rate: number;
  max_concurrency: number;
  preset: PresetName;
  follow_redirects: boolean;
  max_redirects: number;
  retries: number;
  verify_tls: boolean;
}

export interface Stage {
  start_s: number;
  end_s: number;
  from_rps: number;
  to_rps: number;
}

export interface PlanLimits {
  max_rps: number;
  max_concurrency: number;
  max_duration_s: number;
  max_timeout_s: number;
  max_request_body_bytes: number;
  response_body_limit_bytes: number;
}

export interface TestPlan {
  preset: PresetName;
  url_preview: string;
  method: HttpMethod;
  target_origin: string;
  peak_rps: number;
  average_rps: number;
  configured_rate: number;
  rate_unit: RateUnit;
  duration_s: number;
  max_concurrency: number;
  timeout_s: number;
  expected_requests: number;
  stages: Stage[];
  limits: PlanLimits;
  warnings: string[];
  requires_confirmation: boolean;
}

export interface ValidationIssue {
  code: string;
  message: string;
  field?: string | null;
}

export interface ValidateTargetResponse {
  ok: boolean;
  normalized_url: string | null;
  origin: string | null;
  approved: boolean;
  target_id: string | null;
  resolved_ips: string[];
  errors: ValidationIssue[];
  warnings: string[];
}

export interface PlanResponse {
  ok: boolean;
  plan: TestPlan | null;
  errors: ValidationIssue[];
}

export interface Target {
  id: string;
  name: string;
  origin: string;
  host: string;
  port: number;
  scheme: string;
  notes: string;
  is_local: boolean;
  created_at: string;
}

export interface LatencyStats {
  avg: number | null;
  min: number | null;
  max: number | null;
  p50: number | null;
  p90: number | null;
  p95: number | null;
  p99: number | null;
}

export interface TimelinePoint {
  t: number;
  target_rps: number;
  sent: number;
  completed: number;
  success: number;
  failure: number;
  avg_ms: number | null;
  p95_ms: number | null;
  in_flight: number;
  dropped: number;
}

export interface GeneratorStats {
  cpu_percent: number;
  rss_mb: number;
  loop_lag_ms: number;
  open_connections_limit: number;
  saturated: boolean;
  reasons: string[];
}

export interface ErrorSample {
  kind: string;
  count: number;
  samples: string[];
}

export interface MetricsSnapshot {
  test_id: string;
  status: TestStatus;
  elapsed_s: number;
  remaining_s: number;
  duration_s: number;
  progress: number;
  target_rps: number;
  configured_peak_rps: number;
  actual_rps: number;
  total: number;
  success: number;
  failure: number;
  cancelled: number;
  in_flight: number;
  dropped: number;
  retries: number;
  error_rate: number;
  bytes_received: number;
  latency: LatencyStats;
  status_codes: Record<string, number>;
  errors: ErrorSample[];
  generator: GeneratorStats | null;
  eta: string;
  point: TimelinePoint | null;
  stop_reason?: string;
  achieved_rps?: number;
  max_in_flight?: number;
}

export interface TestRunSummary {
  id: string;
  name: string;
  status: TestStatus;
  preset: string;
  method: string;
  target_origin: string;
  path: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  configured_rps: number;
  achieved_rps: number | null;
  total: number;
  success: number;
  failure: number;
  error_rate: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
}

export interface TestRunDetail extends TestRunSummary {
  config: TestConfig;
  plan: TestPlan;
  summary: (MetricsSnapshot & { generator_at_end?: GeneratorStats | null }) | null;
  stop_reason: string | null;
}

export interface TestReport extends TestRunDetail {
  timeline: TimelinePoint[];
}

export interface TestListResponse {
  items: TestRunSummary[];
  total: number;
}

export interface UserSettings {
  max_rps: number;
  max_concurrency: number;
  max_duration_s: number;
  confirm_above_rps: number;
}

export interface SettingsResponse {
  user: UserSettings;
  hard_limits: PlanLimits;
  auth_mode: "none" | "token";
  allow_external_targets: boolean;
  local_target_hosts: string[];
  environment: string;
}

export interface PresetInfo {
  name: PresetName;
  label: string;
  description: string;
  max_rps: number | null;
  max_duration_s: number | null;
  max_concurrency: number | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}
