from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_session
from ..engine.manager import TestManager
from ..engine.rates import PRESETS
from ..models_db import UserSettingsRow
from ..schemas import SettingsResponse, UserSettings
from ..services.planning import effective_limits
from .deps import manager_dep, owner_dep, settings_dep, user_settings_dep

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health(request: Request):
    return {"status": "ok", "active_tests": len(request.app.state.manager.active)}


@router.get("/settings", response_model=SettingsResponse)
async def get_settings_route(
    settings: Settings = Depends(settings_dep), user: UserSettings = Depends(user_settings_dep)
):
    return SettingsResponse(
        user=user,
        hard_limits=effective_limits(
            settings,
            UserSettings(
                max_rps=settings.hard_max_rps,
                max_concurrency=settings.hard_max_concurrency,
                max_duration_s=settings.hard_max_duration_s,
            ),
        ),
        auth_mode=settings.auth_mode,
        allow_external_targets=settings.allow_external_targets,
        local_target_hosts=settings.local_target_hosts,
        environment=settings.environment,
    )


@router.put("/settings", response_model=UserSettings)
async def update_settings(
    data: UserSettings,
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
):
    """User limits may only be set at or below the operator's hard limits."""
    problems = []
    if data.max_rps > settings.hard_max_rps:
        problems.append(f"max_rps cannot exceed the hard limit of {settings.hard_max_rps:g}")
    if data.max_concurrency > settings.hard_max_concurrency:
        problems.append(f"max_concurrency cannot exceed the hard limit of {settings.hard_max_concurrency}")
    if data.max_duration_s > settings.hard_max_duration_s:
        problems.append(f"max_duration_s cannot exceed the hard limit of {settings.hard_max_duration_s}")
    if problems:
        raise HTTPException(422, "; ".join(problems))
    row = await session.scalar(select(UserSettingsRow).where(UserSettingsRow.owner == owner))
    if row is None:
        row = UserSettingsRow(owner=owner)
        session.add(row)
    row.max_rps = data.max_rps
    row.max_concurrency = data.max_concurrency
    row.max_duration_s = data.max_duration_s
    row.confirm_above_rps = data.confirm_above_rps
    await session.commit()
    return data


@router.get("/presets")
async def presets(_: str = Depends(owner_dep)):
    return [
        {
            "name": k,
            "label": p.label,
            "description": p.description,
            "max_rps": p.max_rps,
            "max_duration_s": p.max_duration_s,
            "max_concurrency": p.max_concurrency,
        }
        for k, p in PRESETS.items()
    ]


@router.get("/system")
async def system_stats(
    request: Request, _: str = Depends(owner_dep), manager: TestManager = Depends(manager_dep)
):
    mon = request.app.state.monitor
    return {
        "active_tests": len(manager.active),
        "generator": mon.stats(connections_limit=0, in_flight=0, recent_dropped=0),
    }
