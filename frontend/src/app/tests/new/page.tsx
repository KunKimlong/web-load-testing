"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/app-shell";
import { TestConfigForm } from "@/components/config/test-config-form";
import { ErrorState, LoadingState } from "@/components/states";
import { api } from "@/lib/api";
import { DEFAULT_CONFIG } from "@/lib/config-schema";
import { useAsync } from "@/lib/use-async";
import type { TestConfig } from "@/lib/types";

function NewTest() {
  const router = useRouter();
  const params = useSearchParams();
  const from = params.get("from");

  const data = useAsync(async () => {
    const [targets, settings, presets, source] = await Promise.all([
      api.targets(),
      api.settings(),
      api.presets(),
      from ? api.get(from) : Promise.resolve(null),
    ]);
    let initial: TestConfig | undefined;
    if (source) {
      // re-run: stored configs have secrets redacted, so clear them and require re-entry
      const c = source.config;
      const clean = (kv: { key: string; value: string }[]) =>
        kv.map((x) => ({ key: x.key, value: x.value === "[REDACTED]" ? "" : x.value }));
      initial = {
        ...DEFAULT_CONFIG,
        ...c,
        name: `${c.name} (re-run)`,
        query: clean(c.query),
        headers: clean(c.headers),
        auth: { type: c.auth.type, token: "", username: c.auth.username ?? "", password: "" },
      };
    } else if (targets.length) {
      initial = { ...DEFAULT_CONFIG, base_url: targets[0].origin };
    }
    return { targets, settings, presets, initial };
  }, [from]);

  if (data.loading && !data.data) return <LoadingState label="Loading targets and limits…" />;
  if (data.error) return <ErrorState message={data.error} onRetry={data.reload} />;
  if (!data.data) return null;
  return (
    <TestConfigForm
      key={from ?? "new"}
      initial={data.data.initial}
      targets={data.data.targets}
      limits={data.data.settings.user}
      presets={data.data.presets}
      onStarted={(id) => router.push(`/tests/${id}`)}
    />
  );
}

export default function NewTestPage() {
  return (
    <>
      <PageHeader
        title="New load test"
        description="Configure the request and load profile, validate it, then confirm to start."
      />
      <Suspense fallback={<LoadingState />}>
        <NewTest />
      </Suspense>
    </>
  );
}
