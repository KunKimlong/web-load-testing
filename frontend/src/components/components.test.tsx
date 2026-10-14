import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TooltipProvider } from "@/components/ui/overlays";
import { TestConfigForm } from "@/components/config/test-config-form";
import { LiveView } from "@/components/live-dashboard";
import { initialLiveState, type LiveState } from "@/lib/use-live-test";
import type { MetricsSnapshot, PresetInfo, Target, TestPlan } from "@/lib/types";

const apiMock = vi.hoisted(() => ({ plan: vi.fn(), start: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: apiMock }));

const limits = { max_rps: 100, max_concurrency: 50, max_duration_s: 600, confirm_above_rps: 50 };
const targets: Target[] = [
  { id: "t1", name: "Mock", origin: "http://localhost:8080", host: "localhost", port: 8080, scheme: "http", notes: "", is_local: true, created_at: "" },
];
const presets: PresetInfo[] = [
  { name: "custom", label: "Custom", description: "Constant", max_rps: null, max_duration_s: null, max_concurrency: null },
  { name: "smoke", label: "Smoke", description: "Tiny", max_rps: 1, max_duration_s: 30, max_concurrency: 2 },
];
const plan: TestPlan = {
  preset: "custom", url_preview: "http://localhost:8080/api/v1/patients", method: "GET", target_origin: "http://localhost:8080",
  peak_rps: 5, average_rps: 5, configured_rate: 5, rate_unit: "rps", duration_s: 30, max_concurrency: 10, timeout_s: 10,
  expected_requests: 150, stages: [{ start_s: 0, end_s: 30, from_rps: 5, to_rps: 5 }],
  limits: { max_rps: 100, max_concurrency: 50, max_duration_s: 600, max_timeout_s: 60, max_request_body_bytes: 1, response_body_limit_bytes: 1 },
  warnings: [], requires_confirmation: true,
};

function renderForm(onStarted = vi.fn()) {
  render(
    <TooltipProvider>
      <TestConfigForm targets={targets} limits={limits} presets={presets} onStarted={onStarted} />
    </TooltipProvider>,
  );
  return onStarted;
}

describe("TestConfigForm", () => {
  beforeEach(() => {
    apiMock.plan.mockReset();
    apiMock.start.mockReset();
  });

  it("shows a live URL preview with masked secret query values", async () => {
    const user = userEvent.setup();
    renderForm();
    expect(screen.getByTestId("url-preview")).toHaveTextContent("GET http://localhost:8080/api/v1/patients");
    await user.click(screen.getAllByRole("button", { name: /add/i })[0]);
    await user.type(screen.getByLabelText("Query parameters 1 name"), "api_key");
    await user.type(screen.getByLabelText("Query parameters 1 value"), "hunter2");
    expect(screen.getByTestId("url-preview")).toHaveTextContent("?api_key=••••");
    expect(screen.getByTestId("url-preview")).not.toHaveTextContent("hunter2");
    expect(screen.getByText("Registered target")).toBeInTheDocument();
  });

  it("converts RPM to RPS in the hint", async () => {
    const user = userEvent.setup();
    renderForm();
    const rate = screen.getByLabelText("Target rate", { selector: "input" });
    await user.clear(rate);
    await user.type(rate, "120");
    await user.selectOptions(screen.getByLabelText("Rate unit"), "rpm");
    expect(screen.getByTestId("rate-conversion")).toHaveTextContent("= 2 RPS · 120 RPM");
  });

  it("blocks invalid input on the client before calling the API", async () => {
    const user = userEvent.setup();
    renderForm();
    const rate = screen.getByLabelText("Target rate", { selector: "input" });
    await user.clear(rate);
    await user.type(rate, "500");
    await user.click(screen.getByRole("button", { name: /validate configuration/i }));
    expect(await screen.findByText(/exceeds your maximum/i)).toBeInTheDocument();
    expect(apiMock.plan).not.toHaveBeenCalled();
  });

  it("shows server validation errors", async () => {
    apiMock.plan.mockResolvedValue({ ok: false, plan: null, errors: [{ code: "target_not_approved", message: "Not registered", field: "base_url" }] });
    const user = userEvent.setup();
    renderForm();
    await user.click(screen.getByRole("button", { name: /validate configuration/i }));
    expect(await screen.findByText("Not registered")).toBeInTheDocument();
  });

  it("validates, requires confirmation, and starts exactly once", async () => {
    apiMock.plan.mockResolvedValue({ ok: true, plan, errors: [] });
    let resolveStart: (v: unknown) => void = () => {};
    apiMock.start.mockImplementation(() => new Promise((r) => (resolveStart = r)));
    const user = userEvent.setup();
    const onStarted = renderForm();

    await user.click(screen.getByRole("button", { name: /start test…/i }));
    const dialog = await screen.findByRole("dialog");
    const startBtn = screen.getByRole("button", { name: /^start test$/i });
    expect(startBtn).toBeDisabled(); // must acknowledge authorization first
    expect(dialog).toHaveTextContent("≈ 150");
    await user.click(screen.getByRole("checkbox"));
    await user.click(startBtn);
    await user.click(startBtn); // double click while pending
    expect(apiMock.start).toHaveBeenCalledTimes(1);
    resolveStart({ id: "run123" });
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith("run123"));
  });
});

const snapshot: MetricsSnapshot = {
  test_id: "x", status: "running", elapsed_s: 10, remaining_s: 20, duration_s: 30, progress: 0.33,
  target_rps: 5, configured_peak_rps: 5, actual_rps: 4.67, total: 48, success: 45, failure: 3, cancelled: 0,
  in_flight: 2, dropped: 1, retries: 0, error_rate: 6.25, bytes_received: 2048,
  latency: { avg: 12, min: 3, max: 90, p50: 10, p90: 20, p95: 30, p99: 80 },
  status_codes: { "200": 45, "503": 3 }, errors: [],
  generator: { cpu_percent: 95, rss_mb: 80, loop_lag_ms: 3, open_connections_limit: 10, saturated: true, reasons: ["Generator CPU at 95% of one core"] },
  eta: "~20s remaining", point: null,
};
const run = { id: "x", name: "Live run", method: "GET", target_origin: "http://localhost:8080", path: "/health" };
const live = (patch: Partial<LiveState>): LiveState => ({ ...initialLiveState, ...patch });
const noop = () => {};

function renderLive(state: LiveState, handlers: Partial<{ onStop: () => void; onPause: () => void; onResume: () => void }> = {}) {
  render(
    <TooltipProvider>
      <LiveView run={run} live={state} busy={false} actionError={null} onStop={handlers.onStop ?? noop} onPause={handlers.onPause ?? noop} onResume={handlers.onResume ?? noop} />
    </TooltipProvider>,
  );
}

describe("LiveView dashboard states", () => {
  it("shows a loading state while connecting", () => {
    renderLive(live({ connection: "connecting" }));
    expect(screen.getByText(/connecting to live metrics/i)).toBeInTheDocument();
  });

  it("renders live metrics, saturation warning and a working Stop button", async () => {
    const onStop = vi.fn();
    const user = userEvent.setup();
    renderLive(live({ connection: "live", status: "running", snapshot }), { onStop });
    expect(screen.getByText("48")).toBeInTheDocument();
    expect(screen.getByText("6.25%")).toBeInTheDocument();
    expect(screen.getByText("~20s remaining")).toBeInTheDocument();
    expect(screen.getByText(/saturation detected/i)).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /stop test now/i }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("offers Resume when paused and shows reconnecting state", async () => {
    const onResume = vi.fn();
    const user = userEvent.setup();
    renderLive(live({ connection: "reconnecting", status: "paused", snapshot: { ...snapshot, status: "paused" } }), { onResume });
    expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /resume/i }));
    expect(onResume).toHaveBeenCalledOnce();
  });

  it("hides controls once the test is done", () => {
    renderLive(live({ connection: "closed", status: "stopped", done: true, snapshot: { ...snapshot, status: "stopped" } }));
    expect(screen.queryByRole("button", { name: /stop test now/i })).not.toBeInTheDocument();
    expect(screen.getAllByText("Stopped").length).toBeGreaterThan(0);
  });
});
