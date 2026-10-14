"use client";

import Link from "next/link";
import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Line, LineChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { StatusBadge } from "@/components/metrics";
import { ErrorState, LoadingState } from "@/components/states";
import { api } from "@/lib/api";
import { delta, fmtDate, fmtMs, fmtNumber, fmtPercent, fmtRate } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import type { TestReport } from "@/lib/types";

type Row = { label: string; a: number | null; b: number | null; fmt: (n: number | null) => string; lowerIsBetter: boolean };

function rows(a: TestReport, b: TestReport): Row[] {
  const la = a.summary?.latency;
  const lb = b.summary?.latency;
  return [
    { label: "Achieved rate", a: a.achieved_rps, b: b.achieved_rps, fmt: fmtRate, lowerIsBetter: false },
    { label: "Total requests", a: a.total, b: b.total, fmt: (n) => fmtNumber(n), lowerIsBetter: false },
    { label: "Error rate", a: a.error_rate, b: b.error_rate, fmt: fmtPercent, lowerIsBetter: true },
    { label: "Average latency", a: la?.avg ?? null, b: lb?.avg ?? null, fmt: fmtMs, lowerIsBetter: true },
    { label: "p50", a: a.p50_ms, b: b.p50_ms, fmt: fmtMs, lowerIsBetter: true },
    { label: "p90", a: la?.p90 ?? null, b: lb?.p90 ?? null, fmt: fmtMs, lowerIsBetter: true },
    { label: "p95", a: a.p95_ms, b: b.p95_ms, fmt: fmtMs, lowerIsBetter: true },
    { label: "p99", a: a.p99_ms, b: b.p99_ms, fmt: fmtMs, lowerIsBetter: true },
    { label: "Max latency", a: la?.max ?? null, b: lb?.max ?? null, fmt: fmtMs, lowerIsBetter: true },
    { label: "Dropped", a: a.summary?.dropped ?? null, b: b.summary?.dropped ?? null, fmt: (n) => fmtNumber(n), lowerIsBetter: true },
  ];
}

function Compare() {
  const params = useSearchParams();
  const a = params.get("a") ?? "";
  const b = params.get("b") ?? "";
  const data = useAsync(() => api.compare(a, b), [a, b]);

  const merged = useMemo(() => {
    if (!data.data) return [];
    const len = Math.max(data.data.a.timeline.length, data.data.b.timeline.length);
    return Array.from({ length: len }, (_, i) => ({
      t: i + 1,
      a: data.data!.a.timeline[i]?.p95_ms ?? null,
      b: data.data!.b.timeline[i]?.p95_ms ?? null,
    }));
  }, [data.data]);

  if (!a || !b) return <ErrorState message="Pick two runs on the History page to compare." />;
  if (data.loading && !data.data) return <LoadingState />;
  if (data.error) return <ErrorState message={data.error} onRetry={data.reload} />;
  if (!data.data) return null;
  const { a: ra, b: rb } = data.data;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        {[ra, rb].map((r, i) => (
          <Card key={r.id} className="p-4">
            <p className="text-xs text-muted-foreground">Run {i === 0 ? "A" : "B"}</p>
            <Link href={`/tests/${r.id}`} className="font-medium hover:underline">{r.name}</Link>
            <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
              <StatusBadge status={r.status} /> {fmtDate(r.started_at)} · {r.preset}
            </p>
          </Card>
        ))}
      </div>
      <Card className="relative overflow-x-auto">
        <table className="tabular w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b">
              <th scope="col" className="p-3 font-medium">Metric</th>
              <th scope="col" className="p-3 font-medium">A</th>
              <th scope="col" className="p-3 font-medium">B</th>
              <th scope="col" className="p-3 font-medium">Change (B vs A)</th>
            </tr>
          </thead>
          <tbody>
            {rows(ra, rb).map((r) => {
              const d = delta(r.a, r.b);
              const better = d === null || Math.abs(d) < 0.5 ? null : r.lowerIsBetter ? d < 0 : d > 0;
              return (
                <tr key={r.label} className="border-b last:border-0">
                  <td className="p-3">{r.label}</td>
                  <td className="p-3">{r.fmt(r.a)}</td>
                  <td className="p-3">{r.fmt(r.b)}</td>
                  <td className={`p-3 ${better === true ? "text-text-good" : better === false ? "text-critical" : "text-muted-foreground"}`}>
                    {d === null ? "—" : `${d > 0 ? "▲ +" : d < 0 ? "▼ " : ""}${d.toFixed(1)}%`}
                    {better !== null && <span className="sr-only">{better ? " (better)" : " (worse)"}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>p95 latency over time</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-60" role="img" aria-label="p95 latency comparison chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={merged} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="t" stroke="var(--chart-axis)" fontSize={11} unit="s" tickLine={false} />
                <YAxis stroke="var(--chart-axis)" fontSize={11} unit="ms" width={56} tickLine={false} />
                <Tooltip
                  contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", fontSize: 12 }}
                  formatter={(v) => fmtMs(v as number)}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line name="Run A" dataKey="a" stroke="var(--series-1)" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
                <Line name="Run B" dataKey="b" stroke="var(--series-2)" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default function ComparePage() {
  return (
    <>
      <PageHeader
        title="Compare runs"
        description="Side-by-side results for two runs against the same target."
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/history"><ArrowLeft /> History</Link>
          </Button>
        }
      />
      <Suspense fallback={<LoadingState />}>
        <Compare />
      </Suspense>
    </>
  );
}
