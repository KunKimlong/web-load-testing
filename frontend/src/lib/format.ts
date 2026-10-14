import type { RateUnit } from "./types";

export function toRps(rate: number, unit: RateUnit): number {
  return unit === "rpm" ? rate / 60 : rate;
}

export function fromRps(rps: number, unit: RateUnit): number {
  return unit === "rpm" ? rps * 60 : rps;
}

export function fmtNumber(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  if (ms >= 100) return `${ms.toFixed(0)} ms`;
  return `${ms.toFixed(1)} ms`;
}

export function fmtRate(rps: number | null | undefined): string {
  if (rps === null || rps === undefined) return "—";
  if (rps > 0 && rps < 1) return `${fmtNumber(rps * 60, 1)} RPM`;
  return `${fmtNumber(rps, 2)} RPS`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m ? `${m}m ${r.toString().padStart(2, "0")}s` : `${r}s`;
}

export function fmtPercent(p: number | null | undefined): string {
  if (p === null || p === undefined) return "—";
  return `${p.toFixed(p < 10 ? 2 : 1)}%`;
}

export function fmtBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

export function statusClass(code: string): "2xx" | "3xx" | "4xx" | "5xx" | "other" {
  const c = Number(code);
  if (c >= 200 && c < 300) return "2xx";
  if (c >= 300 && c < 400) return "3xx";
  if (c >= 400 && c < 500) return "4xx";
  if (c >= 500 && c < 600) return "5xx";
  return "other";
}

export function newRequestId(): string {
  return globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? `${Date.now()}${Math.random().toString(16).slice(2)}`;
}

/** Percentage change from a to b, or null when undefined. */
export function delta(a: number | null, b: number | null): number | null {
  if (a === null || b === null || a === 0) return null;
  return ((b - a) / a) * 100;
}
