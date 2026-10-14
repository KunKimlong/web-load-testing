"""Report serialization and CSV/JSON export."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from ..models_db import TestRun

SENSITIVE_WARNING = (
    "This report may contain sensitive endpoint metadata (URLs, header names, payload shapes). "
    "Credentials are redacted, but review before sharing."
)

TIMELINE_COLUMNS = [
    "t",
    "target_rps",
    "sent",
    "completed",
    "success",
    "failure",
    "avg_ms",
    "p95_ms",
    "in_flight",
    "dropped",
]
HISTORY_COLUMNS = [
    "id",
    "name",
    "status",
    "preset",
    "method",
    "target_origin",
    "path",
    "created_at",
    "started_at",
    "finished_at",
    "duration_s",
    "configured_rps",
    "achieved_rps",
    "total",
    "success",
    "failure",
    "error_rate",
    "p50_ms",
    "p95_ms",
    "p99_ms",
]


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def run_summary(row: TestRun) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "preset": row.preset,
        "method": row.method,
        "target_origin": row.target_origin,
        "path": row.path,
        "created_at": as_utc(row.created_at),
        "started_at": as_utc(row.started_at),
        "finished_at": as_utc(row.finished_at),
        "duration_s": row.duration_s,
        "configured_rps": row.configured_rps,
        "achieved_rps": row.achieved_rps,
        "total": row.total,
        "success": row.success,
        "failure": row.failure,
        "error_rate": row.error_rate,
        "p50_ms": row.p50_ms,
        "p95_ms": row.p95_ms,
        "p99_ms": row.p99_ms,
    }


def run_detail(row: TestRun) -> dict:
    return {
        **run_summary(row),
        "config": row.config,
        "plan": row.plan,
        "summary": row.summary,
        "stop_reason": row.stop_reason,
    }


def run_report(row: TestRun) -> dict:
    return {**run_detail(row), "timeline": row.timeline or []}


def _csv_value(v: object) -> object:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v  # neutralise spreadsheet formula injection
    return "" if v is None else v


def timeline_csv(row: TestRun) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TIMELINE_COLUMNS)
    for p in row.timeline or []:
        w.writerow([_csv_value(p.get(c)) for c in TIMELINE_COLUMNS])
    return buf.getvalue()


def history_csv(rows: list[TestRun]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HISTORY_COLUMNS)
    for r in rows:
        s = run_summary(r)
        w.writerow([_csv_value(s[c]) for c in HISTORY_COLUMNS])
    return buf.getvalue()
