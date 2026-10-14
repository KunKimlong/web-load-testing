from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_session
from ..engine.manager import ActiveTest, TestManager
from ..models_db import TestRun
from ..schemas import (
    PlanResponse,
    StartTestRequest,
    TestConfig,
    TestListResponse,
    TestReport,
    TestRunDetail,
    UserSettings,
)
from ..services import reports
from ..services.planning import PlanValidationError, prepare_test
from ..services.targets import approved_origins
from .deps import manager_dep, owner_dep, settings_dep, user_settings_dep

router = APIRouter(prefix="/api/tests", tags=["tests"])

ACTIVE_STATUSES = ("pending", "running", "paused")


async def _get_row(session: AsyncSession, owner: str, test_id: str) -> TestRun:
    row = await session.scalar(select(TestRun).where(TestRun.id == test_id, TestRun.owner == owner))
    if row is None:
        raise HTTPException(404, "Test run not found.")
    return row


def _active_or_409(manager: TestManager, test_id: str, owner: str) -> ActiveTest:
    a = manager.get(test_id, owner)
    if a is None:
        raise HTTPException(409, "This test is not running.")
    return a


@router.post("/plan", response_model=PlanResponse)
async def plan_test(
    config: TestConfig,
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
    user: UserSettings = Depends(user_settings_dep),
):
    """Validate a configuration and return the execution plan without starting anything."""
    try:
        prepared = await prepare_test(session, owner, config, settings, user)
    except PlanValidationError as exc:
        return PlanResponse(ok=False, errors=exc.errors)
    return PlanResponse(ok=True, plan=prepared.plan)


@router.post("", response_model=TestRunDetail, status_code=201)
async def start_test(
    req: StartTestRequest,
    response: Response,
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
    user: UserSettings = Depends(user_settings_dep),
    manager: TestManager = Depends(manager_dep),
):
    if req.client_request_id:
        existing = await session.scalar(
            select(TestRun).where(TestRun.owner == owner, TestRun.client_request_id == req.client_request_id)
        )
        if existing:  # duplicate submission (double click / retry): return the original run
            response.status_code = 200
            return reports.run_detail(existing)
    if not req.confirm:
        raise HTTPException(400, "Review the test plan and confirm before starting (confirm=true).")

    prepared = await prepare_test(session, owner, req.config, settings, user)  # raises PlanValidationError
    manager.check_capacity(owner)  # raises CapacityError -> 409

    plan = prepared.plan
    row = TestRun(
        owner=owner,
        client_request_id=req.client_request_id,
        name=req.config.name,
        status="pending",
        preset=plan.preset,
        method=plan.method,
        target_origin=plan.target_origin,
        path=prepared.spec.url.path,
        configured_rps=plan.peak_rps,
        config=prepared.redacted_config,
        plan=plan.model_dump(),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "A test with this request id already exists.") from exc
    await session.refresh(row)
    try:
        await manager.start(row.id, owner, prepared, await approved_origins(session, owner))
    except Exception:
        row.status = "failed"
        row.stop_reason = "start_failed"
        await session.commit()
        raise
    row.status = "running"
    return reports.run_detail(row)


@router.get("", response_model=TestListResponse)
async def list_tests(
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
    q: str | None = Query(None, max_length=200, description="Search name, target or path"),
    target: str | None = Query(None, max_length=300),
    status: str | None = Query(None, max_length=16),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    stmt = select(TestRun).where(TestRun.owner == owner)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(TestRun.name).like(like),
                func.lower(TestRun.target_origin).like(like),
                func.lower(TestRun.path).like(like),
            )
        )
    if target:
        stmt = stmt.where(TestRun.target_origin == target)
    if status:
        stmt = stmt.where(TestRun.status == status)
    if date_from:
        stmt = stmt.where(TestRun.created_at >= date_from)
    if date_to:
        stmt = stmt.where(TestRun.created_at <= date_to)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.scalars(stmt.order_by(TestRun.created_at.desc()).limit(limit).offset(offset))
    return {"items": [reports.run_summary(r) for r in rows.all()], "total": total or 0}


@router.get("/export")
async def export_history(
    format: Literal["csv", "json"] = "csv",
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
):
    rows = list(
        (
            await session.scalars(
                select(TestRun).where(TestRun.owner == owner).order_by(TestRun.created_at.desc()).limit(5000)
            )
        ).all()
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if format == "csv":
        return Response(
            reports.history_csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="loadlab-history-{stamp}.csv"'},
        )
    body = {"warning": reports.SENSITIVE_WARNING, "runs": [reports.run_summary(r) for r in rows]}
    return JSONResponse(
        jsonable_encoder(body),
        headers={"Content-Disposition": f'attachment; filename="loadlab-history-{stamp}.json"'},
    )


@router.get("/compare")
async def compare(
    a: str, b: str, owner: str = Depends(owner_dep), session: AsyncSession = Depends(get_session)
):
    ra, rb = await _get_row(session, owner, a), await _get_row(session, owner, b)
    if ra.target_origin != rb.target_origin:
        raise HTTPException(400, "Only runs against the same target can be compared.")
    return jsonable_encoder({"a": reports.run_report(ra), "b": reports.run_report(rb)})


@router.delete("", status_code=200)
async def delete_history(
    confirm: bool = False, owner: str = Depends(owner_dep), session: AsyncSession = Depends(get_session)
):
    if not confirm:
        raise HTTPException(400, "Pass confirm=true to delete all finished test runs.")
    result = await session.execute(
        delete(TestRun).where(TestRun.owner == owner, TestRun.status.not_in(ACTIVE_STATUSES))
    )
    await session.commit()
    return {"deleted": result.rowcount or 0}


@router.get("/{test_id}", response_model=TestRunDetail)
async def get_test(
    test_id: str, owner: str = Depends(owner_dep), session: AsyncSession = Depends(get_session)
):
    return reports.run_detail(await _get_row(session, owner, test_id))


@router.get("/{test_id}/results", response_model=TestReport)
async def get_results(
    test_id: str, owner: str = Depends(owner_dep), session: AsyncSession = Depends(get_session)
):
    return reports.run_report(await _get_row(session, owner, test_id))


@router.get("/{test_id}/export")
async def export_run(
    test_id: str,
    format: Literal["csv", "json"] = "json",
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
):
    row = await _get_row(session, owner, test_id)
    if row.status in ACTIVE_STATUSES:
        raise HTTPException(409, "Results can be exported once the test has finished.")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in row.name)[:60] or "run"
    if format == "csv":
        return Response(
            reports.timeline_csv(row),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="loadlab-{safe_name}-{row.id[:8]}.csv"'},
        )
    body = {"warning": reports.SENSITIVE_WARNING, "report": reports.run_report(row)}
    return JSONResponse(
        jsonable_encoder(body),
        headers={"Content-Disposition": f'attachment; filename="loadlab-{safe_name}-{row.id[:8]}.json"'},
    )


@router.delete("/{test_id}", status_code=204)
async def delete_test(
    test_id: str, owner: str = Depends(owner_dep), session: AsyncSession = Depends(get_session)
):
    row = await _get_row(session, owner, test_id)
    if row.status in ACTIVE_STATUSES:
        raise HTTPException(409, "Stop the test before deleting it.")
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)


@router.post("/{test_id}/stop")
async def stop_test(
    test_id: str,
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
    manager: TestManager = Depends(manager_dep),
):
    await _get_row(session, owner, test_id)
    a = manager.get(test_id, owner)
    if a is None:
        return {"status": "not_running"}
    manager.stop(a, "stopped")
    if a.task:  # wait briefly so the caller sees a settled state; cancellation is immediate
        await asyncio.wait({a.task}, timeout=5)
    return {"status": "stopped"}


@router.post("/{test_id}/pause")
async def pause_test(
    test_id: str, owner: str = Depends(owner_dep), manager: TestManager = Depends(manager_dep)
):
    a = _active_or_409(manager, test_id, owner)
    if not manager.pause(a):
        raise HTTPException(409, "Test cannot be paused in its current state.")
    return {"status": "paused"}


@router.post("/{test_id}/resume")
async def resume_test(
    test_id: str, owner: str = Depends(owner_dep), manager: TestManager = Depends(manager_dep)
):
    a = _active_or_409(manager, test_id, owner)
    if not manager.resume(a):
        raise HTTPException(409, "Test is not paused.")
    return {"status": "running"}


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), separators=(',', ':'))}\n\n"


@router.get("/{test_id}/events")
async def stream_events(
    test_id: str,
    request: Request,
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
    manager: TestManager = Depends(manager_dep),
):
    """Server-Sent Events: ``init`` (full state), ``snapshot`` (1/s), ``status`` and ``done``."""
    row = await _get_row(session, owner, test_id)
    final_detail = reports.run_report(row)
    await session.close()  # don't hold a DB connection for the lifetime of the stream
    active = manager.get(test_id, owner)

    async def gen():
        if active is None:
            yield _sse("done", {"report": final_detail})
            return
        queue = manager.subscribe(active)
        try:
            yield _sse(
                "init",
                {
                    "snapshot": active.last_snapshot or manager.snapshot(active),
                    "timeline": active.metrics.timeline,
                    "plan": active.prepared.plan.model_dump(),
                },
            )
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    if test_id not in manager.active:
                        yield _sse("done", active.last_snapshot or {})
                        return
                    yield ": keepalive\n\n"
                    continue
                yield _sse(event, data)
                if event == "done":
                    return
        finally:
            manager.unsubscribe(active, queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
