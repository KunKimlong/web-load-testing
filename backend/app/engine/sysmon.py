"""Load-generator self-monitoring (CPU, memory, event-loop lag).

These numbers let users tell *generator* saturation apart from *target* saturation: if the
event loop lags or the CPU is pegged, latency figures include client-side queueing.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import psutil

CPU_SATURATION_PCT = 85.0
LOOP_LAG_SATURATION_MS = 100.0


class GeneratorMonitor:
    def __init__(self, interval_s: float = 0.5):
        self.interval_s = interval_s
        self._proc = psutil.Process()
        self._proc.cpu_percent(None)
        self._cpu_count = psutil.cpu_count() or 1
        self.cpu_percent = 0.0
        self.rss_mb = 0.0
        self.loop_lag_ms = 0.0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="generator-monitor")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            t0 = time.monotonic()
            await asyncio.sleep(self.interval_s)
            lag = max(0.0, (time.monotonic() - t0 - self.interval_s) * 1000.0)
            self.loop_lag_ms = round(0.7 * self.loop_lag_ms + 0.3 * lag, 2)
            try:
                # normalised to a single core so 100% means one core fully busy (asyncio is single-threaded)
                self.cpu_percent = round(self._proc.cpu_percent(None), 1)
                self.rss_mb = round(self._proc.memory_info().rss / (1024 * 1024), 1)
            except psutil.Error:
                pass

    def stats(self, *, connections_limit: int, in_flight: int, recent_dropped: int) -> dict:
        reasons = []
        if self.cpu_percent >= CPU_SATURATION_PCT:
            reasons.append(f"Generator CPU at {self.cpu_percent:.0f}% of one core")
        if self.loop_lag_ms >= LOOP_LAG_SATURATION_MS:
            reasons.append(f"Event loop lag {self.loop_lag_ms:.0f} ms")
        if recent_dropped > 0:
            if in_flight >= connections_limit:
                reasons.append("Concurrency limit reached: target is slower than the requested rate")
            else:
                reasons.append("Scheduler fell behind the requested rate")
        return {
            "cpu_percent": self.cpu_percent,
            "rss_mb": self.rss_mb,
            "loop_lag_ms": self.loop_lag_ms,
            "open_connections_limit": connections_limit,
            "saturated": bool(reasons),
            "reasons": reasons,
        }
