"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .api import system, targets, tests
from .config import Settings, get_settings
from .engine.manager import CapacityError, TestManager
from .engine.sysmon import GeneratorMonitor
from .logging_setup import configure_logging
from .safety.url_policy import PolicyError
from .security import CSRF_HEADER, SecurityMiddleware, error_body
from .services.planning import PlanValidationError

log = logging.getLogger("loadlab")


def _check_config(settings: Settings) -> None:
    if settings.auth_mode == "token":
        tokens = [t.strip() for t in (settings.auth_token or "").split(",") if t.strip()]
        if not tokens or any(len(t) < 16 for t in tokens):
            raise RuntimeError(
                "LOADLAB_AUTH_MODE=token requires LOADLAB_AUTH_TOKEN (each token >= 16 characters)."
            )
    if settings.environment == "production" and settings.auth_mode == "none":
        raise RuntimeError("Authentication is required in production (set LOADLAB_AUTH_MODE=token).")
    if "*" in settings.cors_origins:
        raise RuntimeError("Wildcard CORS origins are not allowed.")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _check_config(settings)
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_engine(settings.database_url)
        await db.create_schema()
        monitor = GeneratorMonitor()
        monitor.start()
        app.state.monitor = monitor
        app.state.manager = TestManager(settings, monitor)
        if settings.auth_mode == "none":
            log.warning("authentication disabled (LOADLAB_AUTH_MODE=none); bind the API to localhost only")
        log.info(
            "loadlab started",
            extra={
                "allow_external": settings.allow_external_targets,
                "local_hosts": settings.local_target_hosts,
            },
        )
        try:
            yield
        finally:
            await app.state.manager.shutdown()  # graceful: stop tests and persist partial results
            await monitor.stop()
            await db.dispose_engine()

    app = FastAPI(
        title="LoadLab API",
        version="1.0.0",
        description="Authorized HTTP load testing. All safety limits are enforced server-side.",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(SecurityMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", CSRF_HEADER, "X-Request-ID"],
        expose_headers=["Content-Disposition", "X-Request-ID"],
        max_age=600,
    )

    @app.exception_handler(HTTPException)
    async def _http_exc(_: Request, exc: HTTPException):
        code = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation_failed",
            429: "rate_limited",
        }.get(exc.status_code, "error")
        return JSONResponse(
            error_body(code, str(exc.detail)),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(_: Request, exc: RequestValidationError):
        details = [
            {
                "field": ".".join(str(p) for p in e.get("loc", [])[1:]),
                "message": e.get("msg", "invalid"),
                "code": e.get("type", "invalid"),
            }
            for e in exc.errors()
        ]
        msg = details[0]["message"] if details else "Invalid request."
        return JSONResponse(error_body("validation_failed", msg, details), status_code=422)

    @app.exception_handler(PolicyError)
    async def _policy_exc(_: Request, exc: PolicyError):
        return JSONResponse(error_body(exc.code, exc.message), status_code=400)

    @app.exception_handler(PlanValidationError)
    async def _plan_exc(_: Request, exc: PlanValidationError):
        details = [e.model_dump() for e in exc.errors]
        msg = exc.errors[0].message if exc.errors else "Invalid test configuration."
        return JSONResponse(error_body("validation_failed", msg, details), status_code=422)

    @app.exception_handler(CapacityError)
    async def _capacity_exc(_: Request, exc: CapacityError):
        return JSONResponse(error_body("capacity", str(exc)), status_code=409)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse(error_body("internal_error", "An unexpected error occurred."), status_code=500)

    app.include_router(system.router)
    app.include_router(targets.router)
    app.include_router(tests.router)
    return app
