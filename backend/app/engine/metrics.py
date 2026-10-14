"""Metrics collection and aggregation for a single load test.

Latency percentiles are exact (linear interpolation) while the sample count is small and fall
back to a log-bucketed histogram (~1% relative error) beyond ``EXACT_LIMIT`` samples, so memory
stays bounded no matter how long a test runs.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field

EXACT_LIMIT = 20_000
MAX_ERROR_SAMPLES = 5


def percentile_exact(sorted_values: list[float], p: float) -> float | None:
    """Percentile with linear interpolation between closest ranks (same as numpy's default)."""
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return sorted_values[0]
    k = (n - 1) * (p / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


class LatencyHistogram:
    GROWTH = 1.01
    _LOG_G = math.log(GROWTH)
    MIN_MS = 0.001

    def __init__(self) -> None:
        self.buckets: Counter[int] = Counter()
        self.exact: list[float] | None = []
        self.count = 0
        self.total = 0.0
        self.min: float | None = None
        self.max: float | None = None

    def _index(self, ms: float) -> int:
        return int(math.floor(math.log(max(ms, self.MIN_MS) / self.MIN_MS) / self._LOG_G))

    def record(self, ms: float) -> None:
        self.count += 1
        self.total += ms
        self.min = ms if self.min is None else min(self.min, ms)
        self.max = ms if self.max is None else max(self.max, ms)
        self.buckets[self._index(ms)] += 1
        if self.exact is not None:
            if len(self.exact) < EXACT_LIMIT:
                self.exact.append(ms)
            else:
                self.exact = None  # switch to histogram mode permanently

    def percentile(self, p: float) -> float | None:
        if self.count == 0:
            return None
        if self.exact is not None:
            return percentile_exact(sorted(self.exact), p)
        rank = max(1, math.ceil(self.count * p / 100.0))
        seen = 0
        for idx in sorted(self.buckets):
            seen += self.buckets[idx]
            if seen >= rank:
                lo = self.MIN_MS * self.GROWTH**idx
                mid = lo * math.sqrt(self.GROWTH)
                return min(max(mid, self.min or mid), self.max or mid)
        return self.max

    @property
    def avg(self) -> float | None:
        return self.total / self.count if self.count else None

    def stats(self) -> dict[str, float | None]:
        r = lambda v: None if v is None else round(v, 3)  # noqa: E731
        return {
            "avg": r(self.avg),
            "min": r(self.min),
            "max": r(self.max),
            "p50": r(self.percentile(50)),
            "p90": r(self.percentile(90)),
            "p95": r(self.percentile(95)),
            "p99": r(self.percentile(99)),
        }


@dataclass
class _Window:
    sent: int = 0
    completed: int = 0
    success: int = 0
    failure: int = 0
    dropped: int = 0
    latencies: list[float] = field(default_factory=list)


class MetricsCollector:
    def __init__(self) -> None:
        self.sent = 0
        self.success = 0
        self.failure = 0
        self.cancelled = 0
        self.dropped = 0
        self.retries = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.bytes_received = 0
        self.status_codes: Counter[str] = Counter()
        self.errors: Counter[str] = Counter()
        self.error_samples: dict[str, list[str]] = {}
        self.latency = LatencyHistogram()
        self.timeline: list[dict] = []
        self._window = _Window()
        self._recent_sent: deque[int] = deque(maxlen=3)

    # --- recording -------------------------------------------------------------------
    def on_send(self) -> None:
        self.sent += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self._window.sent += 1

    def on_dropped(self, n: int = 1) -> None:
        self.dropped += n
        self._window.dropped += n

    def on_retry(self) -> None:
        self.retries += 1

    def on_response(self, status: int, latency_ms: float, nbytes: int) -> None:
        self.in_flight -= 1
        self.bytes_received += nbytes
        self.status_codes[str(status)] += 1
        self.latency.record(latency_ms)
        self._window.completed += 1
        self._window.latencies.append(latency_ms)
        if 200 <= status < 400:
            self.success += 1
            self._window.success += 1
        else:
            self.failure += 1
            self._window.failure += 1

    def on_error(self, kind: str, message: str, latency_ms: float | None = None) -> None:
        self.in_flight -= 1
        self.failure += 1
        self.errors[kind] += 1
        self._window.completed += 1
        self._window.failure += 1
        samples = self.error_samples.setdefault(kind, [])
        if len(samples) < MAX_ERROR_SAMPLES and message not in samples:
            samples.append(message[:500])

    def on_cancelled(self) -> None:
        self.in_flight -= 1
        self.cancelled += 1

    # --- aggregation -------------------------------------------------------------------
    @property
    def completed(self) -> int:
        return self.success + self.failure

    @property
    def error_rate(self) -> float:
        return round(100.0 * self.failure / self.completed, 3) if self.completed else 0.0

    def close_window(self, t: int, target_rps: float) -> dict:
        w = self._window
        lat = sorted(w.latencies)
        point = {
            "t": t,
            "target_rps": round(target_rps, 3),
            "sent": w.sent,
            "completed": w.completed,
            "success": w.success,
            "failure": w.failure,
            "avg_ms": round(sum(lat) / len(lat), 3) if lat else None,
            "p95_ms": None if not lat else round(percentile_exact(lat, 95) or 0.0, 3),
            "in_flight": self.in_flight,
            "dropped": w.dropped,
        }
        self.timeline.append(point)
        self._recent_sent.append(w.sent)
        self._window = _Window()
        return point

    @property
    def actual_rps(self) -> float:
        if not self._recent_sent:
            return 0.0
        return round(sum(self._recent_sent) / len(self._recent_sent), 3)

    def error_list(self) -> list[dict]:
        return [
            {"kind": k, "count": c, "samples": self.error_samples.get(k, [])}
            for k, c in self.errors.most_common()
        ]

    def totals(self) -> dict:
        return {
            "total": self.sent,
            "success": self.success,
            "failure": self.failure,
            "cancelled": self.cancelled,
            "in_flight": self.in_flight,
            "max_in_flight": self.max_in_flight,
            "dropped": self.dropped,
            "retries": self.retries,
            "error_rate": self.error_rate,
            "bytes_received": self.bytes_received,
            "latency": self.latency.stats(),
            "status_codes": dict(sorted(self.status_codes.items())),
            "errors": self.error_list(),
        }
