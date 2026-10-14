import { loadConnection } from "./client-settings";
import type {
  PlanResponse,
  PresetInfo,
  SettingsResponse,
  Target,
  TestConfig,
  TestListResponse,
  TestReport,
  TestRunDetail,
  UserSettings,
  ValidateTargetResponse,
  ValidationIssue,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }

  get issues(): ValidationIssue[] {
    return Array.isArray(this.details) ? (this.details as ValidationIssue[]) : [];
  }
}

export function apiBase(): string {
  return loadConnection().apiUrl.replace(/\/+$/, "");
}

export function authHeaders(): Record<string, string> {
  const { token } = loadConnection();
  // The custom header forces a CORS preflight, which the backend uses as CSRF protection.
  const h: Record<string, string> = { "X-LoadLab-Client": "1" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

const FRIENDLY: Record<number, string> = {
  0: "Cannot reach the LoadLab API. Is the backend running? Check the API URL in Settings.",
  401: "Authentication failed. Set a valid API token in Settings.",
  429: "Too many requests to the LoadLab API. Wait a moment and try again.",
};

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders(), ...(init.headers as Record<string, string>) };
  if (init.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(apiBase() + path, { ...init, headers });
  } catch {
    throw new ApiError(0, "network_error", FRIENDLY[0]);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: unknown = undefined;
  try {
    body = text ? JSON.parse(text) : undefined;
  } catch {
    body = undefined;
  }
  if (!res.ok) {
    const err = (body as { error?: { code?: string; message?: string; details?: unknown } } | undefined)?.error;
    throw new ApiError(
      res.status,
      err?.code ?? "http_error",
      err?.message ?? FRIENDLY[res.status] ?? `Request failed (${res.status}).`,
      err?.details,
    );
  }
  return body as T;
}

const json = (data: unknown): RequestInit => ({ body: JSON.stringify(data) });

export const api = {
  settings: () => request<SettingsResponse>("/api/settings"),
  updateSettings: (s: UserSettings) => request<UserSettings>("/api/settings", { method: "PUT", ...json(s) }),
  presets: () => request<PresetInfo[]>("/api/presets"),
  health: () => request<{ status: string; active_tests: number }>("/api/health"),

  targets: () => request<Target[]>("/api/targets"),
  createTarget: (t: { name: string; base_url: string; notes: string; authorized: boolean }) =>
    request<Target>("/api/targets", { method: "POST", ...json(t) }),
  deleteTarget: (id: string) => request<void>(`/api/targets/${id}`, { method: "DELETE" }),
  validateTarget: (base_url: string, path: string) =>
    request<ValidateTargetResponse>("/api/targets/validate", { method: "POST", ...json({ base_url, path }) }),

  plan: (config: TestConfig) => request<PlanResponse>("/api/tests/plan", { method: "POST", ...json(config) }),
  start: (config: TestConfig, clientRequestId: string) =>
    request<TestRunDetail>("/api/tests", {
      method: "POST",
      ...json({ config, confirm: true, client_request_id: clientRequestId }),
    }),
  list: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
    return request<TestListResponse>(`/api/tests?${qs}`);
  },
  get: (id: string) => request<TestRunDetail>(`/api/tests/${id}`),
  results: (id: string) => request<TestReport>(`/api/tests/${id}/results`),
  compare: (a: string, b: string) => request<{ a: TestReport; b: TestReport }>(`/api/tests/compare?a=${a}&b=${b}`),
  stop: (id: string) => request<{ status: string }>(`/api/tests/${id}/stop`, { method: "POST" }),
  pause: (id: string) => request<{ status: string }>(`/api/tests/${id}/pause`, { method: "POST" }),
  resume: (id: string) => request<{ status: string }>(`/api/tests/${id}/resume`, { method: "POST" }),
  remove: (id: string) => request<void>(`/api/tests/${id}`, { method: "DELETE" }),
  removeAll: () => request<{ deleted: number }>("/api/tests?confirm=true", { method: "DELETE" }),
};

/** Download an export through fetch so the auth header is sent, then save it as a file. */
export async function downloadExport(path: string, fallbackName: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(apiBase() + path, { headers: authHeaders() });
  } catch {
    throw new ApiError(0, "network_error", FRIENDLY[0]);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => undefined);
    throw new ApiError(res.status, body?.error?.code ?? "http_error", body?.error?.message ?? "Export failed.");
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
