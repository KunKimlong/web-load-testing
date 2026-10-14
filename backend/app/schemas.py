"""Pydantic API contracts. ``frontend/src/lib/types.ts`` mirrors these definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
RateUnit = Literal["rps", "rpm"]
PresetName = Literal["custom", "smoke", "baseline", "load", "spike", "stress"]
TestStatus = Literal["pending", "running", "paused", "completed", "stopped", "failed"]

_HEADER_NAME_CHARS = set("!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
FORBIDDEN_HEADERS = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "upgrade",
    "te",
    "trailer",
    "proxy-authorization",
    "proxy-connection",
    "keep-alive",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-real-ip",
    "forwarded",
    "true-client-ip",
    "cf-connecting-ip",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=65536)


class KeyValue(Strict):
    key: str = Field(max_length=256)
    value: str = Field(default="", max_length=8192)


class BodyConfig(Strict):
    type: Literal["none", "json", "text"] = "none"
    content: str = ""


class AuthConfig(Strict):
    type: Literal["none", "bearer", "basic"] = "none"
    token: str | None = Field(default=None, max_length=8192)
    username: str | None = Field(default=None, max_length=512)
    password: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def _check(self) -> AuthConfig:
        if self.type == "bearer" and not self.token:
            raise ValueError("A bearer token is required for bearer authentication.")
        if self.type == "basic" and (not self.username or ":" in self.username):
            raise ValueError("Basic authentication needs a username without ':'.")
        return self


class TestConfig(Strict):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(max_length=2048)
    path: str = Field(default="/", max_length=2048)
    method: HttpMethod = "GET"
    query: list[KeyValue] = Field(default_factory=list)
    headers: list[KeyValue] = Field(default_factory=list)
    body: BodyConfig = Field(default_factory=BodyConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    timeout_s: float = Field(default=10.0, gt=0)
    duration_s: int = Field(default=30, ge=1)
    rate_unit: RateUnit = "rps"
    rate: float = Field(default=5.0, gt=0)
    max_concurrency: int = Field(default=10, ge=1)
    preset: PresetName = "custom"
    follow_redirects: bool = False
    max_redirects: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    verify_tls: bool = True

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Test name is required.")
        return v

    @field_validator("headers")
    @classmethod
    def _check_headers(cls, v: list[KeyValue]) -> list[KeyValue]:
        for h in v:
            name = h.key.strip()
            if not name or any(c not in _HEADER_NAME_CHARS for c in name):
                raise ValueError(f"Invalid header name: {h.key!r}")
            if name.lower() in FORBIDDEN_HEADERS:
                raise ValueError(f"Header {name!r} is managed by the client or not allowed.")
            if any(c in h.value for c in "\r\n\0"):
                raise ValueError(f"Header {name!r} contains illegal characters.")
        return v

    @field_validator("query")
    @classmethod
    def _check_query(cls, v: list[KeyValue]) -> list[KeyValue]:
        for q in v:
            if not q.key.strip():
                raise ValueError("Query parameter names must not be empty.")
        return v


class StartTestRequest(Strict):
    config: TestConfig
    confirm: bool = False
    client_request_id: str | None = Field(default=None, max_length=64)


class Stage(BaseModel):
    start_s: float
    end_s: float
    from_rps: float
    to_rps: float


class PlanLimits(BaseModel):
    max_rps: float
    max_concurrency: int
    max_duration_s: int
    max_timeout_s: float
    max_request_body_bytes: int
    response_body_limit_bytes: int


class TestPlan(BaseModel):
    preset: PresetName
    url_preview: str
    method: HttpMethod
    target_origin: str
    peak_rps: float
    average_rps: float
    configured_rate: float
    rate_unit: RateUnit
    duration_s: int
    max_concurrency: int
    timeout_s: float
    expected_requests: int
    stages: list[Stage]
    limits: PlanLimits
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True


class ValidationIssue(BaseModel):
    code: str
    message: str
    field: str | None = None


class ValidateTargetRequest(Strict):
    base_url: str = Field(max_length=2048)
    path: str = Field(default="/", max_length=2048)


class ValidateTargetResponse(BaseModel):
    ok: bool
    normalized_url: str | None = None
    origin: str | None = None
    approved: bool = False
    target_id: str | None = None
    resolved_ips: list[str] = Field(default_factory=list)
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PlanResponse(BaseModel):
    ok: bool
    plan: TestPlan | None = None
    errors: list[ValidationIssue] = Field(default_factory=list)


class TargetCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(max_length=2048)
    notes: str = Field(default="", max_length=2000)
    authorized: bool = Field(
        default=False, description="User attests they own or are authorized to load test this target."
    )


class TargetOut(BaseModel):
    id: str
    name: str
    origin: str
    host: str
    port: int
    scheme: str
    notes: str
    is_local: bool
    created_at: datetime


class LatencyStats(BaseModel):
    avg: float | None = None
    min: float | None = None
    max: float | None = None
    p50: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None


class TimelinePoint(BaseModel):
    t: int
    target_rps: float
    sent: int
    completed: int
    success: int
    failure: int
    avg_ms: float | None
    p95_ms: float | None
    in_flight: int
    dropped: int


class GeneratorStats(BaseModel):
    cpu_percent: float
    rss_mb: float
    loop_lag_ms: float
    open_connections_limit: int
    saturated: bool
    reasons: list[str] = Field(default_factory=list)


class ErrorSample(BaseModel):
    kind: str
    count: int
    samples: list[str]


class MetricsSnapshot(BaseModel):
    test_id: str
    status: TestStatus
    elapsed_s: float
    remaining_s: float
    duration_s: int
    progress: float
    target_rps: float
    configured_peak_rps: float
    actual_rps: float
    total: int
    success: int
    failure: int
    cancelled: int
    in_flight: int
    dropped: int
    retries: int
    error_rate: float
    bytes_received: int
    latency: LatencyStats
    status_codes: dict[str, int]
    errors: list[ErrorSample]
    generator: GeneratorStats | None = None
    eta: str
    point: TimelinePoint | None = None


class TestRunSummary(BaseModel):
    id: str
    name: str
    status: TestStatus
    preset: str
    method: str
    target_origin: str
    path: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_s: float | None
    configured_rps: float
    achieved_rps: float | None
    total: int
    success: int
    failure: int
    error_rate: float | None
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None


class TestRunDetail(TestRunSummary):
    config: dict[str, Any]
    plan: dict[str, Any]
    summary: dict[str, Any] | None
    stop_reason: str | None = None


class TestReport(TestRunDetail):
    timeline: list[dict[str, Any]]


class TestListResponse(BaseModel):
    items: list[TestRunSummary]
    total: int


class UserSettings(Strict):
    max_rps: float = Field(gt=0)
    max_concurrency: int = Field(ge=1)
    max_duration_s: int = Field(ge=1)
    confirm_above_rps: float = Field(default=50, ge=0)


class SettingsResponse(BaseModel):
    user: UserSettings
    hard_limits: PlanLimits
    auth_mode: str
    allow_external_targets: bool
    local_target_hosts: list[str]
    environment: str


class ErrorResponse(BaseModel):
    error: dict[str, Any]
