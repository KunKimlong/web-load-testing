"""Test lifecycle management: start, pause/resume, stop, live snapshots and persistence."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial

from sqlalchemy import select

from .. import db
from ..config import Settings
from ..models_db import TestRun
from ..redaction import redact_text
from ..safety.network import build_guarded_client
from ..services.planning import PreparedTest
from ..services.targets import policy_for
from .metrics import MetricsCollector
from .runner import LoadRunner
from .sysmon import GeneratorMonitor

log = logging.getLogger(__name__)

STOP_REASON_STATUS = {
    "completed": "completed",
    "stopped": "stopped",
    "pause_timeout": "stopped",
    "shutdown": "stopped",
    "hard_deadline": "stopped",
    "error": "failed",
}


class CapacityError(Exception):
    pass


@dataclass
class ActiveTest:
    id: str
    owner: str
    runner: LoadRunner
    metrics: MetricsCollector
    prepared: PreparedTest
    started_wall: float
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    task: asyncio.Task | None = None
    tick: int = 0
    last_snapshot: dict | None = None
    status: str = "running"
    stopping: bool = False


class TestManager:
    __test__ = False

    def __init__(self, settings: Settings, monitor: GeneratorMonitor):
        self.settings = settings
        self.monitor = monitor
        self.active: dict[str, ActiveTest] = {}
        self._lock = asyncio.Lock()

    # --- queries ------------------------------------------------------------------------
    def get(self, test_id: str, owner: str) -> ActiveTest | None:
        a = self.active.get(test_id)
        return a if a and a.owner == owner else None

    def count_for(self, owner: str) -> int:
        return sum(1 for a in self.active.values() if a.owner == owner)

    def check_capacity(self, owner: str) -> None:
        if len(self.active) >= self.settings.max_active_tests_total:
            raise CapacityError("The server is already running the maximum number of concurrent tests.")
        if self.count_for(owner) >= self.settings.max_active_tests_per_owner:
            raise CapacityError(
                f"You already have {self.count_for(owner)} running test(s); stop one before starting another."
            )

    # --- lifecycle ----------------------------------------------------------------------
    async def start(self, test_id: str, owner: str, prepared: PreparedTest, approved: set[str]) -> ActiveTest:
        async with self._lock:
            self.check_capacity(owner)
            plan = prepared.plan
            policy = policy_for(self.settings, approved)
            client = build_guarded_client(
                policy,
                pinned={prepared.origin.host: prepared.pinned_ips},
                max_connections=plan.max_concurrency,
                timeout_s=plan.timeout_s,
                verify_tls=prepared.redacted_config.get("verify_tls", True),
            )
            metrics = MetricsCollector()
            runner = LoadRunner(
                spec=prepared.spec,
                stages=plan.stages,
                duration_s=plan.duration_s,
                max_concurrency=plan.max_concurrency,
                client=client,
                policy=policy,
                metrics=metrics,
                redact=partial(redact_text, secrets=prepared.spec.secrets),
                max_pause_s=self.settings.max_pause_s,
            )
            active = ActiveTest(
                id=test_id,
                owner=owner,
                runner=runner,
                metrics=metrics,
                prepared=prepared,
                started_wall=time.monotonic(),
            )
            self.active[test_id] = active
            active.task = asyncio.create_task(self._run(active, client), name=f"loadtest-{test_id}")
            log.info(
                "test started",
                extra={
                    "test_id": test_id,
                    "target": plan.target_origin,
                    "peak_rps": plan.peak_rps,
                    "duration_s": plan.duration_s,
                },
            )
            return active

    def stop(self, a: ActiveTest, reason: str = "stopped") -> None:
        a.stopping = True
        a.runner.stop(reason)

    def pause(self, a: ActiveTest) -> bool:
        ok = a.runner.pause()
        if ok:
            a.status = "paused"
            self._publish(a, "status", {"status": "paused"})
        return ok

    def resume(self, a: ActiveTest) -> bool:
        ok = a.runner.resume()
        if ok:
            a.status = "running"
            self._publish(a, "status", {"status": "running"})
        return ok

    async def shutdown(self) -> None:
        for a in list(self.active.values()):
            self.stop(a, "shutdown")
        tasks = [a.task for a in self.active.values() if a.task]
        if tasks:
            await asyncio.wait(tasks, timeout=10)

    # --- events -------------------------------------------------------------------------
    def subscribe(self, a: ActiveTest) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        a.subscribers.add(q)
        return q

    def unsubscribe(self, a: ActiveTest, q: asyncio.Queue) -> None:
        a.subscribers.discard(q)

    def _publish(self, a: ActiveTest, event: str, data: dict) -> None:
        for q in list(a.subscribers):
            if q.full():  # slow consumer: drop the oldest event rather than grow unbounded
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait((event, data))

    def snapshot(self, a: ActiveTest, point: dict | None = None) -> dict:
        m, r, plan = a.metrics, a.runner, a.prepared.plan
        elapsed = r.elapsed
        remaining = max(0.0, plan.duration_s - elapsed)
        recent_dropped = sum(p["dropped"] for p in m.timeline[-3:])
        if a.status in ("completed", "stopped", "failed"):
            eta = {"completed": "Completed", "stopped": "Stopped", "failed": "Failed"}[a.status]
        elif a.stopping:
            eta = "Stopping…"
        elif a.status == "paused":
            eta = f"Paused — {remaining:.0f}s of load remaining"
        elif remaining <= 0:
            eta = "Finishing in-flight requests…"
        else:
            eta = f"~{remaining:.0f}s remaining"
        totals = m.totals()
        return {
            "test_id": a.id,
            "status": a.status,
            "elapsed_s": round(elapsed, 2),
            "remaining_s": round(remaining, 2),
            "duration_s": plan.duration_s,
            "progress": round(min(1.0, elapsed / plan.duration_s), 4) if plan.duration_s else 1.0,
            "target_rps": round(r.current_target_rps, 3),
            "configured_peak_rps": plan.peak_rps,
            "actual_rps": m.actual_rps,
            "total": totals["total"],
            "success": totals["success"],
            "failure": totals["failure"],
            "cancelled": totals["cancelled"],
            "in_flight": r.in_flight,
            "dropped": totals["dropped"],
            "retries": totals["retries"],
            "error_rate": totals["error_rate"],
            "bytes_received": totals["bytes_received"],
            "latency": totals["latency"],
            "status_codes": totals["status_codes"],
            "errors": totals["errors"],
            "generator": self.monitor.stats(
                connections_limit=plan.max_concurrency, in_flight=r.in_flight, recent_dropped=recent_dropped
            ),
            "eta": eta,
            "point": point,
        }

    # --- internals ---------------------------------------------------------------------
    async def _snapshot_loop(self, a: ActiveTest) -> None:
        interval = self.settings.snapshot_interval_s
        next_at = a.started_wall + interval
        while True:
            await asyncio.sleep(max(0.0, next_at - time.monotonic()))
            next_at += interval
            a.tick += 1
            point = a.metrics.close_window(a.tick, a.runner.current_target_rps)
            a.last_snapshot = self.snapshot(a, point)
            self._publish(a, "snapshot", a.last_snapshot)

    async def _run(self, a: ActiveTest, client) -> None:
        plan = a.prepared.plan
        await self._update_row(a.id, status="running", started_at=datetime.now(UTC))
        snap_task = asyncio.create_task(self._snapshot_loop(a))
        hard_deadline = plan.duration_s + self.settings.max_pause_s + plan.timeout_s + 15
        reason = "error"
        try:
            reason = await asyncio.wait_for(a.runner.run(), timeout=hard_deadline)
        except TimeoutError:
            reason = "hard_deadline"
        except Exception:
            log.exception("load test crashed", extra={"test_id": a.id})
            reason = "error"
        finally:
            snap_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await snap_task
            await client.aclose()
            a.status = STOP_REASON_STATUS.get(reason, "stopped")
            a.tick += 1
            point = a.metrics.close_window(a.tick, 0.0)
            final = self.snapshot(a, point)
            final["stop_reason"] = reason
            final["max_in_flight"] = a.metrics.max_in_flight
            final["achieved_rps"] = (
                round(a.metrics.sent / a.runner.elapsed, 3) if a.runner.elapsed > 0 else 0.0
            )
            try:
                await self._persist_final(a, final, reason)
            except Exception:
                log.exception("failed to persist results", extra={"test_id": a.id})
            self._publish(a, "done", final)
            self.active.pop(a.id, None)
            log.info("test finished", extra={"test_id": a.id, "reason": reason, "total": a.metrics.sent})

    async def _update_row(self, test_id: str, **fields) -> None:
        async with db.sessionmaker()() as session:
            row = await session.scalar(select(TestRun).where(TestRun.id == test_id))
            if row:
                for k, v in fields.items():
                    setattr(row, k, v)
                await session.commit()

    async def _persist_final(self, a: ActiveTest, final: dict, reason: str) -> None:
        lat = final["latency"]
        summary = {k: v for k, v in final.items() if k not in ("point", "generator")}
        summary["generator_at_end"] = final.get("generator")
        await self._update_row(
            a.id,
            status=a.status,
            stop_reason=reason,
            finished_at=datetime.now(UTC),
            duration_s=round(a.runner.elapsed, 3),
            achieved_rps=final["achieved_rps"],
            total=final["total"],
            success=final["success"],
            failure=final["failure"],
            error_rate=final["error_rate"],
            p50_ms=lat["p50"],
            p95_ms=lat["p95"],
            p99_ms=lat["p99"],
            summary=summary,
            timeline=a.metrics.timeline,
        )
