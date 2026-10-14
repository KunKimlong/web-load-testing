"use client";

import { memo } from "react";
import { AlertTriangle, CheckCircle2, Cpu, OctagonX } from "lucide-react";
import { Alert, Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { InfoTip } from "@/components/ui/overlays";
import { fmtBytes, fmtMs, fmtNumber, fmtPercent, fmtRate } from "@/lib/format";
import type { ErrorSample, GeneratorStats, LatencyStats, MetricsSnapshot, TestStatus } from "@/lib/types";

export const HELP = {
  actual: "Requests actually sent per second (3-second rolling average).",
  target: "Rate the scheduler is aiming for right now, following the planned load profile.",
  total: "Requests sent so far, including those still in flight.",
  success: "Requests that received a 2xx or 3xx response.",
  failure: "4xx/5xx responses plus timeouts, connection and protocol errors.",
  errorRate: "Failed requests divided by completed requests.",
  inFlight: "Requests sent and awaiting a response. Never exceeds the concurrency limit.",
  dropped:
    "Scheduled requests that were not sent because all concurrency slots were busy (backpressure) or the generator fell behind. High values mean the target can't keep up at this concurrency.",
  p50: "Median: half of the requests were faster than this.",
  p90: "90% of requests completed faster than this.",
  p95: "95% of requests completed faster than this.",
  p99: "99% of requests completed faster than this — the tail most users rarely see.",
};

export function MetricCard({
  label,
  value,
  sub,
  help,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  help?: string;
  tone?: "good" | "critical" | "warning";
}) {
  const toneClass = tone === "critical" ? "text-critical" : tone === "good" ? "text-text-good" : "";
  return (
    <Card className="p-3">
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        {label}
        {help && <InfoTip label={label} text={help} />}
      </div>
      <div className={`mt-1 text-2xl font-semibold leading-tight ${toneClass}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </Card>
  );
}

export function StatusBadge({ status }: { status: TestStatus | string | null }) {
  const map: Record<string, { v: "good" | "warning" | "critical" | "info" | "default"; label: string }> = {
    running: { v: "info", label: "Running" },
    pending: { v: "default", label: "Starting" },
    paused: { v: "warning", label: "Paused" },
    completed: { v: "good", label: "Completed" },
    stopped: { v: "warning", label: "Stopped" },
    failed: { v: "critical", label: "Failed" },
  };
  const m = map[status ?? ""] ?? { v: "default" as const, label: status ?? "Unknown" };
  return (
    <Badge variant={m.v}>
      {m.v === "good" && <CheckCircle2 className="size-3" aria-hidden />}
      {m.v === "critical" && <OctagonX className="size-3" aria-hidden />}
      {m.v === "warning" && <AlertTriangle className="size-3" aria-hidden />}
      {m.label}
    </Badge>
  );
}

export const SummaryGrid = memo(function SummaryGrid({ s }: { s: MetricsSnapshot }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
      <MetricCard label="Achieved rate" value={fmtRate(s.actual_rps)} help={HELP.actual} />
      <MetricCard
        label="Target rate"
        value={fmtRate(s.target_rps)}
        sub={`Peak ${fmtRate(s.configured_peak_rps)}`}
        help={HELP.target}
      />
      <MetricCard label="Total sent" value={fmtNumber(s.total)} help={HELP.total} />
      <MetricCard label="Successful" value={fmtNumber(s.success)} tone="good" help={HELP.success} />
      <MetricCard
        label="Failed"
        value={fmtNumber(s.failure)}
        tone={s.failure > 0 ? "critical" : undefined}
        help={HELP.failure}
      />
      <MetricCard
        label="Error rate"
        value={fmtPercent(s.error_rate)}
        tone={s.error_rate > 5 ? "critical" : undefined}
        help={HELP.errorRate}
      />
      <MetricCard label="In flight" value={fmtNumber(s.in_flight)} help={HELP.inFlight} />
      <MetricCard
        label="Dropped"
        value={fmtNumber(s.dropped)}
        tone={s.dropped > 0 ? "warning" : undefined}
        sub={s.retries ? `${s.retries} retries` : undefined}
        help={HELP.dropped}
      />
    </div>
  );
});

export const LatencyPanel = memo(function LatencyPanel({ l, bytes }: { l: LatencyStats; bytes?: number }) {
  const rows: [string, number | null, string | undefined][] = [
    ["Average", l.avg, undefined],
    ["Median (p50)", l.p50, HELP.p50],
    ["p90", l.p90, HELP.p90],
    ["p95", l.p95, HELP.p95],
    ["p99", l.p99, HELP.p99],
    ["Min", l.min, undefined],
    ["Max", l.max, undefined],
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Latency</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="tabular grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          {rows.map(([k, v, help]) => (
            <div key={k} className="contents">
              <dt className="flex items-center gap-1 text-muted-foreground">
                {k}
                {help && <InfoTip label={k} text={help} />}
              </dt>
              <dd className="text-right font-medium">{fmtMs(v)}</dd>
            </div>
          ))}
          {bytes !== undefined && (
            <div className="contents">
              <dt className="text-muted-foreground">Received</dt>
              <dd className="text-right font-medium">{fmtBytes(bytes)}</dd>
            </div>
          )}
        </dl>
      </CardContent>
    </Card>
  );
});

export const GeneratorPanel = memo(function GeneratorPanel({ g }: { g: GeneratorStats | null | undefined }) {
  if (!g) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Cpu className="size-4" aria-hidden /> Load generator
          <InfoTip
            label="Load generator"
            text="Resource use of LoadLab itself. If the generator is saturated, measured latency includes client-side delay and the target may not be the bottleneck."
          />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <dl className="tabular grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted-foreground">CPU (1 core = 100%)</dt>
          <dd className="text-right font-medium">{fmtNumber(g.cpu_percent, 1)}%</dd>
          <dt className="text-muted-foreground">Memory (RSS)</dt>
          <dd className="text-right font-medium">{fmtNumber(g.rss_mb, 1)} MB</dd>
          <dt className="text-muted-foreground">Event-loop lag</dt>
          <dd className="text-right font-medium">{fmtMs(g.loop_lag_ms)}</dd>
          <dt className="text-muted-foreground">Connection limit</dt>
          <dd className="text-right font-medium">{g.open_connections_limit || "—"}</dd>
        </dl>
        {g.saturated ? (
          <Alert variant="warning">
            <AlertTriangle aria-hidden />
            <div>
              <p className="font-medium">Saturation detected</p>
              <ul className="list-disc pl-4 text-xs">
                {g.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          </Alert>
        ) : (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <CheckCircle2 className="size-3.5 text-good" aria-hidden /> Generator healthy
          </p>
        )}
      </CardContent>
    </Card>
  );
});

const ERROR_LABELS: Record<string, string> = {
  timeout: "Timeouts",
  connect_error: "Connection errors",
  blocked_destination: "Blocked by safety policy",
  redirect_blocked: "Redirect blocked",
  protocol_error: "Protocol errors",
  network_error: "Network errors",
  http_error: "HTTP client errors",
  internal_error: "Internal errors",
};

export const ErrorsPanel = memo(function ErrorsPanel({ errors }: { errors: ErrorSample[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Errors without a response</CardTitle>
      </CardHeader>
      <CardContent>
        {errors.length === 0 ? (
          <p className="text-sm text-muted-foreground">None.</p>
        ) : (
          <ul className="space-y-3">
            {errors.map((e) => (
              <li key={e.kind}>
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">{ERROR_LABELS[e.kind] ?? e.kind}</span>
                  <Badge variant="critical">{fmtNumber(e.count)}</Badge>
                </div>
                {e.samples.map((s) => (
                  <p key={s} className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
                    {s}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
});
