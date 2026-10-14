"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Loader2, Play, RotateCcw, ShieldAlert, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  NativeSelect,
  Switch,
  Textarea,
} from "@/components/ui/primitives";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Field, KeyValueEditor, SecretInput, isSensitiveKey } from "./fields";
import { PlanSummary } from "./plan-summary";
import { ApiError, api } from "@/lib/api";
import { DEFAULT_CONFIG, presetDefaults, validateConfig, type FieldErrors } from "@/lib/config-schema";
import { fmtNumber, fmtRate, newRequestId, toRps } from "@/lib/format";
import type { HttpMethod, PresetInfo, PresetName, Target, TestConfig, TestPlan, UserSettings } from "@/lib/types";

const METHODS: HttpMethod[] = ["GET", "POST", "PUT", "PATCH", "DELETE"];

export function previewUrl(c: TestConfig): string {
  const base = c.base_url.trim().replace(/\/+$/, "");
  const path = c.path.trim() ? (c.path.trim().startsWith("/") ? c.path.trim() : `/${c.path.trim()}`) : "/";
  const qs = c.query
    .filter((q) => q.key.trim())
    .map((q) => `${encodeURIComponent(q.key)}=${isSensitiveKey(q.key) ? "••••" : encodeURIComponent(q.value)}`)
    .join("&");
  return `${base}${path}${qs ? `?${qs}` : ""}`;
}

export function TestConfigForm({
  initial,
  targets,
  limits,
  presets,
  onStarted,
}: {
  initial?: TestConfig;
  targets: Target[];
  limits: UserSettings;
  presets: PresetInfo[];
  onStarted: (id: string) => void;
}) {
  const [config, setConfig] = useState<TestConfig>(initial ?? DEFAULT_CONFIG);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [serverErrors, setServerErrors] = useState<string[]>([]);
  const [plan, setPlan] = useState<TestPlan | null>(null);
  const [validating, setValidating] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const requestId = useRef<string>(newRequestId());

  const set = <K extends keyof TestConfig>(key: K, value: TestConfig[K]) => {
    setConfig((c) => ({ ...c, [key]: value }));
    setPlan(null); // any change invalidates the reviewed plan
    setErrors((e) => ({ ...e, [key]: undefined }));
  };

  const url = useMemo(() => previewUrl(config), [config]);
  const approved = targets.some((t) => t.origin === config.base_url.trim().replace(/\/+$/, "").toLowerCase());
  const rps = toRps(config.rate || 0, config.rate_unit);
  const bodyAllowed = config.method !== "GET";

  async function validate(): Promise<TestPlan | null> {
    const fieldErrors = validateConfig(config, limits);
    setErrors(fieldErrors);
    setServerErrors([]);
    if (Object.values(fieldErrors).some(Boolean)) return null;
    setValidating(true);
    try {
      const res = await api.plan(config);
      if (!res.ok || !res.plan) {
        const fe: FieldErrors = {};
        const general: string[] = [];
        for (const e of res.errors) {
          if (e.field) fe[e.field] ??= e.message;
          else general.push(e.message);
        }
        setErrors(fe);
        setServerErrors(general);
        setPlan(null);
        return null;
      }
      setPlan(res.plan);
      return res.plan;
    } catch (e) {
      const err = e as ApiError;
      setServerErrors(err.issues.length ? err.issues.map((i) => i.message) : [err.message]);
      return null;
    } finally {
      setValidating(false);
    }
  }

  async function openConfirm() {
    const p = plan ?? (await validate());
    if (!p) return;
    requestId.current = newRequestId();
    setAcknowledged(false);
    setStartError(null);
    setConfirmOpen(true);
  }

  async function start() {
    if (starting) return; // guard against double submission; the backend is idempotent too
    setStarting(true);
    setStartError(null);
    try {
      const run = await api.start(config, requestId.current);
      setConfirmOpen(false);
      onStarted(run.id);
    } catch (e) {
      setStartError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  function applyPreset(p: PresetName) {
    setConfig((c) => ({ ...c, preset: p, ...presetDefaults(p, limits) }));
    setPlan(null);
    setErrors({});
  }

  function reset() {
    setConfig(DEFAULT_CONFIG);
    setPlan(null);
    setErrors({});
    setServerErrors([]);
  }

  const err = (k: string) => errors[k];
  const needsHighRateAck = plan ? plan.peak_rps >= limits.confirm_above_rps : false;

  return (
    <form
      className="grid gap-4 xl:grid-cols-[1fr_380px]"
      onSubmit={(e) => {
        e.preventDefault();
        void openConfirm();
      }}
      noValidate
    >
      <div className="flex min-w-0 flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Target</CardTitle>
            <CardDescription>
              Only registered targets can be tested.{" "}
              <Link className="text-primary underline-offset-2 hover:underline" href="/targets">
                Manage targets
              </Link>
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <Field label="Test name" htmlFor="name" error={err("name")} className="md:col-span-2">
              <Input id="name" value={config.name} onChange={(e) => set("name", e.target.value)} aria-invalid={!!err("name")} maxLength={120} />
            </Field>
            <Field label="Base URL" htmlFor="base_url" error={err("base_url")} help="Scheme, host and port of a registered target, e.g. http://localhost:8080.">
              <Input
                id="base_url"
                list="target-origins"
                value={config.base_url}
                spellCheck={false}
                onChange={(e) => set("base_url", e.target.value)}
                aria-invalid={!!err("base_url")}
                placeholder="http://localhost:8080"
              />
              <datalist id="target-origins">
                {targets.map((t) => (
                  <option key={t.id} value={t.origin}>
                    {t.name}
                  </option>
                ))}
              </datalist>
              <span className="flex items-center gap-1 text-xs">
                {approved ? (
                  <>
                    <ShieldCheck className="size-3.5 text-good" aria-hidden /> Registered target
                  </>
                ) : (
                  <>
                    <ShieldAlert className="size-3.5 text-warning" aria-hidden /> Not a registered target
                  </>
                )}
              </span>
            </Field>
            <Field label="Endpoint path" htmlFor="path" error={err("path")}>
              <Input id="path" value={config.path} spellCheck={false} onChange={(e) => set("path", e.target.value)} placeholder="/api/v1/patients" aria-invalid={!!err("path")} />
            </Field>
            <Field label="HTTP method" htmlFor="method">
              <NativeSelect id="method" value={config.method} onChange={(e) => set("method", e.target.value as HttpMethod)}>
                {METHODS.map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </NativeSelect>
            </Field>
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium">Final URL preview</span>
              <code className="break-all rounded-md border bg-muted px-3 py-2 text-xs" data-testid="url-preview">
                {config.method} {url}
              </code>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Request</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-5">
            <KeyValueEditor label="Query parameters" items={config.query} onChange={(v) => set("query", v)} error={err("query")} />
            <KeyValueEditor
              label="Headers"
              items={config.headers}
              onChange={(v) => set("headers", v)}
              keyPlaceholder="X-Header-Name"
              help="Values of sensitive headers (Authorization, Cookie, *token*, *key*) are masked here and redacted from stored reports."
              error={err("headers")}
            />
            <fieldset className="grid gap-3 md:grid-cols-[200px_1fr]">
              <legend className="mb-2 text-xs font-medium">Authentication</legend>
              <NativeSelect
                aria-label="Authentication type"
                value={config.auth.type}
                onChange={(e) => set("auth", { ...config.auth, type: e.target.value as TestConfig["auth"]["type"] })}
              >
                <option value="none">None</option>
                <option value="bearer">Bearer token</option>
                <option value="basic">Basic auth</option>
              </NativeSelect>
              {config.auth.type === "bearer" && (
                <SecretInput label="Bearer token" value={config.auth.token ?? ""} onChange={(v) => set("auth", { ...config.auth, token: v })} placeholder="token" />
              )}
              {config.auth.type === "basic" && (
                <div className="grid gap-2 sm:grid-cols-2">
                  <Input aria-label="Username" placeholder="username" autoComplete="off" value={config.auth.username ?? ""} onChange={(e) => set("auth", { ...config.auth, username: e.target.value })} />
                  <SecretInput label="Password" value={config.auth.password ?? ""} onChange={(v) => set("auth", { ...config.auth, password: v })} placeholder="password" />
                </div>
              )}
              {err("auth") && <p className="text-xs text-critical md:col-span-2" role="alert">{err("auth")}</p>}
              <p className="text-xs text-muted-foreground md:col-span-2">
                Credentials are sent only to the target, never logged, and redacted from history.
              </p>
            </fieldset>
            <Field label="Request body" htmlFor="body" error={err("body")} help="JSON or plain text for POST, PUT, PATCH and DELETE.">
              <div className="flex gap-2">
                <NativeSelect
                  aria-label="Body type"
                  className="w-36"
                  value={config.body.type}
                  disabled={!bodyAllowed}
                  onChange={(e) => set("body", { ...config.body, type: e.target.value as TestConfig["body"]["type"] })}
                >
                  <option value="none">No body</option>
                  <option value="json">JSON</option>
                  <option value="text">Plain text</option>
                </NativeSelect>
                {!bodyAllowed && <span className="self-center text-xs text-muted-foreground">GET requests have no body.</span>}
              </div>
              {bodyAllowed && config.body.type !== "none" && (
                <Textarea
                  id="body"
                  value={config.body.content}
                  spellCheck={false}
                  aria-invalid={!!err("body")}
                  placeholder={config.body.type === "json" ? '{\n  "name": "Jane"\n}' : "text payload"}
                  onChange={(e) => set("body", { ...config.body, content: e.target.value })}
                />
              )}
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Load profile</CardTitle>
            <CardDescription>
              Your limits: ≤ {fmtRate(limits.max_rps)}, ≤ {limits.max_concurrency} concurrent, ≤ {limits.max_duration_s}s. Presets
              never exceed them.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div role="radiogroup" aria-label="Test preset" className="grid grid-cols-2 gap-2 md:grid-cols-3">
              {presets.map((p) => (
                <button
                  type="button"
                  role="radio"
                  aria-checked={config.preset === p.name}
                  key={p.name}
                  onClick={() => applyPreset(p.name)}
                  className={`rounded-md border p-2.5 text-left text-xs transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                    config.preset === p.name ? "border-primary bg-primary/5" : ""
                  }`}
                >
                  <span className="block text-sm font-medium">{p.label}</span>
                  <span className="text-muted-foreground">{p.description}</span>
                </button>
              ))}
            </div>
            <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3">
              <Field
                label={config.preset === "custom" || config.preset === "baseline" || config.preset === "smoke" ? "Target rate" : "Peak rate"}
                htmlFor="rate"
                error={err("rate")}
                help="For ramp/spike/stress presets this is the peak; the profile stays at or below it."
              >
                <div className="flex gap-2">
                  <Input id="rate" type="number" min={0} step="any" value={Number.isFinite(config.rate) ? config.rate : ""} onChange={(e) => set("rate", e.target.valueAsNumber)} aria-invalid={!!err("rate")} />
                  <NativeSelect aria-label="Rate unit" className="w-24" value={config.rate_unit} onChange={(e) => set("rate_unit", e.target.value as TestConfig["rate_unit"])}>
                    <option value="rps">RPS</option>
                    <option value="rpm">RPM</option>
                  </NativeSelect>
                </div>
                <span className="text-xs text-muted-foreground" data-testid="rate-conversion">
                  = {fmtNumber(rps, 3)} RPS · {fmtNumber(rps * 60, 1)} RPM
                </span>
              </Field>
              <Field label="Duration (s)" htmlFor="duration" error={err("duration_s")}>
                <Input id="duration" type="number" min={1} step={1} value={Number.isFinite(config.duration_s) ? config.duration_s : ""} onChange={(e) => set("duration_s", e.target.valueAsNumber)} aria-invalid={!!err("duration_s")} />
              </Field>
              <Field label="Max concurrency" htmlFor="concurrency" error={err("max_concurrency")} help="Upper bound on simultaneous in-flight requests. When full, scheduled requests are dropped (not queued).">
                <Input id="concurrency" type="number" min={1} step={1} value={Number.isFinite(config.max_concurrency) ? config.max_concurrency : ""} onChange={(e) => set("max_concurrency", e.target.valueAsNumber)} aria-invalid={!!err("max_concurrency")} />
              </Field>
              <Field label="Request timeout (s)" htmlFor="timeout" error={err("timeout_s")}>
                <Input id="timeout" type="number" min={0.1} step="any" value={Number.isFinite(config.timeout_s) ? config.timeout_s : ""} onChange={(e) => set("timeout_s", e.target.valueAsNumber)} aria-invalid={!!err("timeout_s")} />
              </Field>
              <Field label="Retries" htmlFor="retries" error={err("retries")} help="Retries apply only to connection failures, max 3, with backoff. Off by default.">
                <Input id="retries" type="number" min={0} max={3} step={1} value={config.retries} onChange={(e) => set("retries", e.target.valueAsNumber || 0)} />
              </Field>
              <Field label="Redirects" htmlFor="redirects" error={err("max_redirects")} help="Off by default. When on, every hop must stay on a registered target.">
                <div className="flex h-9 items-center gap-2">
                  <Switch
                    id="redirects"
                    checked={config.follow_redirects}
                    onCheckedChange={(v) => setConfig((c) => ({ ...c, follow_redirects: v, max_redirects: v ? Math.max(1, c.max_redirects) : 0 }))}
                  />
                  {config.follow_redirects && (
                    <Input aria-label="Max redirects" type="number" min={1} max={5} className="w-20" value={config.max_redirects} onChange={(e) => set("max_redirects", e.target.valueAsNumber || 0)} />
                  )}
                </div>
              </Field>
            </div>
            {config.base_url.startsWith("https") && (
              <div className="flex items-center gap-2">
                <Switch id="verify_tls" checked={config.verify_tls} onCheckedChange={(v) => set("verify_tls", v)} />
                <Label htmlFor="verify_tls">Verify TLS certificates</Label>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="flex flex-col gap-4 xl:sticky xl:top-20 xl:self-start">
        <Card>
          <CardHeader>
            <CardTitle>Plan</CardTitle>
            <CardDescription>Validate to see exactly what will run.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {serverErrors.length > 0 && (
              <Alert variant="critical">
                <AlertTriangle aria-hidden />
                <ul className="space-y-1 text-xs">
                  {serverErrors.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </Alert>
            )}
            {Object.values(errors).some(Boolean) && serverErrors.length === 0 && (
              <Alert variant="critical">
                <AlertTriangle aria-hidden /> <span className="text-xs">Fix the highlighted fields.</span>
              </Alert>
            )}
            {plan ? (
              <>
                <Alert variant="good">
                  <CheckCircle2 aria-hidden /> <span className="text-xs">Configuration is valid.</span>
                </Alert>
                <PlanSummary plan={plan} />
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No plan yet.</p>
            )}
            <div className="flex flex-wrap gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => void validate()} disabled={validating}>
                {validating ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Validate configuration
              </Button>
              <Button type="submit" disabled={validating || starting}>
                <Play /> Start test…
              </Button>
              <Button type="button" variant="ghost" onClick={reset}>
                <RotateCcw /> Reset
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Dialog open={confirmOpen} onOpenChange={(o) => !starting && setConfirmOpen(o)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Start load test?</DialogTitle>
            <DialogDescription>Review the plan. You can stop the test at any time from the dashboard.</DialogDescription>
          </DialogHeader>
          {plan && <PlanSummary plan={plan} />}
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1 size-4 accent-[var(--primary)]"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            <span>
              I own <strong>{plan?.target_origin}</strong> or am authorized to load test it
              {needsHighRateAck ? ", and I understand this rate may disrupt the service" : ""}.
            </span>
          </label>
          {startError && (
            <Alert variant="critical">
              <AlertTriangle aria-hidden /> <span className="text-xs">{startError}</span>
            </Alert>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={starting}>
              Cancel
            </Button>
            <Button onClick={() => void start()} disabled={!acknowledged || starting}>
              {starting ? <Loader2 className="animate-spin" /> : <Play />} Start test
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </form>
  );
}
