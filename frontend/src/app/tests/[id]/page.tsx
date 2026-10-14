"use client";

import { use, useCallback } from "react";
import { LiveDashboard } from "@/components/live-dashboard";
import { ReportView } from "@/components/report-view";
import { ErrorState, LoadingState } from "@/components/states";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/use-async";

const ACTIVE = ["pending", "running", "paused"];

export default function TestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const report = useAsync(() => api.results(id), [id]);
  const { reload } = report;
  const onFinished = useCallback(() => reload(), [reload]);

  if (report.loading && !report.data) return <LoadingState label="Loading test…" />;
  if (report.error) return <ErrorState message={report.error} onRetry={report.reload} />;
  if (!report.data) return null;
  if (ACTIVE.includes(report.data.status)) return <LiveDashboard run={report.data} onFinished={onFinished} />;
  return <ReportView report={report.data} />;
}
