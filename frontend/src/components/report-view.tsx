"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, Download, Info, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { LatencyChart, OutcomeChart, PlanChart, RateChart, StatusCodeChart } from "@/components/charts";
import { ErrorsPanel, GeneratorPanel, LatencyPanel, StatusBadge, SummaryGrid } from "@/components/metrics";
import { downloadExport } from "@/lib/api";
import { fmtDate, fmtDuration, fmtNumber, fmtRate } from "@/lib/format";
import type { TestReport } from "@/lib/types";

const STOP_REASONS: Record<string, string> = {
  completed: "Ran for the full planned duration.",
  stopped: "Stopped by the user.",
  pause_timeout: "Stopped automatically: paused for too long.",
  shutdown: "Stopped because the server shut down.",
  hard_deadline: "Stopped by the hard safety deadline.",
  error: "The test runner failed unexpectedly.",
  start_failed: "The test could not be started.",
};

export function SensitiveWarning() {
  return (
    <Alert variant="warning">
      <AlertTriangle aria-hidden />
      <span className="text-xs">
        Reports may contain sensitive endpoint metadata (URLs, header names, payload shapes). Credentials are redacted, but
        review exports before sharing them.
      </span>
    </Alert>
  );
}

export function ExportButtons({ id, name }: { id: string; name: string }) {
  const [error, setError] = useState<string | null>(null);
  const run = (fmt: "csv" | "json") => async () => {
    setError(null);
    try {
      await downloadExport(`/api/tests/${id}/export?format=${fmt}`, `loadlab-${name}.${fmt}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" onClick={run("json")}>
        <Download /> JSON report
      </Button>
      <Button variant="outline" size="sm" onClick={run("csv")}>
        <Download /> CSV timeline
      </Button>
      {error && <span className="text-xs text-critical" role="alert">{error}</span>}
    </div>
  );
}

export function ReportView({ report }: { report: TestReport }) {
  const s = report.summary;
  const cfg = report.config;
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-xl font-semibold">{report.name}</h1>
            <StatusBadge status={report.status} />
          </div>
          <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
            {report.method} {report.plan?.url_preview ?? report.target_origin + report.path}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Started {fmtDate(report.started_at)} · ran {fmtDuration(report.duration_s)} ·{" "}
            {STOP_REASONS[report.stop_reason ?? ""] ?? report.stop_reason}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ExportButtons id={report.id} name={report.name} />
          <Button asChild size="sm" variant="secondary">
            <Link href={`/tests/new?from=${report.id}`}>
              <RotateCw /> Run again
            </Link>
          </Button>
        </div>
      </div>

      <SensitiveWarning />

      {!s ? (
        <Alert variant="info">
          <Info aria-hidden /> No metrics were recorded for this run.
        </Alert>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card className="p-3">
              <p className="text-xs text-muted-foreground">Configured peak</p>
              <p className="text-xl font-semibold">{fmtRate(report.configured_rps)}</p>
            </Card>
            <Card className="p-3">
              <p className="text-xs text-muted-foreground">Achieved average</p>
              <p className="text-xl font-semibold">{fmtRate(report.achieved_rps)}</p>
            </Card>
            <Card className="p-3">
              <p className="text-xs text-muted-foreground">Max in flight</p>
              <p className="text-xl font-semibold">{fmtNumber(s.max_in_flight ?? null)}</p>
            </Card>
            <Card className="p-3">
              <p className="text-xs text-muted-foreground">Cancelled at stop</p>
              <p className="text-xl font-semibold">{fmtNumber(s.cancelled)}</p>
            </Card>
          </div>
          <SummaryGrid s={{ ...s, actual_rps: report.achieved_rps ?? 0, target_rps: report.configured_rps }} />
          <div className="grid gap-4 lg:grid-cols-2">
            <RateChart timeline={report.timeline} />
            <LatencyChart timeline={report.timeline} />
            <OutcomeChart timeline={report.timeline} />
            <StatusCodeChart codes={s.status_codes} />
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <LatencyPanel l={s.latency} bytes={s.bytes_received} />
            <GeneratorPanel g={s.generator_at_end} />
            <ErrorsPanel errors={s.errors} />
          </div>
        </>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Planned profile</CardTitle>
          </CardHeader>
          <CardContent>{report.plan?.stages && <PlanChart stages={report.plan.stages} />}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Configuration (secrets redacted)</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="max-h-72 overflow-auto rounded bg-muted p-3 text-[11px]">
              {JSON.stringify(
                {
                  preset: cfg.preset,
                  rate: `${cfg.rate} ${cfg.rate_unit}`,
                  duration_s: cfg.duration_s,
                  max_concurrency: cfg.max_concurrency,
                  timeout_s: cfg.timeout_s,
                  query: cfg.query,
                  headers: cfg.headers,
                  auth: cfg.auth,
                  body: cfg.body,
                  follow_redirects: cfg.follow_redirects,
                  retries: cfg.retries,
                },
                null,
                2,
              )}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
