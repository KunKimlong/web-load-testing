"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Download, GitCompare, Search, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Alert, Card, Input, NativeSelect } from "@/components/ui/primitives";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/overlays";
import { StatusBadge } from "@/components/metrics";
import { SensitiveWarning } from "@/components/report-view";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { api, downloadExport } from "@/lib/api";
import { fmtDate, fmtDuration, fmtMs, fmtNumber, fmtPercent, fmtRate } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import type { TestRunSummary } from "@/lib/types";

const PAGE = 25;

export default function HistoryPage() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<TestRunSummary[]>([]);
  const [deleting, setDeleting] = useState<TestRunSummary | "all" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const targets = useAsync(() => api.targets());
  const list = useAsync(
    () =>
      api.list({
        q: query,
        target,
        status,
        date_from: from ? new Date(from).toISOString() : undefined,
        date_to: to ? new Date(`${to}T23:59:59`).toISOString() : undefined,
        limit: PAGE,
        offset,
      }),
    [query, target, status, from, to, offset],
  );

  const toggle = (r: TestRunSummary) =>
    setSelected((sel) => {
      if (sel.some((s) => s.id === r.id)) return sel.filter((s) => s.id !== r.id);
      if (sel.length && sel[0].target_origin !== r.target_origin) return [r]; // compare only same target
      return [...sel, r].slice(-2);
    });

  async function doDelete() {
    try {
      if (deleting === "all") {
        const r = await api.removeAll();
        setMessage(`Deleted ${r.deleted} run(s). Running tests were kept.`);
      } else if (deleting) {
        await api.remove(deleting.id);
      }
      setSelected([]);
      list.reload();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setDeleting(null);
    }
  }

  const exportAll = (fmt: "csv" | "json") => async () => {
    try {
      await downloadExport(`/api/tests/export?format=${fmt}`, `loadlab-history.${fmt}`);
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  return (
    <>
      <PageHeader
        title="Test history"
        description="Search, compare, export and delete previous runs."
        actions={
          <>
            <Button variant="outline" size="sm" onClick={exportAll("csv")}>
              <Download /> CSV
            </Button>
            <Button variant="outline" size="sm" onClick={exportAll("json")}>
              <Download /> JSON
            </Button>
            <Button variant="outline" size="sm" onClick={() => setDeleting("all")}>
              <Trash2 /> Delete all
            </Button>
          </>
        }
      />
      <div className="space-y-4">
        <SensitiveWarning />
        <Card className="p-3">
          <form
            className="grid gap-2 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-[1fr_200px_140px_150px_150px_auto]"
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setQuery(q);
            }}
            role="search"
          >
            <Input className="sm:col-span-2 md:col-span-3 xl:col-span-1" aria-label="Search by name, target or path" placeholder="Search name, target, path…" value={q} onChange={(e) => setQ(e.target.value)} />
            <NativeSelect aria-label="Filter by target" value={target} onChange={(e) => { setTarget(e.target.value); setOffset(0); }}>
              <option value="">All targets</option>
              {targets.data?.map((t) => (
                <option key={t.id} value={t.origin}>{t.origin}</option>
              ))}
            </NativeSelect>
            <NativeSelect aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
              <option value="">Any status</option>
              {["running", "completed", "stopped", "failed"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </NativeSelect>
            <Input type="date" aria-label="From date" value={from} onChange={(e) => { setFrom(e.target.value); setOffset(0); }} />
            <Input type="date" aria-label="To date" value={to} onChange={(e) => { setTo(e.target.value); setOffset(0); }} />
            <Button type="submit" variant="secondary">
              <Search /> Search
            </Button>
          </form>
        </Card>

        {message && <Alert variant="info">{message}</Alert>}

        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">
            {selected.length === 0
              ? "Select two runs against the same target to compare."
              : `${selected.length} selected (${selected[0].target_origin})`}
          </span>
          <Button
            size="sm"
            disabled={selected.length !== 2}
            onClick={() => router.push(`/history/compare?a=${selected[0].id}&b=${selected[1].id}`)}
          >
            <GitCompare /> Compare
          </Button>
        </div>

        {list.loading && !list.data ? (
          <LoadingState rows={5} />
        ) : list.error ? (
          <ErrorState message={list.error} onRetry={list.reload} />
        ) : list.data && list.data.items.length === 0 ? (
          <EmptyState
            title="No runs found"
            description={query || target || status || from || to ? "Try different filters." : "Completed tests will appear here."}
          />
        ) : (
          <Card className="relative overflow-x-auto">
            <table className="tabular w-full min-w-[900px] text-sm [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b">
                  <th scope="col" className="p-3"><span className="sr-only">Select</span></th>
                  <th scope="col" className="p-3 font-medium">Test</th>
                  <th scope="col" className="p-3 font-medium">Status</th>
                  <th scope="col" className="p-3 font-medium">Configured / achieved</th>
                  <th scope="col" className="p-3 font-medium">Requests</th>
                  <th scope="col" className="p-3 font-medium">Errors</th>
                  <th scope="col" className="p-3 font-medium">p50 / p95 / p99</th>
                  <th scope="col" className="p-3 font-medium">Started</th>
                  <th scope="col" className="p-3"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {list.data?.items.map((r) => (
                  <tr key={r.id} className="border-b last:border-0 hover:bg-accent/40">
                    <td className="p-3">
                      <input
                        type="checkbox"
                        className="size-4"
                        aria-label={`Select ${r.name} for comparison`}
                        checked={selected.some((s) => s.id === r.id)}
                        onChange={() => toggle(r)}
                        disabled={["running", "paused", "pending"].includes(r.status)}
                      />
                    </td>
                    <td className="max-w-72 p-3 !whitespace-normal">
                      <Link href={`/tests/${r.id}`} className="font-medium hover:underline">{r.name}</Link>
                      <p className="truncate font-mono text-xs text-muted-foreground">
                        {r.method} {r.target_origin}{r.path} · {r.preset}
                      </p>
                    </td>
                    <td className="p-3"><StatusBadge status={r.status} /></td>
                    <td className="p-3 text-xs">{fmtRate(r.configured_rps)} / {fmtRate(r.achieved_rps)}</td>
                    <td className="p-3">{fmtNumber(r.total)}</td>
                    <td className="p-3">{fmtPercent(r.error_rate)}</td>
                    <td className="p-3 text-xs">{fmtMs(r.p50_ms)} / {fmtMs(r.p95_ms)} / {fmtMs(r.p99_ms)}</td>
                    <td className="p-3 text-xs text-muted-foreground">
                      {fmtDate(r.started_at ?? r.created_at)}
                      <br />
                      {fmtDuration(r.duration_s)}
                    </td>
                    <td className="p-3">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${r.name}`}
                        disabled={["running", "paused", "pending"].includes(r.status)}
                        onClick={() => setDeleting(r)}
                      >
                        <Trash2 />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}

        {list.data && list.data.total > PAGE && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {offset + 1}–{Math.min(offset + PAGE, list.data.total)} of {list.data.total}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                Previous
              </Button>
              <Button variant="outline" size="sm" disabled={offset + PAGE >= list.data.total} onClick={() => setOffset(offset + PAGE)}>
                Next
              </Button>
            </div>
          </div>
        )}
      </div>

      <Dialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{deleting === "all" ? "Delete all history?" : "Delete this run?"}</DialogTitle>
            <DialogDescription>
              {deleting === "all"
                ? "All finished test runs and their reports will be permanently deleted. Running tests are kept."
                : `"${deleting && typeof deleting === "object" ? deleting.name : ""}" and its report will be permanently deleted.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="destructive" onClick={() => void doDelete()}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
