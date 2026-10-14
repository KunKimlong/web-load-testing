"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Save } from "lucide-react";
import { useTheme } from "next-themes";
import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Alert, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, NativeSelect } from "@/components/ui/primitives";
import { Field, SecretInput } from "@/components/config/fields";
import { ErrorState, LoadingState } from "@/components/states";
import { api } from "@/lib/api";
import { loadConnection, saveConnection } from "@/lib/client-settings";
import { fmtRate } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import type { UserSettings } from "@/lib/types";

function ConnectionCard({ onSaved }: { onSaved: () => void }) {
  const [apiUrl, setApiUrl] = useState("");
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  useEffect(() => {
    const c = loadConnection();
    setApiUrl(c.apiUrl);
    setToken(c.token);
  }, []);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    saveConnection({ apiUrl: apiUrl.trim(), token: token.trim() });
    try {
      await api.health();
      setStatus("Connected.");
    } catch (err) {
      setStatus((err as Error).message);
    }
    onSaved();
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>API connection</CardTitle>
        <CardDescription>Stored in this browser only.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={save}>
          <Field label="API URL" htmlFor="api-url">
            <Input id="api-url" value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} spellCheck={false} />
          </Field>
          <Field label="API token" htmlFor="api-token" help="Required when the server runs with LOADLAB_AUTH_MODE=token.">
            <SecretInput id="api-token" label="API token" value={token} onChange={setToken} placeholder="(none)" />
          </Field>
          <div className="flex items-center gap-3">
            <Button type="submit" variant="secondary">
              <Save /> Save &amp; test
            </Button>
            {status && <span className="text-xs text-muted-foreground" role="status">{status}</span>}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const settings = useAsync(() => api.settings());
  const { theme, setTheme } = useTheme();
  const [limits, setLimits] = useState<UserSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (settings.data) setLimits(settings.data.user);
  }, [settings.data]);

  async function saveLimits(e: React.FormEvent) {
    e.preventDefault();
    if (!limits) return;
    setSaving(true);
    setMessage(null);
    try {
      await api.updateSettings(limits);
      setMessage({ ok: true, text: "Limits saved." });
      settings.reload();
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setSaving(false);
    }
  }

  const hard = settings.data?.hard_limits;
  const num = (k: keyof UserSettings) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setLimits((l) => (l ? { ...l, [k]: e.target.valueAsNumber } : l));

  return (
    <>
      <PageHeader title="Settings" description="Connection, personal safety limits and appearance." />
      <div className="grid gap-4 lg:grid-cols-2">
        <ConnectionCard onSaved={settings.reload} />

        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
          </CardHeader>
          <CardContent>
            <Field label="Theme" htmlFor="theme">
              <NativeSelect id="theme" value={theme ?? "system"} onChange={(e) => setTheme(e.target.value)}>
                <option value="system">System</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </NativeSelect>
            </Field>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Your safety limits</CardTitle>
            <CardDescription>
              Tests and presets can never exceed these. They can be lowered freely but never raised above the server&apos;s hard
              limits{hard ? ` (${fmtRate(hard.max_rps)}, ${hard.max_concurrency} concurrent, ${hard.max_duration_s}s)` : ""}.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {settings.loading && !settings.data ? (
              <LoadingState rows={2} />
            ) : settings.error ? (
              <ErrorState message={settings.error} onRetry={settings.reload} />
            ) : limits && hard ? (
              <form className="space-y-4" onSubmit={saveLimits}>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Field label="Max rate (RPS)" htmlFor="l-rps">
                    <Input id="l-rps" type="number" min={0.01} step="any" max={hard.max_rps} value={limits.max_rps} onChange={num("max_rps")} />
                  </Field>
                  <Field label="Max concurrency" htmlFor="l-conc">
                    <Input id="l-conc" type="number" min={1} max={hard.max_concurrency} value={limits.max_concurrency} onChange={num("max_concurrency")} />
                  </Field>
                  <Field label="Max duration (s)" htmlFor="l-dur">
                    <Input id="l-dur" type="number" min={1} max={hard.max_duration_s} value={limits.max_duration_s} onChange={num("max_duration_s")} />
                  </Field>
                  <Field label="Extra confirmation above (RPS)" htmlFor="l-confirm" help="Tests with a higher peak rate show an explicit disruption warning before starting.">
                    <Input id="l-confirm" type="number" min={0} step="any" value={limits.confirm_above_rps} onChange={num("confirm_above_rps")} />
                  </Field>
                </div>
                {message && (
                  <Alert variant={message.ok ? "good" : "critical"}>
                    {message.ok && <CheckCircle2 aria-hidden />} {message.text}
                  </Alert>
                )}
                <Button type="submit" disabled={saving}>
                  {saving ? <Loader2 className="animate-spin" /> : <Save />} Save limits
                </Button>
              </form>
            ) : null}
          </CardContent>
        </Card>

        {settings.data && (
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Server policy (read-only)</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
                <dt className="text-muted-foreground">Environment</dt>
                <dd>{settings.data.environment}</dd>
                <dt className="text-muted-foreground">Authentication</dt>
                <dd>{settings.data.auth_mode === "token" ? "API token required" : "Disabled (local only)"}</dd>
                <dt className="text-muted-foreground">Local development hosts</dt>
                <dd className="font-mono text-xs">{settings.data.local_target_hosts.join(", ")}</dd>
                <dt className="text-muted-foreground">Public internet targets</dt>
                <dd>{settings.data.allow_external_targets ? "Allowed for registered targets" : "Blocked"}</dd>
                <dt className="text-muted-foreground">Response body read limit</dt>
                <dd>{Math.round(settings.data.hard_limits.response_body_limit_bytes / 1024)} KB per response</dd>
                <dt className="text-muted-foreground">Max request body</dt>
                <dd>{Math.round(settings.data.hard_limits.max_request_body_bytes / 1024)} KB</dd>
              </dl>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
