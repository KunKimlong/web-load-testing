from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_session
from ..engine.manager import TestManager
from ..models_db import UserSettingsRow
from ..schemas import UserSettings
from ..security import AuthError, resolve_owner
from ..services.planning import default_user_settings


def settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def manager_dep(request: Request) -> TestManager:
    return request.app.state.manager


def owner_dep(request: Request, settings: Settings = Depends(settings_dep)) -> str:
    try:
        return resolve_owner(request, settings)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc


async def user_settings_dep(
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> UserSettings:
    row = await session.scalar(select(UserSettingsRow).where(UserSettingsRow.owner == owner))
    if row is None:
        return default_user_settings(settings)
    return UserSettings(
        max_rps=row.max_rps,
        max_concurrency=row.max_concurrency,
        max_duration_s=row.max_duration_s,
        confirm_above_rps=row.confirm_above_rps,
    )
