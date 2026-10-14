"""Test-configuration validation and plan construction (all limits enforced here, server-side)."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..engine.rates import PRESETS, build_stages, expected_requests, peak_of, to_rps
from ..engine.runner import RequestSpec
from ..redaction import REDACTED, is_sensitive_key, redact_pairs
from ..safety.url_policy import DEFAULT_PORTS, NormalizedOrigin, PolicyError, normalize_path
from ..schemas import PlanLimits, TestConfig, TestPlan, UserSettings, ValidationIssue
from .targets import validate_target


class PlanValidationError(Exception):
    def __init__(self, errors: list[ValidationIssue]):
        super().__init__("; ".join(e.message for e in errors))
        self.errors = errors


@dataclass
class PreparedTest:
    plan: TestPlan
    spec: RequestSpec
    origin: NormalizedOrigin
    pinned_ips: list[str]
    redacted_config: dict


def effective_limits(settings: Settings, user: UserSettings) -> PlanLimits:
    return PlanLimits(
        max_rps=min(user.max_rps, settings.hard_max_rps),
        max_concurrency=min(user.max_concurrency, settings.hard_max_concurrency),
        max_duration_s=min(user.max_duration_s, settings.hard_max_duration_s),
        max_timeout_s=settings.hard_max_timeout_s,
        max_request_body_bytes=settings.hard_max_request_body_bytes,
        response_body_limit_bytes=settings.response_body_limit_bytes,
    )


def default_user_settings(settings: Settings) -> UserSettings:
    return UserSettings(
        max_rps=min(100.0, settings.hard_max_rps),
        max_concurrency=min(50, settings.hard_max_concurrency),
        max_duration_s=min(600, settings.hard_max_duration_s),
        confirm_above_rps=50,
    )


def _body_bytes(config: TestConfig, errors: list[ValidationIssue], limit: int) -> bytes | None:
    if config.body.type == "none" or config.body.content == "":
        return None
    if config.method == "GET":
        errors.append(
            ValidationIssue(code="body_not_allowed", message="GET requests cannot have a body.", field="body")
        )
        return None
    data = config.body.content.encode("utf-8")
    if len(data) > limit:
        errors.append(
            ValidationIssue(
                code="body_too_large", message=f"Request body exceeds {limit} bytes.", field="body"
            )
        )
    if config.body.type == "json":
        try:
            json.loads(config.body.content)
        except json.JSONDecodeError as exc:
            errors.append(
                ValidationIssue(code="invalid_json", message=f"Body is not valid JSON: {exc}", field="body")
            )
    return data


def _secrets(config: TestConfig) -> list[str]:
    out: list[str] = []
    a = config.auth
    if a.type == "bearer" and a.token:
        out.append(a.token)
    if a.type == "basic":
        if a.password:
            out.append(a.password)
        out.append(base64.b64encode(f"{a.username}:{a.password or ''}".encode()).decode())
    out += [h.value for h in config.headers if is_sensitive_key(h.key) and h.value]
    out += [q.value for q in config.query if is_sensitive_key(q.key) and q.value]
    return [s for s in out if s]


def redact_config(config: TestConfig) -> dict:
    data = config.model_dump()
    data["headers"] = redact_pairs(data["headers"])
    data["query"] = redact_pairs(data["query"])
    auth = data["auth"]
    if auth.get("token"):
        auth["token"] = REDACTED
    if auth.get("password"):
        auth["password"] = REDACTED
    return data


def _port(origin: NormalizedOrigin) -> int | None:
    return None if origin.port == DEFAULT_PORTS[origin.scheme] else origin.port


def build_url(origin: NormalizedOrigin, path: str, config: TestConfig) -> httpx.URL:
    url = httpx.URL(scheme=origin.scheme, host=origin.host, port=_port(origin), path=path)
    if config.query:
        url = url.copy_merge_params([(q.key, q.value) for q in config.query])
    return url


def preview_url(origin: NormalizedOrigin, path: str, config: TestConfig) -> str:
    pairs = [(q.key, REDACTED if is_sensitive_key(q.key) else q.value) for q in config.query]
    url = httpx.URL(scheme=origin.scheme, host=origin.host, port=_port(origin), path=path)
    if pairs:
        url = url.copy_merge_params(pairs)
    return str(url)


async def prepare_test(
    session: AsyncSession, owner: str, config: TestConfig, settings: Settings, user: UserSettings
) -> PreparedTest:
    errors: list[ValidationIssue] = []
    warnings: list[str] = []
    limits = effective_limits(settings, user)

    target_resp, origin, ips = await validate_target(session, owner, config.base_url, config.path, settings)
    errors.extend(target_resp.errors)
    warnings.extend(target_resp.warnings)
    try:
        path = normalize_path(config.path)
    except PolicyError:
        path = "/"  # error already recorded by validate_target

    # --- rate / duration / concurrency -----------------------------------------------------
    requested_rps = to_rps(config.rate, config.rate_unit)
    duration = config.duration_s
    concurrency = config.max_concurrency
    preset = PRESETS[config.preset]

    if requested_rps > limits.max_rps:
        errors.append(
            ValidationIssue(
                code="rate_too_high",
                field="rate",
                message=f"Requested rate {requested_rps:g} RPS exceeds your maximum of {limits.max_rps:g} RPS "
                f"(hard limit {settings.hard_max_rps:g} RPS). Lower the rate or adjust Settings.",
            )
        )
    if duration > limits.max_duration_s:
        errors.append(
            ValidationIssue(
                code="duration_too_long",
                field="duration_s",
                message=f"Duration {duration}s exceeds the maximum of {limits.max_duration_s}s.",
            )
        )
    if concurrency > limits.max_concurrency:
        errors.append(
            ValidationIssue(
                code="concurrency_too_high",
                field="max_concurrency",
                message=f"Concurrency {concurrency} exceeds the maximum of {limits.max_concurrency}.",
            )
        )
    if config.timeout_s > limits.max_timeout_s:
        errors.append(
            ValidationIssue(
                code="timeout_too_long",
                field="timeout_s",
                message=f"Timeout {config.timeout_s:g}s exceeds the maximum of {limits.max_timeout_s:g}s.",
            )
        )
    if requested_rps < 1 / 60:
        errors.append(
            ValidationIssue(code="rate_too_low", field="rate", message="Rate must be at least 1 RPM.")
        )

    peak = min(requested_rps, limits.max_rps)
    if preset.max_rps is not None and peak > preset.max_rps:
        warnings.append(f"{preset.label} preset caps the rate at {preset.max_rps:g} RPS.")
        peak = preset.max_rps
    if preset.max_duration_s is not None and duration > preset.max_duration_s:
        warnings.append(f"{preset.label} preset caps the duration at {preset.max_duration_s}s.")
        duration = preset.max_duration_s
    if preset.max_concurrency is not None and concurrency > preset.max_concurrency:
        concurrency = preset.max_concurrency
    duration = min(duration, limits.max_duration_s)
    concurrency = min(concurrency, limits.max_concurrency)

    # --- request shape -------------------------------------------------------------------
    if len(config.headers) > settings.max_headers:
        errors.append(
            ValidationIssue(
                code="too_many_headers",
                field="headers",
                message=f"At most {settings.max_headers} headers are allowed.",
            )
        )
    if len(config.query) > settings.max_query_params:
        errors.append(
            ValidationIssue(
                code="too_many_query_params",
                field="query",
                message=f"At most {settings.max_query_params} query parameters are allowed.",
            )
        )
    if config.auth.type != "none" and any(h.key.lower() == "authorization" for h in config.headers):
        errors.append(
            ValidationIssue(
                code="duplicate_auth",
                field="headers",
                message="Use either the Authentication section or an Authorization header, not both.",
            )
        )
    body = _body_bytes(config, errors, limits.max_request_body_bytes)
    if config.follow_redirects and not (1 <= config.max_redirects <= settings.max_redirects):
        errors.append(
            ValidationIssue(
                code="invalid_redirects",
                field="max_redirects",
                message=f"Max redirects must be between 1 and {settings.max_redirects}.",
            )
        )
    if config.retries > settings.max_retries:
        errors.append(
            ValidationIssue(
                code="too_many_retries",
                field="retries",
                message=f"At most {settings.max_retries} retries (connection errors only).",
            )
        )
    if not config.verify_tls:
        warnings.append("TLS certificate verification is disabled.")

    if errors or origin is None:
        raise PlanValidationError(errors)

    stages = build_stages(config.preset, round(peak, 6), duration)
    assert peak_of(stages) <= limits.max_rps + 1e-9  # presets never exceed the user's maximum
    if peak * config.timeout_s > concurrency and peak > 0:
        warnings.append(
            f"With {concurrency} concurrent requests, throughput drops below {peak:g} RPS once latency "
            f"exceeds {concurrency / peak * 1000:.0f} ms; excess requests are counted as dropped."
        )
    if peak >= user.confirm_above_rps:
        warnings.append(
            f"Peak rate {peak:g} RPS is above your confirmation threshold ({user.confirm_above_rps:g} RPS)."
        )

    headers: dict[str, str] = {h.key.strip(): h.value for h in config.headers}
    if config.auth.type == "bearer":
        headers["Authorization"] = f"Bearer {config.auth.token}"
    elif config.auth.type == "basic":
        cred = base64.b64encode(f"{config.auth.username}:{config.auth.password or ''}".encode()).decode()
        headers["Authorization"] = f"Basic {cred}"
    if body is not None and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = (
            "application/json" if config.body.type == "json" else "text/plain; charset=utf-8"
        )

    plan = TestPlan(
        preset=config.preset,
        url_preview=preview_url(origin, path, config),
        method=config.method,
        target_origin=origin.origin,
        peak_rps=round(peak, 6),
        average_rps=round(expected_requests(stages) / duration, 3) if duration else 0,
        configured_rate=config.rate,
        rate_unit=config.rate_unit,
        duration_s=duration,
        max_concurrency=concurrency,
        timeout_s=config.timeout_s,
        expected_requests=expected_requests(stages),
        stages=stages,
        limits=limits,
        warnings=warnings,
    )
    spec = RequestSpec(
        method=config.method,
        url=build_url(origin, path, config),
        headers=headers,
        content=body,
        timeout_s=config.timeout_s,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects if config.follow_redirects else 0,
        retries=config.retries,
        response_body_limit=settings.response_body_limit_bytes,
        secrets=_secrets(config),
    )
    return PreparedTest(
        plan=plan, spec=spec, origin=origin, pinned_ips=ips, redacted_config=redact_config(config)
    )
