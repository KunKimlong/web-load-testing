// Per-browser connection settings (API URL + optional token). Stored locally only.

const KEY = "loadlab.connection";

export interface ConnectionSettings {
  apiUrl: string;
  token: string;
}

export const DEFAULT_API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function loadConnection(): ConnectionSettings {
  const fallback = { apiUrl: DEFAULT_API_URL, token: "" };
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<ConnectionSettings>;
    return { apiUrl: parsed.apiUrl || DEFAULT_API_URL, token: parsed.token || "" };
  } catch {
    return fallback;
  }
}

export function saveConnection(s: ConnectionSettings): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable: settings last for this page only */
  }
}
