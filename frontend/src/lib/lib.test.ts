import { describe, expect, it } from "vitest";
import { DEFAULT_CONFIG, presetDefaults, validateConfig } from "./config-schema";
import { delta, fmtDuration, fmtMs, fmtRate, fromRps, statusClass, toRps } from "./format";
import { SseParser, type SseEvent } from "./sse";
import { initialLiveState, liveReducer } from "./use-live-test";
import type { MetricsSnapshot, PresetName, TestConfig } from "./types";

describe("rate conversion", () => {
  it("converts RPM to RPS", () => {
    expect(toRps(120, "rpm")).toBe(2);
    expect(toRps(30, "rpm")).toBe(0.5);
    expect(toRps(7, "rps")).toBe(7);
    expect(fromRps(2, "rpm")).toBe(120);
  });
  it("formats rates, durations and latency", () => {
    expect(fmtRate(0.5)).toBe("30 RPM");
    expect(fmtRate(12.5)).toBe("12.5 RPS");
    expect(fmtDuration(125)).toBe("2m 05s");
    expect(fmtMs(1530)).toBe("1.53 s");
    expect(fmtMs(12.34)).toBe("12.3 ms");
    expect(fmtMs(null)).toBe("—");
  });
  it("classifies status codes and computes deltas", () => {
    expect(statusClass("204")).toBe("2xx");
    expect(statusClass("503")).toBe("5xx");
    expect(delta(100, 150)).toBe(50);
    expect(delta(0, 5)).toBeNull();
  });
});

describe("SseParser", () => {
  it("parses events split across chunks and ignores keepalives", () => {
    const events: SseEvent[] = [];
    const p = new SseParser((e) => events.push(e));
    p.push("event: init\ndata: {\"a\"");
    p.push(":1}\n\n: keepalive\n\nevent: snapshot\r\ndata: 1\r\n\r\n");
    p.push("data: line1\ndata: line2\n\n");
    expect(events).toEqual([
      { event: "init", data: '{"a":1}' },
      { event: "snapshot", data: "1" },
      { event: "message", data: "line1\nline2" },
    ]);
  });
});

describe("config validation", () => {
  const limits = { max_rps: 50, max_concurrency: 20, max_duration_s: 300, confirm_above_rps: 25 };
  const cfg = (patch: Partial<TestConfig>): TestConfig => ({ ...DEFAULT_CONFIG, ...patch });

  it("accepts the default config", () => {
    expect(validateConfig(DEFAULT_CONFIG, limits)).toEqual({});
  });
  it("rejects bad URLs, bodies and auth", () => {
    expect(validateConfig(cfg({ base_url: "ftp://x" })).base_url).toBeDefined();
    expect(validateConfig(cfg({ base_url: "http://localhost:8080/api" })).base_url).toBeDefined();
    expect(validateConfig(cfg({ method: "GET", body: { type: "json", content: "{}" } })).body).toMatch(/GET/);
    expect(validateConfig(cfg({ method: "POST", body: { type: "json", content: "{nope" } })).body).toMatch(/JSON/);
    expect(validateConfig(cfg({ auth: { type: "bearer", token: "" } })).auth).toBeDefined();
    expect(validateConfig(cfg({ headers: [{ key: "Bad Header", value: "x" }] })).headers).toBeDefined();
  });
  it("enforces the user's limits, using RPM conversion", () => {
    expect(validateConfig(cfg({ rate: 3000, rate_unit: "rpm" }), limits).rate).toBeUndefined(); // 50 RPS
    expect(validateConfig(cfg({ rate: 3060, rate_unit: "rpm" }), limits).rate).toMatch(/maximum/);
    expect(validateConfig(cfg({ max_concurrency: 21 }), limits).max_concurrency).toBeDefined();
    expect(validateConfig(cfg({ duration_s: 301 }), limits).duration_s).toBeDefined();
  });
  it("preset defaults never exceed the user's limits", () => {
    const tiny = { max_rps: 3, max_concurrency: 2, max_duration_s: 20, confirm_above_rps: 1 };
    for (const p of ["smoke", "baseline", "load", "spike", "stress"] as PresetName[]) {
      const d = presetDefaults(p, tiny);
      expect(toRps(d.rate!, d.rate_unit!)).toBeLessThanOrEqual(tiny.max_rps);
      expect(d.max_concurrency!).toBeLessThanOrEqual(tiny.max_concurrency);
      expect(d.duration_s!).toBeLessThanOrEqual(tiny.max_duration_s);
    }
  });
});

describe("liveReducer", () => {
  const snap = (t: number, status: MetricsSnapshot["status"] = "running") =>
    ({ status, total: t, point: { t, sent: 1 } }) as unknown as MetricsSnapshot;

  it("appends only new points and keeps earlier identity", () => {
    let s = liveReducer(initialLiveState, { type: "init", snapshot: snap(0), timeline: [], plan: {} as never });
    s = liveReducer(s, { type: "snapshot", snapshot: snap(1) });
    const first = s.timeline[0];
    s = liveReducer(s, { type: "snapshot", snapshot: snap(2) });
    s = liveReducer(s, { type: "snapshot", snapshot: snap(2) }); // duplicate ignored
    expect(s.timeline.map((p) => p.t)).toEqual([1, 2]);
    expect(s.timeline[0]).toBe(first);
    expect(s.connection).toBe("live");
  });
  it("handles pause status and completion", () => {
    let s = liveReducer(initialLiveState, { type: "init", snapshot: snap(0), timeline: [], plan: {} as never });
    s = liveReducer(s, { type: "status", status: "paused" });
    expect(s.status).toBe("paused");
    s = liveReducer(s, { type: "done", snapshot: snap(3, "stopped") });
    expect(s.done).toBe(true);
    expect(s.status).toBe("stopped");
    expect(s.connection).toBe("closed");
  });
});
