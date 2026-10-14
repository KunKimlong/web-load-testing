"""Engine integration tests against the local mock server (127.0.0.1 only)."""

import asyncio
import json
import time

import httpx
import pytest

from app.engine.rates import build_stages
from app.engine.runner import LoadRunner, RequestSpec
from app.safety.network import build_guarded_client
from app.safety.url_policy import DestinationPolicy
from tests.conftest import _free_port, mock_stats


def make_runner(
    base: str,
    path: str = "/health",
    *,
    rps: float = 10,
    duration: float = 1.0,
    concurrency: int = 10,
    timeout: float = 2.0,
    method: str = "GET",
    headers: dict | None = None,
    content: bytes | None = None,
    approved: set[str] | None = None,
    **spec_kw,
) -> LoadRunner:
    policy = DestinationPolicy(
        frozenset({"127.0.0.1", "localhost"}),
        allow_external=False,
        approved_origins=frozenset(approved or {base}),
    )
    client = build_guarded_client(policy, pinned=None, max_connections=concurrency, timeout_s=timeout)
    spec = RequestSpec(
        method=method,
        url=httpx.URL(base + path),
        headers=headers or {},
        content=content,
        timeout_s=timeout,
        **spec_kw,
    )
    return LoadRunner(
        spec=spec,
        stages=build_stages("custom", rps, max(1, int(duration))),
        duration_s=duration,
        max_concurrency=concurrency,
        client=client,
        policy=policy,
    )


async def run(runner: LoadRunner) -> str:
    try:
        return await runner.run()
    finally:
        await runner.client.aclose()


async def test_rate_is_respected(reset_mock):
    r = make_runner(reset_mock, rps=20, duration=2)
    reason = await run(r)
    assert reason == "completed"
    m = r.metrics
    assert 39 <= m.sent <= 41, m.sent  # 20 RPS * 2 s = 40 (first request at t=0)
    assert m.success == m.sent and m.failure == 0
    assert mock_stats(reset_mock)["requests"] == m.sent
    assert m.latency.count == m.sent


async def test_rpm_rate(reset_mock):
    r = make_runner(reset_mock, rps=120 / 60, duration=2)  # 120 RPM
    await run(r)
    assert r.metrics.sent == 4  # 2 RPS * 2 s, sent at t = 0, 0.5, 1.0, 1.5


async def test_concurrency_limit_and_backpressure(reset_mock):
    r = make_runner(reset_mock, "/slow?ms=400", rps=50, duration=1, concurrency=5)
    await run(r)
    stats = mock_stats(reset_mock)
    assert stats["max_in_flight"] <= 5
    assert r.metrics.max_in_flight <= 5
    assert r.metrics.dropped > 0, "excess scheduled requests must be dropped, not queued"
    assert r.metrics.sent + r.metrics.dropped == pytest.approx(50, abs=3)


async def test_timeouts_are_counted(reset_mock):
    r = make_runner(reset_mock, "/slow?ms=3000", rps=5, duration=1, timeout=0.3)
    started = time.monotonic()
    await run(r)
    assert time.monotonic() - started < 3
    assert r.metrics.errors["timeout"] == r.metrics.sent > 0
    assert r.metrics.success == 0


async def test_connection_errors_and_bounded_retries():
    base = f"http://127.0.0.1:{_free_port()}"  # nothing listening
    r = make_runner(base, rps=3, duration=1, retries=2)
    await run(r)
    assert r.metrics.errors["connect_error"] == r.metrics.sent > 0
    assert r.metrics.retries == 2 * r.metrics.sent


async def test_status_codes_and_failures(reset_mock):
    r = make_runner(reset_mock, "/status/503", rps=5, duration=1)
    await run(r)
    assert r.metrics.status_codes == {"503": r.metrics.sent}
    assert r.metrics.failure == r.metrics.sent
    assert r.metrics.error_rate == 100.0


async def test_methods_headers_query_and_json_body(reset_mock):
    seen: list[httpx.Request] = []
    body = json.dumps({"name": "test", "n": 1}).encode()
    r = make_runner(
        reset_mock,
        "/echo?ward=A&page=2",
        rps=3,
        duration=1,
        method="PATCH",
        headers={
            "X-Custom": "abc",
            "Content-Type": "application/json",
            "Authorization": "Bearer s3cret-token",
        },
        content=body,
    )

    async def hook(request: httpx.Request):
        seen.append(request)

    r.client.event_hooks["request"].append(hook)
    await run(r)
    assert seen and r.metrics.success == len(seen)
    req = seen[0]
    assert req.method == "PATCH"
    assert req.url.params["ward"] == "A" and req.url.params["page"] == "2"
    assert req.headers["x-custom"] == "abc"
    assert req.headers["content-type"] == "application/json"
    assert req.content == body
    # and the server really received them
    async with httpx.AsyncClient() as c:
        echo = (
            await c.request("PATCH", reset_mock + "/echo?ward=A", headers={"X-Custom": "abc"}, content=body)
        ).json()
    assert echo["method"] == "PATCH" and json.loads(echo["body"]) == {"name": "test", "n": 1}
    assert mock_stats(reset_mock)["methods"].get("PATCH", 0) >= len(seen)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
async def test_all_methods(reset_mock, method):
    r = make_runner(reset_mock, "/echo", rps=2, duration=1, method=method)
    await run(r)
    assert r.metrics.success >= 1
    assert mock_stats(reset_mock)["methods"] == {method: r.metrics.sent}


async def test_stop_cancels_in_flight_quickly(reset_mock):
    r = make_runner(reset_mock, "/slow?ms=10000", rps=10, duration=30, timeout=20)
    task = asyncio.create_task(run(r))
    await asyncio.sleep(0.6)
    assert r.in_flight > 0
    t0 = time.monotonic()
    r.stop()
    reason = await asyncio.wait_for(task, timeout=3)
    assert time.monotonic() - t0 < 1.5
    assert reason == "stopped"
    assert r.in_flight == 0 and r.metrics.in_flight == 0
    assert r.metrics.cancelled > 0
    sent_after_stop = r.metrics.sent
    await asyncio.sleep(0.3)
    assert r.metrics.sent == sent_after_stop  # nothing further scheduled


async def test_pause_and_resume(reset_mock):
    r = make_runner(reset_mock, rps=20, duration=2)
    task = asyncio.create_task(run(r))
    await asyncio.sleep(0.5)
    assert r.pause()
    sent_at_pause = r.metrics.sent
    elapsed_at_pause = r.elapsed
    await asyncio.sleep(0.6)
    assert r.metrics.sent == sent_at_pause
    assert r.elapsed == pytest.approx(elapsed_at_pause, abs=0.01)
    assert r.current_target_rps == 0
    assert r.resume()
    await asyncio.wait_for(task, timeout=5)
    assert 36 <= r.metrics.sent <= 42  # full planned volume still delivered


async def test_redirects_not_followed_by_default(reset_mock):
    r = make_runner(reset_mock, "/redirect?to=/health", rps=3, duration=1)
    await run(r)
    assert set(r.metrics.status_codes) == {"302"}


async def test_redirect_followed_to_approved_origin(reset_mock):
    r = make_runner(
        reset_mock, "/redirect?to=/health", rps=3, duration=1, follow_redirects=True, max_redirects=2
    )
    await run(r)
    assert set(r.metrics.status_codes) == {"200"}


async def test_redirect_to_unapproved_destination_blocked(reset_mock):
    port = reset_mock.rsplit(":", 1)[1]
    other = f"http://localhost:{port}/health"  # same server, different (unregistered) origin
    r = make_runner(
        reset_mock, f"/redirect?to={other}", rps=3, duration=1, follow_redirects=True, max_redirects=3
    )
    await run(r)
    assert r.metrics.errors["redirect_blocked"] == r.metrics.sent > 0


async def test_redirect_to_metadata_blocked(reset_mock):
    r = make_runner(
        reset_mock,
        "/redirect?to=http://169.254.169.254/latest",
        rps=2,
        duration=1,
        follow_redirects=True,
        max_redirects=3,
        approved={reset_mock, "http://169.254.169.254"},
    )
    await run(r)
    assert r.metrics.errors["blocked_destination"] == r.metrics.sent > 0


async def test_response_body_limit(reset_mock):
    r = make_runner(reset_mock, "/large?kb=2048", rps=2, duration=1, response_body_limit=32 * 1024)
    await run(r)
    assert r.metrics.success >= 1
    assert r.metrics.bytes_received <= r.metrics.sent * (32 * 1024 + 65536)
