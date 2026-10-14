"use client";

import { useState } from "react";
import { Loader2, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/overlays";
import { Field } from "@/components/config/fields";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { api } from "@/lib/api";
import { DEFAULT_TARGET } from "@/lib/config-schema";
import { fmtDate } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import type { Target } from "@/lib/types";

export default function TargetsPage() {
  const targets = useAsync(() => api.targets());
  const settings = useAsync(() => api.settings());
  const [name, setName] = useState("Local mock API");
  const [baseUrl, setBaseUrl] = useState(DEFAULT_TARGET);
  const [notes, setNotes] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Target | null>(null);

  async function register(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (!authorized) {
      setError("Confirm that you are authorized to test this target.");
      return;
    }
    setSaving(true);
    try {
      const t = await api.createTarget({ name, base_url: baseUrl, notes, authorized });
      setSuccess(`Registered ${t.origin}.`);
      setAuthorized(false);
      targets.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!toDelete) return;
    try {
      await api.deleteTarget(toDelete.id);
      targets.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setToDelete(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Targets"
        description="Register each origin you're authorized to test. Tests to unregistered origins are refused by the server."
      />
      <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Register target</CardTitle>
            <CardDescription>
              {settings.data
                ? settings.data.allow_external_targets
                  ? "Public targets are enabled by the operator."
                  : `Allowed: local development hosts (${settings.data.local_target_hosts.join(", ")}). Public internet targets are disabled by the operator.`
                : "Loading policy…"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={register}>
              <Field label="Name" htmlFor="t-name">
                <Input id="t-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
              </Field>
              <Field label="Base URL" htmlFor="t-url" help="Scheme, host and port only — e.g. http://localhost:8080.">
                <Input id="t-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} required spellCheck={false} />
              </Field>
              <Field label="Notes (optional)" htmlFor="t-notes">
                <Input id="t-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Owner, ticket, environment…" />
              </Field>
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1 size-4" checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} />
                <span>I own this system or have explicit permission to load test it.</span>
              </label>
              {error && <Alert variant="critical">{error}</Alert>}
              {success && <Alert variant="good">{success}</Alert>}
              <Button type="submit" disabled={saving}>
                {saving ? <Loader2 className="animate-spin" /> : <Plus />} Register target
              </Button>
            </form>
          </CardContent>
        </Card>

        <div>
          {targets.loading && !targets.data ? (
            <LoadingState />
          ) : targets.error ? (
            <ErrorState message={targets.error} onRetry={targets.reload} />
          ) : targets.data && targets.data.length === 0 ? (
            <EmptyState title="No targets yet" description="Register the local mock server (http://localhost:8080) to try LoadLab safely." />
          ) : (
            <ul className="space-y-2">
              {targets.data?.map((t) => (
                <li key={t.id}>
                  <Card className="flex items-center justify-between gap-3 p-4">
                    <div className="min-w-0">
                      <p className="flex items-center gap-2 font-medium">
                        <ShieldCheck className="size-4 text-good" aria-hidden /> {t.name}
                        {t.is_local && <Badge variant="info">local</Badge>}
                      </p>
                      <p className="truncate font-mono text-xs text-muted-foreground">{t.origin}</p>
                      <p className="text-xs text-muted-foreground">
                        Registered {fmtDate(t.created_at)}
                        {t.notes ? ` · ${t.notes}` : ""}
                      </p>
                    </div>
                    <Button variant="ghost" size="icon" aria-label={`Remove ${t.name}`} onClick={() => setToDelete(t)}>
                      <Trash2 />
                    </Button>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <Dialog open={!!toDelete} onOpenChange={(o) => !o && setToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove target?</DialogTitle>
            <DialogDescription>
              {toDelete?.origin} will no longer be approved for testing. Existing reports are kept.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToDelete(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => void confirmDelete()}>
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
