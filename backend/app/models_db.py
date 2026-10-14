"""ORM models. Column types are portable between SQLite and PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Target(Base):
    __tablename__ = "targets"
    __table_args__ = (UniqueConstraint("owner", "origin", name="uq_target_owner_origin"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    origin: Mapped[str] = mapped_column(String(300))
    scheme: Mapped[str] = mapped_column(String(8))
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_local: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TestRun(Base):
    __tablename__ = "test_runs"
    __table_args__ = (UniqueConstraint("owner", "client_request_id", name="uq_run_idempotency"),)
    __test__ = False  # not a pytest class

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    client_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    preset: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(8))
    target_origin: Mapped[str] = mapped_column(String(300), index=True)
    path: Mapped[str] = mapped_column(String(2048))
    configured_rps: Mapped[float] = mapped_column(Float)
    achieved_rps: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[int] = mapped_column(Integer, default=0)
    failure: Mapped[int] = mapped_column(Integer, default=0)
    error_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    p50_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p99_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)  # secrets redacted before storage
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    timeline: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSettingsRow(Base):
    __tablename__ = "user_settings"

    owner: Mapped[str] = mapped_column(String(64), primary_key=True)
    max_rps: Mapped[float] = mapped_column(Float)
    max_concurrency: Mapped[int] = mapped_column(Integer)
    max_duration_s: Mapped[int] = mapped_column(Integer)
    confirm_above_rps: Mapped[float] = mapped_column(Float, default=50)
