"""Rate conversion, preset load profiles and plan construction.

The user's configured rate is always the *peak* of the profile: presets shape the traffic
below that peak and never exceed it, the user's own maximums or the operator's hard limits.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import PresetName, RateUnit, Stage


def to_rps(rate: float, unit: RateUnit) -> float:
    """Convert a configured rate to requests per second (e.g. 120 RPM -> 2.0 RPS)."""
    if rate < 0:
        raise ValueError("rate must be non-negative")
    return rate / 60.0 if unit == "rpm" else float(rate)


def from_rps(rps: float, unit: RateUnit) -> float:
    return rps * 60.0 if unit == "rpm" else rps


@dataclass(frozen=True)
class PresetDefaults:
    label: str
    description: str
    max_rps: float | None = None  # preset-specific ceiling (smoke)
    max_duration_s: int | None = None
    max_concurrency: int | None = None


PRESETS: dict[str, PresetDefaults] = {
    "custom": PresetDefaults("Custom", "Constant rate at the configured value."),
    "smoke": PresetDefaults(
        "Smoke",
        "Very low traffic (<= 1 RPS, <= 30 s) to verify the endpoint is reachable.",
        max_rps=1.0,
        max_duration_s=30,
        max_concurrency=2,
    ),
    "baseline": PresetDefaults(
        "Baseline", "Low, steady traffic at the configured rate to measure normal performance."
    ),
    "load": PresetDefaults("Load", "Ramp from 0 to the configured rate over 30% of the duration, then hold."),
    "spike": PresetDefaults(
        "Spike", "Hold 20% of the configured rate, spike to 100% for 10% of the duration, then recover."
    ),
    "stress": PresetDefaults("Stress", "Step up progressively (25/50/75/100%) to the configured maximum."),
}


def build_stages(preset: PresetName, peak_rps: float, duration_s: int) -> list[Stage]:
    d = float(duration_s)
    if preset in ("custom", "smoke", "baseline"):
        return [Stage(start_s=0, end_s=d, from_rps=peak_rps, to_rps=peak_rps)]
    if preset == "load":
        ramp = max(1.0, round(d * 0.3, 3))
        return [
            Stage(start_s=0, end_s=ramp, from_rps=0, to_rps=peak_rps),
            Stage(start_s=ramp, end_s=d, from_rps=peak_rps, to_rps=peak_rps),
        ]
    if preset == "spike":
        base = round(peak_rps * 0.2, 6)
        s0, s1 = round(d * 0.45, 3), round(d * 0.55, 3)
        return [
            Stage(start_s=0, end_s=s0, from_rps=base, to_rps=base),
            Stage(start_s=s0, end_s=s1, from_rps=peak_rps, to_rps=peak_rps),
            Stage(start_s=s1, end_s=d, from_rps=base, to_rps=base),
        ]
    if preset == "stress":
        stages = []
        for i, frac in enumerate((0.25, 0.5, 0.75, 1.0)):
            r = round(peak_rps * frac, 6)
            stages.append(
                Stage(start_s=round(d * i / 4, 3), end_s=round(d * (i + 1) / 4, 3), from_rps=r, to_rps=r)
            )
        return stages
    raise ValueError(f"unknown preset {preset}")


def rate_at(stages: list[Stage], t: float) -> float:
    """Target RPS at time ``t`` seconds (linear interpolation inside a stage)."""
    for s in stages:
        if s.start_s <= t < s.end_s:
            span = s.end_s - s.start_s
            if span <= 0:
                return s.to_rps
            return s.from_rps + (s.to_rps - s.from_rps) * (t - s.start_s) / span
    return 0.0


def cumulative(stages: list[Stage], t: float) -> float:
    """Expected number of requests scheduled in [0, t): the integral of the rate curve."""
    total = 0.0
    for s in stages:
        if t <= s.start_s:
            break
        end = min(t, s.end_s)
        span = s.end_s - s.start_s
        if span <= 0:
            continue
        r_end = s.from_rps + (s.to_rps - s.from_rps) * (end - s.start_s) / span
        total += (end - s.start_s) * (s.from_rps + r_end) / 2
    return total


def expected_requests(stages: list[Stage]) -> int:
    return int(round(sum((s.end_s - s.start_s) * (s.from_rps + s.to_rps) / 2 for s in stages)))


def peak_of(stages: list[Stage]) -> float:
    return max((max(s.from_rps, s.to_rps) for s in stages), default=0.0)
