"use client";

import Link from "next/link";
import { useEffect } from "react";
import { Activity, PlayCircle, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { MetricCard, StatusBadge } from "@/components/metrics";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { api } from "@/lib/api";
import { fmtDate, fmtMs, fmtPercent, fmtRate } from "@/lib/format";
import { useAsync } from "@/lib/use-async";

export default function OverviewPage() {
  const data = useAsync(async () => {
    const [targets, recent, running, settings] = await Promise.all([
      api.targets(),
      api.list({ limit: 8 }),
      api.list({ status: "running", limit: 10 }),
      api.settings(),
    ]);
    return { targets, recent, running, settings };
  });

  // light refresh while tests are running (the test page itself streams live)
  const runningCount = data.data?.running.total ?? 0;
  const { reload } = data;
  useEffect(() => {
    if (!runningCount) return;
    const t = setInterval(reload, 5000);
    return () => clearInterval(t);
  }, [runningCount, reload]);

  return (
    <>
      <PageHeader
        title="Overview"
        description="Authorized HTTP load testing for systems you own."
        actions={
          <Button asChild>
            <Link href="/tests/new">
              <PlayCircle /> New test
            </Link>
          </Button>
        }
      />
      {data.loading && !data.data ? (
        <LoadingState />
      ) : data.error ? (
        <ErrorState message={data.error} onRetry={data.reload} />
      ) : data.data ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <MetricCard label="Registered targets" value={data.data.targets.length} />
            <MetricCard label="Running tests" value={data.data.running.total} />
            <MetricCard label="Total runs" value={data.data.recent.total} />
            <MetricCard
              label="Your rate limit"
              value={fmtRate(data.data.settings.user.max_rps)}
              sub={`hard limit ${fmtRate(data.data.settings.hard_limits.max_rps)}`}
            />
          </div>

          {data.data.targets.length === 0 && (
            <EmptyState
              title="Register a target to get started"
              description="LoadLab only sends traffic to targets you have registered and confirmed you're authorized to test. Try the bundled mock server at http://localhost:8080."
              action={
                <Button asChild>
                  <Link href="/targets">
                    <ShieldCheck /> Register a target
                  </Link>
                </Button>
              }
            />
          )}

          {data.data.running.items.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Activity className="size-4 text-primary" aria-hidden /> Running now
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.data.running.items.map((r) => (
                  <Link
                    key={r.id}
                    href={`/tests/${r.id}`}
                    className="flex items-center justify-between rounded-md border p-3 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="min-w-0 truncate font-medium">{r.name}</span>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">
                      {fmtRate(r.configured_rps)} <StatusBadge status={r.status} />
                    </span>
                  </Link>
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Recent runs</CardTitle>
            </CardHeader>
            <CardContent>
              {data.data.recent.items.length === 0 ? (
                <p className="text-sm text-muted-foreground">No tests yet.</p>
              ) : (
                <div className="relative overflow-x-auto">
                  <table className="tabular w-full text-sm">
                    <thead className="text-left text-xs text-muted-foreground">
                      <tr>
                        <th scope="col" className="py-2 pr-3 font-medium">Name</th>
                        <th scope="col" className="py-2 pr-3 font-medium">Status</th>
                        <th scope="col" className="py-2 pr-3 font-medium">Achieved</th>
                        <th scope="col" className="py-2 pr-3 font-medium">p95</th>
                        <th scope="col" className="py-2 pr-3 font-medium">Errors</th>
                        <th scope="col" className="py-2 font-medium">Started</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.data.recent.items.map((r) => (
                        <tr key={r.id} className="border-t">
                          <td className="max-w-56 truncate py-2 pr-3">
                            <Link className="font-medium hover:underline" href={`/tests/${r.id}`}>
                              {r.name}
                            </Link>
                          </td>
                          <td className="py-2 pr-3"><StatusBadge status={r.status} /></td>
                          <td className="py-2 pr-3">{fmtRate(r.achieved_rps)}</td>
                          <td className="py-2 pr-3">{fmtMs(r.p95_ms)}</td>
                          <td className="py-2 pr-3">{fmtPercent(r.error_rate)}</td>
                          <td className="py-2 text-xs text-muted-foreground">{fmtDate(r.started_at ?? r.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </>
  );
}
