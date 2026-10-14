from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_session
from ..models_db import Target
from ..schemas import TargetCreate, TargetOut, ValidateTargetRequest, ValidateTargetResponse
from ..services import targets as svc
from ..services.reports import as_utc
from .deps import owner_dep, settings_dep

router = APIRouter(prefix="/api/targets", tags=["targets"])


def _out(t: Target) -> TargetOut:
    return TargetOut(
        id=t.id,
        name=t.name,
        origin=t.origin,
        host=t.host,
        port=t.port,
        scheme=t.scheme,
        notes=t.notes,
        is_local=t.is_local,
        created_at=as_utc(t.created_at),
    )


@router.get("", response_model=list[TargetOut])
async def list_targets(owner: str = Depends(owner_dep), session: AsyncSession = Depends(get_session)):
    return [_out(t) for t in await svc.list_targets(session, owner)]


@router.post("", response_model=TargetOut, status_code=201)
async def create_target(
    data: TargetCreate,
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
):
    return _out(await svc.create_target(session, owner, data, settings))


@router.delete("/{target_id}", status_code=204)
async def delete_target(
    target_id: str, owner: str = Depends(owner_dep), session: AsyncSession = Depends(get_session)
):
    t = await svc.get_target(session, owner, target_id)
    if not t:
        raise HTTPException(404, "Target not found.")
    await session.delete(t)
    await session.commit()
    return Response(status_code=204)


@router.post("/validate", response_model=ValidateTargetResponse)
async def validate_target(
    data: ValidateTargetRequest,
    owner: str = Depends(owner_dep),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
):
    resp, _, _ = await svc.validate_target(session, owner, data.base_url, data.path, settings)
    return resp
