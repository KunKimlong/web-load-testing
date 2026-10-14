"""Target registry: users must register (and attest authorization for) an origin before testing it."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models_db import Target
from ..safety.url_policy import (
    DestinationPolicy,
    NormalizedOrigin,
    PolicyError,
    normalize_base_url,
    normalize_path,
)
from ..schemas import TargetCreate, ValidateTargetResponse, ValidationIssue


def policy_for(
    settings: Settings, approved_origins: set[str] | frozenset[str] = frozenset()
) -> DestinationPolicy:
    return DestinationPolicy(
        local_target_hosts=frozenset(settings.local_target_hosts),
        allow_external=settings.allow_external_targets,
        approved_origins=frozenset(approved_origins),
    )


async def approved_origins(session: AsyncSession, owner: str) -> set[str]:
    rows = await session.scalars(select(Target.origin).where(Target.owner == owner))
    return set(rows.all())


async def list_targets(session: AsyncSession, owner: str) -> list[Target]:
    rows = await session.scalars(
        select(Target).where(Target.owner == owner).order_by(Target.created_at.desc())
    )
    return list(rows.all())


async def get_target(session: AsyncSession, owner: str, target_id: str) -> Target | None:
    return await session.scalar(select(Target).where(Target.owner == owner, Target.id == target_id))


async def create_target(session: AsyncSession, owner: str, data: TargetCreate, settings: Settings) -> Target:
    if not data.authorized:
        raise PolicyError(
            "authorization_required",
            "You must confirm that you own this system or have permission to load test it.",
        )
    origin = normalize_base_url(data.base_url)
    policy = policy_for(settings)
    policy.check_host_static(origin.host)
    # Resolve now so obviously-forbidden targets are rejected at registration time.
    await policy.resolve_and_check(origin.host, origin.port)
    existing = await session.scalar(
        select(Target).where(Target.owner == owner, Target.origin == origin.origin)
    )
    if existing:
        raise PolicyError("duplicate_target", f"{origin.origin} is already registered.")
    target = Target(
        owner=owner,
        name=data.name.strip(),
        origin=origin.origin,
        scheme=origin.scheme,
        host=origin.host,
        port=origin.port,
        notes=data.notes,
        is_local=origin.host in settings.local_target_hosts,
    )
    session.add(target)
    await session.commit()
    await session.refresh(target)
    return target


async def validate_target(
    session: AsyncSession, owner: str, base_url: str, path: str, settings: Settings
) -> tuple[ValidateTargetResponse, NormalizedOrigin | None, list[str]]:
    """Full server-side check: syntax, registration, DNS resolution and IP policy."""
    errors: list[ValidationIssue] = []
    warnings: list[str] = []
    try:
        origin = normalize_base_url(base_url)
    except PolicyError as exc:
        errors.append(ValidationIssue(code=exc.code, message=exc.message, field="base_url"))
        return ValidateTargetResponse(ok=False, errors=errors), None, []
    try:
        norm_path = normalize_path(path)
    except PolicyError as exc:
        errors.append(ValidationIssue(code=exc.code, message=exc.message, field="path"))
        norm_path = None

    target = await session.scalar(select(Target).where(Target.owner == owner, Target.origin == origin.origin))
    policy = policy_for(settings, await approved_origins(session, owner))
    try:
        policy.check_origin_approved(origin)
    except PolicyError as exc:
        errors.append(ValidationIssue(code=exc.code, message=exc.message, field="base_url"))

    ips: list[str] = []
    try:
        ips = await policy.resolve_and_check(origin.host, origin.port)
    except PolicyError as exc:
        errors.append(ValidationIssue(code=exc.code, message=exc.message, field="base_url"))
    if origin.scheme == "http" and origin.host not in settings.local_target_hosts:
        warnings.append("Plain HTTP: credentials and payloads are sent unencrypted.")
    resp = ValidateTargetResponse(
        ok=not errors,
        normalized_url=origin.origin + (norm_path or ""),
        origin=origin.origin,
        approved=target is not None,
        target_id=target.id if target else None,
        resolved_ips=ips,
        errors=errors,
        warnings=warnings,
    )
    return resp, origin, ips
