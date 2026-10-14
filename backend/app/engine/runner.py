"""Open-model HTTP load generator with bounded concurrency.

Scheduling: the number of requests that *should* have been sent by active time ``t`` is the
integral of the rate curve. Every tick the scheduler dispatches the difference. A request is
only launched if a concurrency slot is free; otherwise the slot is counted as *dropped*
(backpressure) instead of being queued, so the number of tasks and memory are always bounded
by ``max_concurrency``. Large scheduling lag (e.g. a stalled event loop) is also counted as
dropped rather than released as a burst.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from ..safety.network import BLOCKED_PREFIX
from ..safety.url_policy import DestinationPolicy, PolicyError, normalize_base_url
from ..schemas import Stage
from .metrics import MetricsCollector
from .rates import cumulative, rate_at

log = logging.getLogger(__name__)

REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_CATCHUP_S = 1.0


class RedirectBlockedError(Exception):
    pass


@dataclass
class RequestSpec:
    method: str
    url: httpx.URL
    headers: dict[str, str]
    content: bytes | None
    timeout_s: float
    follow_redirects: bool = False
    max_redirects: int = 0
    retries: int = 0
    response_body_limit: int = 64 * 1024
    secrets: list[str] = field(default_factory=list)


class LoadRunner:
    def __init__(
        self,
        *,
        spec: RequestSpec,
        stages: list[Stage],
        duration_s: float,
        max_concurrency: int,
        client: httpx.AsyncClient,
        policy: DestinationPolicy,
        metrics: MetricsCollector | None = None,
        redact: Callable[[str], str] = lambda s: s,
        max_pause_s: float = 600,
    ):
        self.spec = spec
        self.stages = stages
        self.duration_s = float(duration_s)
        self.max_concurrency = max_concurrency
        self.client = client
        self.policy = policy
        self.metrics = metrics or MetricsCollector()
        self.redact = redact
        self.max_pause_s = max_pause_s

        self._tasks: set[asyncio.Task] = set()
        self._active = 0
        self._stop = asyncio.Event()
        self._resumed = asyncio.Event()
        self._resumed.set()
        self._start: float | None = None
        self._paused_total = 0.0
        self._paused_at: float | None = None
        self._scheduled = 0
        self._ended_at: float | None = None
        self.stop_reason: str | None = None
        self.finished = False

    # --- control ---------------------------------------------------------------------
    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def stop(self, reason: str = "stopped") -> None:
        if self.stop_reason is None:
            self.stop_reason = reason
        self._stop.set()
        self._resumed.set()

    def pause(self) -> bool:
        if self.finished or self.paused or self._stop.is_set():
            return False
        self._paused_at = time.monotonic()
        self._resumed.clear()
        return True

    def resume(self) -> bool:
        if not self.paused:
            return False
        assert self._paused_at is not None
        self._paused_total += time.monotonic() - self._paused_at
        self._paused_at = None
        self._resumed.set()
        return True

    @property
    def elapsed(self) -> float:
        """Active (non-paused) time since start, capped at the configured duration."""
        if self._start is None:
            return 0.0
        now = self._ended_at or self._paused_at or time.monotonic()
        return max(0.0, min(self.duration_s, now - self._start - self._paused_total))

    @property
    def current_target_rps(self) -> float:
        if self._start is None or self.paused or self.finished:
            return 0.0
        return rate_at(self.stages, self.elapsed)

    @property
    def in_flight(self) -> int:
        return self._active

    # --- main loop ---------------------------------------------------------------------
    async def run(self) -> str:
        self._start = time.monotonic()
        try:
            await self._schedule_loop()
        finally:
            if self._paused_at is not None:
                self.resume()
            self._ended_at = time.monotonic()
            await self._cancel_outstanding()
            self.finished = True
        return self.stop_reason or "completed"

    async def _schedule_loop(self) -> None:
        while not self._stop.is_set():
            if self.paused:
                try:
                    await asyncio.wait_for(self._resumed.wait(), timeout=self.max_pause_s)
                except TimeoutError:
                    self.stop("pause_timeout")
                continue

            now = time.monotonic() - self._start - self._paused_total  # type: ignore[operator]
            if now >= self.duration_s:
                self.stop_reason = self.stop_reason or "completed"
                # let in-flight requests finish (they are bounded by the request timeout)
                await self._drain()
                return

            due_total = cumulative(self.stages, now)
            lag_floor = cumulative(self.stages, max(0.0, now - MAX_CATCHUP_S))
            if self._scheduled < int(lag_floor):
                missed = int(lag_floor) - self._scheduled
                self.metrics.on_dropped(missed)
                self._scheduled += missed

            rate = rate_at(self.stages, now)
            # request k (0-based) is due once the integral reaches k, so the first one goes out at t=0
            while self._scheduled <= due_total and (due_total > 0 or rate > 0) and not self._stop.is_set():
                self._scheduled += 1
                if self._active >= self.max_concurrency:
                    self.metrics.on_dropped()
                    continue
                self._launch()

            wait = 0.05 if rate <= 0 else (self._scheduled - due_total) / rate
            wait = min(max(wait, 0.001), 0.05, max(0.001, self.duration_s - now))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=wait)

    def _launch(self) -> None:
        self._active += 1
        self.metrics.on_send()
        task = asyncio.create_task(self._execute())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drain(self) -> None:
        if not self._tasks:
            return
        grace = self.spec.timeout_s + 1.0
        done_waiter = asyncio.gather(*list(self._tasks), return_exceptions=True)
        stop_waiter = asyncio.ensure_future(self._stop.wait())
        try:
            await asyncio.wait({done_waiter, stop_waiter}, timeout=grace, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop_waiter.cancel()

    async def _cancel_outstanding(self) -> None:
        tasks = list(self._tasks)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # --- single request ----------------------------------------------------------------
    async def _execute(self) -> None:
        t0 = time.perf_counter()
        try:
            try:
                async with asyncio.timeout(self.spec.timeout_s):
                    status, nbytes = await self._send_with_retries()
            except TimeoutError:
                self.metrics.on_error("timeout", f"No complete response within {self.spec.timeout_s:g}s")
                return
            self.metrics.on_response(status, (time.perf_counter() - t0) * 1000.0, nbytes)
        except asyncio.CancelledError:
            self.metrics.on_cancelled()
            raise
        except httpx.TimeoutException as exc:
            self.metrics.on_error("timeout", self._msg(exc, "Request timed out"))
        except httpx.ConnectError as exc:
            text = str(exc)
            if text.startswith(BLOCKED_PREFIX):
                self.metrics.on_error("blocked_destination", self._msg(exc, "Blocked by safety policy"))
            else:
                self.metrics.on_error("connect_error", self._msg(exc, "Connection failed"))
        except RedirectBlockedError as exc:
            self.metrics.on_error("redirect_blocked", self._msg(exc, "Redirect blocked"))
        except (httpx.RemoteProtocolError, httpx.LocalProtocolError) as exc:
            self.metrics.on_error("protocol_error", self._msg(exc, "HTTP protocol error"))
        except (httpx.ReadError, httpx.WriteError, httpx.NetworkError) as exc:
            self.metrics.on_error("network_error", self._msg(exc, "Network error"))
        except httpx.HTTPError as exc:
            self.metrics.on_error("http_error", self._msg(exc, "HTTP error"))
        except Exception as exc:  # never let one request kill the run
            log.exception("unexpected error in request task")
            self.metrics.on_error("internal_error", self._msg(exc, "Internal error"))
        finally:
            self._active -= 1

    def _msg(self, exc: BaseException, fallback: str) -> str:
        text = str(exc).strip() or fallback
        return self.redact(f"{type(exc).__name__}: {text}")

    async def _send_with_retries(self) -> tuple[int, int]:
        attempt = 0
        while True:
            try:
                return await self._send_following_redirects()
            except httpx.ConnectError as exc:
                if str(exc).startswith(BLOCKED_PREFIX) or attempt >= self.spec.retries:
                    raise
                attempt += 1
                self.metrics.on_retry()
                await asyncio.sleep(min(0.05 * 2**attempt, 0.5))

    async def _send_following_redirects(self) -> tuple[int, int]:
        spec = self.spec
        method, url, content = spec.method, spec.url, spec.content
        headers = dict(spec.headers)
        hops = 0
        while True:
            request = self.client.build_request(method, url, headers=headers, content=content)
            response = await self.client.send(request, stream=True)
            try:
                location = response.headers.get("location")
                if (
                    spec.follow_redirects
                    and response.status_code in REDIRECT_CODES
                    and location
                    and hops < spec.max_redirects
                ):
                    next_url = response.url.join(location)
                    self._check_redirect(next_url)
                    if (
                        next_url.scheme != url.scheme
                        or next_url.host != url.host
                        or next_url.port != url.port
                    ):
                        headers.pop("Authorization", None)  # never forward credentials cross-origin
                    if response.status_code == 303 or (
                        response.status_code in (301, 302) and method == "POST"
                    ):
                        method, content = "GET", None
                        headers.pop("Content-Type", None)
                    url = next_url
                    hops += 1
                    continue
                nbytes = 0
                async for chunk in response.aiter_raw():
                    nbytes += len(chunk)
                    if nbytes >= spec.response_body_limit:
                        break  # do not buffer large bodies; connection is discarded on close
                return response.status_code, nbytes
            finally:
                await response.aclose()

    def _check_redirect(self, url: httpx.URL) -> None:
        try:
            origin = normalize_base_url(f"{url.scheme}://{url.netloc.decode('ascii')}")
            self.policy.check_origin_approved(origin)
        except PolicyError as exc:
            raise RedirectBlockedError(f"Redirect to unapproved destination refused: {exc.message}") from exc
