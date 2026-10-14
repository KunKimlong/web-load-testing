"use client";

import { useEffect, useState } from "react";
import { Loader2, Pause, Play, Radio, Square, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, Card, Progress } from "@/components/ui/primitives";
import { LatencyChart, OutcomeChart, RateChart, StatusCodeChart } from "@/components/charts";
import { ErrorsPanel, GeneratorPanel, LatencyPanel, StatusBadge, SummaryGrid } from "@/components/metrics";
import { LoadingState } from "@/components/states";
import { api } from "@/lib/api";
import { fmtDuration } from "@/lib/format";
import { useLiveTest, type LiveState } from "@/lib/use-live-test";
import type { TestRunDetail } from "@/lib/types";

export function LiveView({
  run,
  live,
  onStop,
  onPause,
  onResume,
  busy,
  actionError,
}: {
  run: Pick<TestRunDetail, "id" | "name" | "method" | "target_origin" | "path">;
  live: LiveState;
  onStop: () => void;
  onPause: () => void;
  onResume: () => void;
  busy: boolean;
  actionError: string | null;
}) {
  const s = live.snapshot;
  const status = live.status ?? "running";
  const active = !live.done && (status === "running" || status === "paused" || status === "pending");

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-xl font-semibold">{run.name}</h1>
            <StatusBadge status={status} />
            {live.connection === "live" && active && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <Radio className="size-3.5 animate-pulse text-good" aria-hidden /> Live
              </span>
            )}
            {live.connection === "reconnecting" && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground" role="status">
                <WifiOff className="size-3.5" aria-hidden /> Reconnecting…
              </span>
            )}
          </div>
          <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
            {run.method} {run.target_origin}
            {run.path}
          </p>
        </div>
        {active && (
          <div className="flex gap-2">
            {status === "paused" ? (
              <Button variant="outline" onClick={onResume} disabled={busy}>
                <Play /> Resume
              </Button>
            ) : (
              <Button variant="outline" onClick={onPause} disabled={busy}>
                <Pause /> Pause
              </Button>
            )}
            <Button variant="destructive" size="lg" onClick={onStop} disabled={busy} aria-label="Stop test now">
              {busy ? <Loader2 className="animate-spin" /> : <Square />} Stop test
            </Button>
          </div>
        )}
      </div>

      {actionError && <Alert variant="critical">{actionError}</Alert>}

      {!s ? (
        live.error ? <Alert variant="critical">{live.error}</Alert> : <LoadingState label="Connecting to live metrics…" />
      ) : (
        <>
          <Card className="space-y-2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>
                Elapsed <strong className="tabular">{fmtDuration(s.elapsed_s)}</strong> of {fmtDuration(s.duration_s)}
              </span>
              <span className="text-muted-foreground" aria-live="polite">
                {s.eta}
              </span>
            </div>
            <Progress value={s.progress} label="Test progress" />
          </Card>
          <SummaryGrid s={s} />
          <div className="grid gap-4 lg:grid-cols-2">
            <RateChart timeline={live.timeline} />
            <LatencyChart timeline={live.timeline} />
            <OutcomeChart timeline={live.timeline} />
            <StatusCodeChart codes={s.status_codes} />
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <LatencyPanel l={s.latency} bytes={s.bytes_received} />
            <GeneratorPanel g={s.generator} />
            <ErrorsPanel errors={s.errors} />
          </div>
        </>
      )}
    </div>
  );
}

/** Connects to the event stream and wires the controls to the API. */
export function LiveDashboard({ run, onFinished }: { run: TestRunDetail; onFinished: () => void }) {
  const live = useLiveTest(run.id);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (live.done) {
      const t = setTimeout(onFinished, 600); // allow the final result to be persisted
      return () => clearTimeout(t);
    }
  }, [live.done, onFinished]);

  const act = (fn: () => Promise<unknown>) => async () => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <LiveView
      run={run}
      live={live}
      busy={busy}
      actionError={actionError}
      onStop={act(() => api.stop(run.id))}
      onPause={act(() => api.pause(run.id))}
      onResume={act(() => api.resume(run.id))}
    />
  );
}
