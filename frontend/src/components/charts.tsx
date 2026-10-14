"use client";

import { memo, useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { InfoTip } from "@/components/ui/overlays";
import { fmtMs, fmtNumber, statusClass } from "@/lib/format";
import type { Stage, TimelinePoint } from "@/lib/types";

const AXIS = { stroke: "var(--chart-axis)", fontSize: 11, tickLine: false } as const;
const GRID = { stroke: "var(--chart-grid)", strokeDasharray: "0", vertical: false } as const;
const TOOLTIP = {
  contentStyle: {
    background: "var(--popover)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    fontSize: 12,
    color: "var(--popover-foreground)",
  },
  labelStyle: { color: "var(--muted-foreground)" },
  cursor: { stroke: "var(--chart-axis)", strokeWidth: 1 },
} as const;
const LEGEND = { wrapperStyle: { fontSize: 12, color: "var(--muted-foreground)" }, iconSize: 10 } as const;

export function ChartCard({
  title,
  help,
  description,
  children,
  table,
}: {
  title: string;
  help?: string;
  description?: string;
  children: React.ReactNode;
  table?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          {title}
          {help && <InfoTip label={title} text={help} />}
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>
        <div className="h-56 w-full" role="img" aria-label={`${title} chart`}>
          {children}
        </div>
        {table && (
          <details className="mt-2 text-xs">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">View as table</summary>
            <div className="relative mt-2 max-h-56 overflow-auto rounded border">{table}</div>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function SimpleTable({ columns, rows }: { columns: string[]; rows: (string | number)[][] }) {
  return (
    <table className="tabular w-full text-left">
      <thead className="sticky top-0 bg-muted">
        <tr>
          {columns.map((c) => (
            <th key={c} scope="col" className="px-2 py-1 font-medium">
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-t">
            {r.map((v, j) => (
              <td key={j} className="px-2 py-1">
                {v}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const tail = (t: TimelinePoint[]) => t.slice(-120).reverse();

export const RateChart = memo(function RateChart({ timeline }: { timeline: TimelinePoint[] }) {
  return (
    <ChartCard
      title="Request rate"
      help="Target is the rate the scheduler aims for; Achieved is requests actually sent each second. A gap means backpressure (concurrency limit) or generator saturation."
      table={<SimpleTable columns={["t (s)", "Target RPS", "Achieved RPS", "Dropped"]} rows={tail(timeline).map((p) => [p.t, p.target_rps, p.sent, p.dropped])} />}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={timeline} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="t" {...AXIS} unit="s" minTickGap={24} />
          <YAxis {...AXIS} allowDecimals={false} width={44} />
          <Tooltip {...TOOLTIP} labelFormatter={(t) => `t = ${t}s`} />
          <Legend {...LEGEND} />
          <Line name="Target" type="stepAfter" dataKey="target_rps" stroke="var(--series-1)" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
          <Line name="Achieved" type="monotone" dataKey="sent" stroke="var(--series-2)" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
});

export const LatencyChart = memo(function LatencyChart({ timeline }: { timeline: TimelinePoint[] }) {
  return (
    <ChartCard
      title="Response latency"
      help="Average and 95th percentile latency of requests that completed in each second."
      table={<SimpleTable columns={["t (s)", "Avg", "p95"]} rows={tail(timeline).map((p) => [p.t, fmtMs(p.avg_ms), fmtMs(p.p95_ms)])} />}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={timeline} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="t" {...AXIS} unit="s" minTickGap={24} />
          <YAxis {...AXIS} unit="ms" width={56} />
          <Tooltip {...TOOLTIP} labelFormatter={(t) => `t = ${t}s`} formatter={(v) => fmtMs(v as number)} />
          <Legend {...LEGEND} />
          <Line name="Average" type="monotone" dataKey="avg_ms" stroke="var(--series-1)" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
          <Line name="p95" type="monotone" dataKey="p95_ms" stroke="var(--series-2)" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
});

export const OutcomeChart = memo(function OutcomeChart({ timeline }: { timeline: TimelinePoint[] }) {
  return (
    <ChartCard
      title="Success vs failure"
      help="Completed requests per second. Failures include HTTP 4xx/5xx, timeouts and connection errors."
      table={<SimpleTable columns={["t (s)", "Success", "Failure"]} rows={tail(timeline).map((p) => [p.t, p.success, p.failure])} />}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={timeline} margin={{ top: 8, right: 12, bottom: 0, left: -8 }} barCategoryGap={1}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="t" {...AXIS} unit="s" minTickGap={24} />
          <YAxis {...AXIS} allowDecimals={false} width={44} />
          <Tooltip {...TOOLTIP} labelFormatter={(t) => `t = ${t}s`} cursor={{ fill: "var(--accent)" }} />
          <Legend {...LEGEND} />
          <Bar name="Success" dataKey="success" stackId="o" fill="var(--status-good)" isAnimationActive={false} />
          <Bar name="Failure" dataKey="failure" stackId="o" fill="var(--status-critical)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
});

const CODE_COLORS: Record<string, string> = {
  "2xx": "var(--status-good)",
  "3xx": "var(--series-1)",
  "4xx": "var(--status-warning)",
  "5xx": "var(--status-critical)",
  other: "var(--chart-axis)",
};

export const StatusCodeChart = memo(function StatusCodeChart({ codes }: { codes: Record<string, number> }) {
  const data = useMemo(
    () => Object.entries(codes).map(([code, count]) => ({ code, count, cls: statusClass(code) })),
    [codes],
  );
  return (
    <ChartCard
      title="HTTP status codes"
      help="Distribution of response status codes. 2xx/3xx count as success; 4xx/5xx as failures. Requests with no response (timeouts, connection errors) appear under Errors."
      table={<SimpleTable columns={["Status", "Class", "Count"]} rows={data.map((d) => [d.code, d.cls, d.count])} />}
    >
      {data.length === 0 ? (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">No responses yet</div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 0, left: 0 }} barCategoryGap={6}>
            <CartesianGrid {...GRID} horizontal={false} vertical />
            <XAxis type="number" {...AXIS} allowDecimals={false} />
            <YAxis type="category" dataKey="code" {...AXIS} width={44} />
            <Tooltip {...TOOLTIP} cursor={{ fill: "var(--accent)" }} formatter={(v) => [fmtNumber(v as number), "Responses"]} />
            <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={28} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.code} fill={CODE_COLORS[d.cls]} />
              ))}
              <LabelList dataKey="count" position="right" fill="var(--muted-foreground)" fontSize={11} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  );
});

export function stagesToSeries(stages: Stage[]): { t: number; rps: number }[] {
  const out: { t: number; rps: number }[] = [];
  for (const s of stages) {
    out.push({ t: s.start_s, rps: s.from_rps });
    out.push({ t: s.end_s, rps: s.to_rps });
  }
  return out;
}

export const PlanChart = memo(function PlanChart({ stages }: { stages: Stage[] }) {
  const data = useMemo(() => stagesToSeries(stages), [stages]);
  return (
    <div className="h-36 w-full" role="img" aria-label="Planned request rate over time">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} {...AXIS} unit="s" />
          <YAxis {...AXIS} width={44} />
          <Tooltip {...TOOLTIP} formatter={(v) => [`${fmtNumber(v as number, 2)} RPS`, "Planned"]} labelFormatter={(t) => `t = ${t}s`} />
          <Area type="linear" dataKey="rps" stroke="var(--series-1)" strokeWidth={2} fill="var(--series-1)" fillOpacity={0.15} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
});
