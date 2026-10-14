import random

import pytest

from app.engine.metrics import EXACT_LIMIT, LatencyHistogram, MetricsCollector, percentile_exact
from app.engine.rates import (
    build_stages,
    cumulative,
    expected_requests,
    from_rps,
    peak_of,
    rate_at,
    to_rps,
)

# --- rate conversion -------------------------------------------------------------------


@pytest.mark.parametrize(
    "rate,unit,rps",
    [(120, "rpm", 2.0), (60, "rpm", 1.0), (30, "rpm", 0.5), (5, "rps", 5.0), (1, "rpm", 1 / 60)],
)
def test_to_rps(rate, unit, rps):
    assert to_rps(rate, unit) == pytest.approx(rps)


def test_roundtrip():
    assert from_rps(to_rps(90, "rpm"), "rpm") == pytest.approx(90)
    with pytest.raises(ValueError):
        to_rps(-1, "rps")


# --- presets / stages ------------------------------------------------------------------


@pytest.mark.parametrize("preset", ["custom", "smoke", "baseline", "load", "spike", "stress"])
def test_presets_never_exceed_peak(preset):
    stages = build_stages(preset, 40.0, 60)
    assert peak_of(stages) <= 40.0
    assert stages[0].start_s == 0 and stages[-1].end_s == 60
    for t in range(0, 600):
        assert rate_at(stages, t / 10) <= 40.0


def test_load_ramp_and_cumulative():
    stages = build_stages("load", 10.0, 100)  # ramp 0->10 over 30s, hold 70s
    assert rate_at(stages, 0) == 0
    assert rate_at(stages, 15) == pytest.approx(5.0)
    assert rate_at(stages, 50) == pytest.approx(10.0)
    assert cumulative(stages, 30) == pytest.approx(150.0)  # triangle area
    assert expected_requests(stages) == 150 + 700


def test_constant_cumulative():
    stages = build_stages("custom", 2.0, 10)
    assert cumulative(stages, 5) == pytest.approx(10.0)
    assert expected_requests(stages) == 20
    assert rate_at(stages, 10) == 0  # after the end


def test_spike_and_stress_shapes():
    spike = build_stages("spike", 50.0, 100)
    assert rate_at(spike, 10) == pytest.approx(10.0)
    assert rate_at(spike, 50) == pytest.approx(50.0)
    stress = build_stages("stress", 40.0, 80)
    assert [rate_at(stress, t) for t in (5, 25, 45, 65)] == pytest.approx([10, 20, 30, 40])


# --- metrics -----------------------------------------------------------------------------


def test_percentile_exact_matches_numpy_convention():
    vals = sorted([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
    assert percentile_exact(vals, 50) == pytest.approx(55)
    assert percentile_exact(vals, 90) == pytest.approx(91)
    assert percentile_exact(vals, 0) == 10
    assert percentile_exact(vals, 100) == 100
    assert percentile_exact([], 50) is None
    assert percentile_exact([7.0], 99) == 7.0


def test_histogram_exact_mode():
    h = LatencyHistogram()
    for v in range(1, 101):
        h.record(float(v))
    s = h.stats()
    assert s["min"] == 1 and s["max"] == 100
    assert s["avg"] == pytest.approx(50.5)
    assert s["p50"] == pytest.approx(50.5)
    assert s["p99"] == pytest.approx(99.01)


def test_histogram_bounded_mode_accuracy():
    rng = random.Random(42)
    values = [rng.lognormvariate(3, 0.8) for _ in range(EXACT_LIMIT + 5000)]
    h = LatencyHistogram()
    for v in values:
        h.record(v)
    assert h.exact is None  # switched to bounded memory mode
    ordered = sorted(values)
    for p in (50, 90, 95, 99):
        expected = percentile_exact(ordered, p)
        assert h.percentile(p) == pytest.approx(expected, rel=0.02)
    assert len(h.buckets) < 2000


def test_collector_counts_and_windows():
    m = MetricsCollector()
    for _ in range(4):
        m.on_send()
    m.on_response(200, 10.0, 100)
    m.on_response(201, 20.0, 50)
    m.on_response(500, 30.0, 10)
    m.on_error("timeout", "No response")
    m.on_dropped(2)
    assert m.success == 2 and m.failure == 2 and m.in_flight == 0
    assert m.error_rate == pytest.approx(50.0)
    assert m.status_codes == {"200": 1, "201": 1, "500": 1}
    point = m.close_window(1, 4.0)
    assert point["sent"] == 4 and point["completed"] == 4 and point["dropped"] == 2
    assert point["avg_ms"] == pytest.approx(20.0)
    assert m.actual_rps == 4.0
    errs = m.error_list()
    assert errs == [{"kind": "timeout", "count": 1, "samples": ["No response"]}]
    empty = m.close_window(2, 4.0)
    assert empty["sent"] == 0 and empty["avg_ms"] is None
    assert m.actual_rps == 2.0
