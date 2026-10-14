"use client";

import { AlertTriangle, ShieldCheck } from "lucide-react";
import { PlanChart } from "@/components/charts";
import { Alert } from "@/components/ui/primitives";
import { fmtDuration, fmtNumber, fmtRate } from "@/lib/format";
import type { TestPlan } from "@/lib/types";

const PRESET_LABEL: Record<string, string> = {
  custom: "Custom (constant)",
  smoke: "Smoke",
  baseline: "Baseline",
  load: "Load (ramp up)",
  spike: "Spike",
  stress: "Stress (step up)",
};

export function PlanSummary({ plan }: { plan: TestPlan }) {
  const rows: [string, string][] = [
    ["Request", `${plan.method} ${plan.url_preview}`],
    ["Profile", PRESET_LABEL[plan.preset] ?? plan.preset],
    ["Peak rate", fmtRate(plan.peak_rps)],
    ["Average rate", fmtRate(plan.average_rps)],
    ["Duration", fmtDuration(plan.duration_s)],
    ["Max concurrency", fmtNumber(plan.max_concurrency)],
    ["Timeout", `${plan.timeout_s}s per request`],
    ["Expected requests", `≈ ${fmtNumber(plan.expected_requests)}`],
  ];
  return (
    <div className="space-y-3" data-testid="plan-summary">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="tabular break-all font-medium">{v}</dd>
          </div>
        ))}
      </dl>
      <PlanChart stages={plan.stages} />
      <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-good" aria-hidden />
        Safety limits: ≤ {fmtRate(plan.limits.max_rps)}, ≤ {plan.limits.max_concurrency} concurrent, ≤{" "}
        {fmtDuration(plan.limits.max_duration_s)}, timeout ≤ {plan.limits.max_timeout_s}s. Enforced by the server; the test
        stops automatically at the planned duration.
      </p>
      {plan.warnings.length > 0 && (
        <Alert variant="warning">
          <AlertTriangle aria-hidden />
          <ul className="space-y-1 text-xs">
            {plan.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Alert>
      )}
    </div>
  );
}
