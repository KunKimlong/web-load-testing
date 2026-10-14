"""Application settings. Every hard safety limit lives here and is enforced server-side."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOADLAB_", env_file=".env", extra="ignore")

    environment: Literal["development", "production", "test"] = "development"
    database_url: str = "sqlite+aiosqlite:///./data/loadlab.db"
    log_level: str = "INFO"

    # --- Authentication -------------------------------------------------------------
    # "none" is only appropriate when the API port is bound to localhost.
    auth_mode: Literal["none", "token"] = "none"
    auth_token: str | None = None

    # --- CORS / CSRF ------------------------------------------------------------------
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # --- Target authorization -----------------------------------------------------------
    # Host names (or IP literals) that may resolve to loopback/private addresses.
    local_target_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1"]
    )
    # Public internet targets are refused unless the operator explicitly enables them.
    allow_external_targets: bool = False

    # --- Hard safety limits (users can lower these, never raise them) --------------------
    hard_max_rps: float = 500.0
    hard_max_concurrency: int = 200
    hard_max_duration_s: int = 1800
    hard_max_timeout_s: float = 60.0
    hard_max_request_body_bytes: int = 256 * 1024
    response_body_limit_bytes: int = 64 * 1024
    max_headers: int = 50
    max_query_params: int = 50
    max_redirects: int = 5
    max_retries: int = 3
    max_active_tests_total: int = 4
    max_active_tests_per_owner: int = 2
    max_pause_s: int = 600

    # --- Own API rate limit (per client) ---------------------------------------------------
    api_rate_limit_per_s: float = 20.0
    api_rate_limit_burst: int = 60
    test_start_limit_per_min: int = 10

    snapshot_interval_s: float = 1.0

    @field_validator("cors_origins", "local_target_hosts", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            if v.strip().startswith("["):
                return json.loads(v)
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("local_target_hosts")
    @classmethod
    def _lower_hosts(cls, v: list[str]) -> list[str]:
        return [h.lower().strip("[]") for h in v]


@lru_cache
def get_settings() -> Settings:
    return Settings()
