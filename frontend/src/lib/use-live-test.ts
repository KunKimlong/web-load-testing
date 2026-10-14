"use client";

import { useEffect, useReducer } from "react";
import { apiBase, authHeaders } from "./api";
import { streamSse } from "./sse";
import type { MetricsSnapshot, TestPlan, TestStatus, TimelinePoint } from "./types";

const MAX_POINTS = 3600;

export interface LiveState {
  connection: "connecting" | "live" | "reconnecting" | "closed";
  status: TestStatus | null;
  snapshot: MetricsSnapshot | null;
  timeline: TimelinePoint[];
  plan: TestPlan | null;
  done: boolean;
  error: string | null;
}

export type LiveAction =
  | { type: "init"; snapshot: MetricsSnapshot; timeline: TimelinePoint[]; plan: TestPlan }
  | { type: "snapshot"; snapshot: MetricsSnapshot }
  | { type: "status"; status: TestStatus }
  | { type: "done"; snapshot?: MetricsSnapshot }
  | { type: "connection"; connection: LiveState["connection"] }
  | { type: "error"; error: string };

export const initialLiveState: LiveState = {
  connection: "connecting",
  status: null,
  snapshot: null,
  timeline: [],
  plan: null,
  done: false,
  error: null,
};

export function liveReducer(state: LiveState, action: LiveAction): LiveState {
  switch (action.type) {
    case "init":
      return {
        ...state,
        connection: "live",
        error: null,
        snapshot: action.snapshot,
        status: action.snapshot.status,
        timeline: action.timeline.slice(-MAX_POINTS),
        plan: action.plan,
      };
    case "snapshot": {
      const p = action.snapshot.point;
      // only the new point is appended; earlier points keep identity so memoised charts stay cheap
      const timeline =
        p && (state.timeline.length === 0 || state.timeline[state.timeline.length - 1].t < p.t)
          ? [...state.timeline.slice(-(MAX_POINTS - 1)), p]
          : state.timeline;
      return { ...state, connection: "live", snapshot: action.snapshot, status: action.snapshot.status, timeline };
    }
    case "status":
      return { ...state, status: action.status, snapshot: state.snapshot && { ...state.snapshot, status: action.status } };
    case "done": {
      const snap = action.snapshot ?? state.snapshot;
      const p = action.snapshot?.point;
      const timeline =
        p && (state.timeline.length === 0 || state.timeline[state.timeline.length - 1].t < p.t)
          ? [...state.timeline, p]
          : state.timeline;
      return { ...state, done: true, connection: "closed", snapshot: snap, status: snap?.status ?? state.status, timeline };
    }
    case "connection":
      return { ...state, connection: action.connection };
    case "error":
      return { ...state, error: action.error };
  }
}

/** Subscribe to a running test's event stream; reconnects with backoff until the test is done. */
export function useLiveTest(testId: string | null, enabled = true): LiveState {
  const [state, dispatch] = useReducer(liveReducer, initialLiveState);

  useEffect(() => {
    if (!testId || !enabled) return;
    const ctrl = new AbortController();
    let finished = false;

    (async () => {
      let attempt = 0;
      while (!finished && !ctrl.signal.aborted) {
        try {
          await streamSse(
            `${apiBase()}/api/tests/${testId}/events`,
            authHeaders(),
            (e) => {
              const data = JSON.parse(e.data);
              if (e.event === "init") {
                attempt = 0;
                dispatch({ type: "init", snapshot: data.snapshot, timeline: data.timeline, plan: data.plan });
              } else if (e.event === "snapshot") dispatch({ type: "snapshot", snapshot: data });
              else if (e.event === "status") dispatch({ type: "status", status: data.status });
              else if (e.event === "done") {
                finished = true;
                dispatch({ type: "done", snapshot: data && "total" in data ? data : undefined });
              }
            },
            ctrl.signal,
          );
        } catch (err) {
          if (ctrl.signal.aborted) return;
          dispatch({ type: "error", error: err instanceof Error ? err.message : "Live connection lost." });
        }
        if (finished || ctrl.signal.aborted) break;
        attempt += 1;
        dispatch({ type: "connection", connection: "reconnecting" });
        await new Promise((r) => setTimeout(r, Math.min(1000 * 2 ** (attempt - 1), 10000)));
      }
    })();

    return () => {
      ctrl.abort();
    };
  }, [testId, enabled]);

  return state;
}
