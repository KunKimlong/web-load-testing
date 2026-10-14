"""A small local HTTP service to load test safely (used by the test suite and docker-compose demo).

Run: ``uvicorn app.mock_target:app --port 8080``
"""

from __future__ import annotations

import asyncio
import random

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse


class Stats:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.requests = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.methods: dict[str, int] = {}


stats = Stats()
app = FastAPI(title="LoadLab mock target", docs_url=None, redoc_url=None)

PATIENTS = [{"id": i, "name": f"Patient {i}", "ward": random.choice("ABCD")} for i in range(1, 26)]  # noqa: S311


@app.middleware("http")
async def _count(request: Request, call_next):
    if request.url.path.startswith("/__"):
        return await call_next(request)
    stats.requests += 1
    stats.in_flight += 1
    stats.max_in_flight = max(stats.max_in_flight, stats.in_flight)
    stats.methods[request.method] = stats.methods.get(request.method, 0) + 1
    try:
        return await call_next(request)
    finally:
        stats.in_flight -= 1


@app.get("/__stats")
async def get_stats():
    return {
        "requests": stats.requests,
        "in_flight": stats.in_flight,
        "max_in_flight": stats.max_in_flight,
        "methods": stats.methods,
    }


@app.post("/__reset")
async def reset_stats():
    stats.reset()
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.api_route("/api/v1/patients", methods=["GET", "POST"])
async def patients(request: Request, delay_ms: int = 5):
    await asyncio.sleep(min(delay_ms, 5000) / 1000 * random.uniform(0.5, 1.5))  # noqa: S311
    if request.method == "POST":
        return JSONResponse({"created": True}, status_code=201)
    return PATIENTS


@app.api_route("/api/v1/patients/{pid}", methods=["GET", "PUT", "PATCH", "DELETE"])
async def patient(pid: int, request: Request):
    await asyncio.sleep(0.005)
    if pid not in range(1, 26):
        return JSONResponse({"detail": "not found"}, status_code=404)
    if request.method == "DELETE":
        return Response(status_code=204)
    return PATIENTS[pid - 1]


@app.api_route("/echo", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def echo(request: Request):
    body = await request.body()
    return {
        "method": request.method,
        "path": request.url.path,
        "query": dict(request.query_params),
        "headers": {k: v for k, v in request.headers.items()},
        "body": body.decode("utf-8", "replace"),
    }


@app.get("/slow")
async def slow(ms: int = 500):
    await asyncio.sleep(min(ms, 120_000) / 1000)
    return {"slept_ms": ms}


@app.get("/status/{code}")
async def status(code: int):
    return Response(status_code=code if 100 <= code <= 599 else 400)


@app.get("/flaky")
async def flaky(fail_rate: float = 0.2):
    if random.random() < fail_rate:  # noqa: S311
        return JSONResponse({"error": "random failure"}, status_code=503)
    return {"ok": True}


@app.get("/redirect")
async def redirect(to: str = "/health", code: int = 302):
    return RedirectResponse(to, status_code=code)


@app.get("/large")
async def large(kb: int = 512):
    return Response(b"x" * (min(kb, 10_240) * 1024), media_type="application/octet-stream")
