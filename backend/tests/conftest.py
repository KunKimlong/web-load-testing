"""Shared fixtures. All traffic goes to a mock server bound to 127.0.0.1 — never to public hosts."""

from __future__ import annotations

import contextlib
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.mock_target import app as mock_app
from app.safety.url_policy import DestinationPolicy

HEADERS = {"X-LoadLab-Client": "1"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # running in a thread
        pass


@contextlib.contextmanager
def live_server(asgi_app, health_path: str = "/api/health"):
    """Run an ASGI app with uvicorn on 127.0.0.1 in a background thread."""
    port = _free_port()
    config = uvicorn.Config(asgi_app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = _Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            if httpx.get(base + health_path, timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    else:
        raise RuntimeError("server did not start")
    try:
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="session")
def mock_server() -> str:
    with live_server(mock_app, "/health") as base:
        yield base


@pytest.fixture
def reset_mock(mock_server: str):
    httpx.post(mock_server + "/__reset")
    return mock_server


def mock_stats(base: str) -> dict:
    return httpx.get(base + "/__stats").json()


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        local_target_hosts=["localhost", "127.0.0.1", "::1"],
        allow_external_targets=False,
        api_rate_limit_per_s=1000,
        api_rate_limit_burst=1000,
        test_start_limit_per_min=1000,
        snapshot_interval_s=0.25,
        log_level="WARNING",
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app, headers=HEADERS) as c:
        yield c


@pytest.fixture
def local_policy() -> DestinationPolicy:
    return DestinationPolicy(
        local_target_hosts=frozenset({"localhost", "127.0.0.1", "::1"}),
        allow_external=False,
        approved_origins=frozenset(),
    )
