# LoadLab — authorized HTTP load testing

LoadLab is a web application for **authorized** load and performance testing of HTTP endpoints you own.
You register a target, configure a bounded request rate and a load profile, review the plan, then watch
live metrics (rate, latency percentiles, status codes, errors, generator health) while the test runs.
You can stop it immediately, and afterwards download a CSV or JSON report.

> LoadLab is not a tool for testing third-party services. The server refuses unregistered targets,
> internal network addresses (except operator-approved local development hosts), cloud metadata
> addresses and, by default, the public internet. These rules are enforced in the backend, not only in the UI.

```
┌──────────────┐  REST + SSE (fetch)   ┌──────────────────────────────┐   bounded, guarded HTTP   ┌─────────────┐
│  Next.js UI  │ ────────────────────► │  FastAPI + asyncio engine    │ ────────────────────────► │ your target │
│  :3000       │ ◄──────────────────── │  :8000  (SQLite/PostgreSQL)  │                           │ (e.g. mock) │
└──────────────┘   live metrics 1/s    └──────────────────────────────┘                           └─────────────┘
```

## Technology stack (and why)

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, **FastAPI**, asyncio | Async I/O suits a high-concurrency, I/O-bound load generator. Pydantic gives strict server-side validation. |
| HTTP client | **HTTPX** 0.28 / httpcore | Async client with connection pooling. A custom network backend lets every connection be checked against the SSRF policy at dial time. |
| Live updates | **Server-Sent Events** | One-way server→client stream: simpler than WebSockets, works through proxies. The UI reads it with `fetch()` so it can send the `Authorization` header. |
| Storage | **SQLAlchemy 2 (async)** + SQLite (aiosqlite) | Zero-setup locally. Set `LOADLAB_DATABASE_URL=postgresql+asyncpg://…` to use PostgreSQL. |
| Frontend | **Next.js 15**, React 19, TypeScript | App Router, typed API contracts (`frontend/src/lib/types.ts` mirrors `backend/app/schemas.py`). |
| UI | **Tailwind CSS 4** + shadcn/ui-style components on Radix primitives | Accessible dialogs, tooltips, tabs and switches; dark and light themes. |
| Charts | **Recharts 3** | Memoised charts with animation off for 1 Hz live updates; each chart also has a table view. |
| Tests | **pytest** (+ local mock server), **Vitest** + Testing Library | No test sends traffic outside `127.0.0.1`. |
| Deploy | Docker multi-stage images + Docker Compose | Non-root containers, ports bound to `127.0.0.1`. |

## Requirements

| What | Option A: Docker (recommended) | Option B: run locally |
|---|---|---|
| Software | Docker Desktop (Windows/macOS) or Docker Engine 24+ with Compose v2 | Python **3.12+** and Node.js **22+** (npm 10+) |
| OS | Windows 10/11, macOS, Linux | same |
| Hardware | 2 CPU cores, 2 GB free RAM, ~2 GB disk for images | 2 CPU cores, 1 GB free RAM |
| Free ports | `3000` (UI), `8000` (API), `8080` (mock target) on 127.0.0.1 | same |
| Browser | A current Chrome, Edge, Firefox or Safari | same |

Check your setup:

```bash
docker --version && docker compose version      # Option A
python --version && node --version              # Option B (python must be 3.12+, node 22+)
```

## Quick start (Docker — recommended)

Requirements: Docker Desktop / Docker Engine with Compose v2.

```bash
docker compose up -d --build
```

| Service | URL | Notes |
|---|---|---|
| UI | http://127.0.0.1:3000 | |
| API + OpenAPI docs | http://127.0.0.1:8000/docs | |
| Mock target | http://127.0.0.1:8080 (inside Compose: `http://mock-target:8080`) | Safe service to test against |

> **Tip:** if something else on your machine already listens on `localhost:3000` (e.g. another dev
> server on IPv6 `::1`), open **http://127.0.0.1:3000** explicitly.

Stop it with `docker compose down`. Add `-v` to also delete the SQLite volume (all history).

### Run a safe test against the local mock server

1. Open **Targets** and register `http://mock-target:8080` (pre-filled). Tick *"I own this system…"*.
   (When running without Docker, register `http://localhost:8080` instead.)
2. Open **New test**. The defaults are a 5 RPS, 30 s constant test of `GET /api/v1/patients`.
   Try a preset (e.g. **Load**), then click **Validate configuration** to see the plan and the safety limits.
3. Click **Start test…**, review the summary, confirm authorization and start.
4. Watch the live dashboard. **Pause/Resume** or **Stop test** at any time (stopping cancels in-flight requests).
5. When it finishes, the page becomes the report. Use **JSON report** / **CSV timeline** to export, or **Run again**.

Useful mock endpoints: `/api/v1/patients?delay_ms=50`, `/slow?ms=800` (shows backpressure when the
concurrency limit is low), `/status/503`, `/flaky?fail_rate=0.2`, `/redirect?to=/health`, `/large?kb=512`, `/echo`.

To test a service running on your host machine from Docker, register `http://host.docker.internal:<port>`.

The same flow via the API (useful for scripting) is in [docs/API.md](docs/API.md#end-to-end-example-with-curl).

## How to use LoadLab

The sidebar has five pages:

**Overview** shows your registered targets, running tests and recent runs at a glance. With no targets yet, it
links you to the Targets page.

**Targets** is where you approve the systems you may test. Enter a name and base URL (scheme, host and port only,
e.g. `http://localhost:8080`) and tick the authorization box. Remove a target with the trash icon. The server
rejects anything its policy forbids, such as internal IPs that aren't approved local hosts, public hosts (unless
enabled), or metadata addresses, and tells you why.

**New test** is where you configure and start a test:

1. *Target*: test name, base URL (pick a registered one), endpoint path and HTTP method. The **Final URL preview**
   shows exactly what will be requested, with secret query values masked.
2. *Request*: optional query parameters, headers, authentication (Bearer or Basic, masked with a show/hide eye)
   and a JSON or text body for POST/PUT/PATCH/DELETE.
3. *Load profile*: pick a preset (Custom, Smoke, Baseline, Load, Spike, Stress), then set rate (RPS or RPM; the hint
   shows the conversion), duration, max concurrency, timeout, retries and redirects. The ⓘ icons explain each field.
4. Click **Validate configuration**. The **Plan** panel shows peak and average rate, expected request count, a
   chart of the load profile, the safety limits and any warnings. Errors appear next to the field they concern.
5. Click **Start test…**, review the summary, tick the authorization box, and press **Start test**.
   **Reset** restores the defaults.

**Test dashboard** opens automatically and updates every second:

- Cards: achieved vs target rate, total, successful, failed, error rate, in flight, dropped.
- Charts: request rate (target dashed vs achieved), latency (average and p95), success vs failure, and status codes.
  Each chart has a *View as table* option.
- Panels: latency percentiles (p50/p90/p95/p99, min/max), **Load generator** health, and errors with samples.
  If the generator panel says *Saturation detected*, LoadLab itself is the bottleneck, not your target.
- **Pause / Resume** and **Stop test**. Stop cancels in-flight requests immediately.

When the test ends, the same page becomes the **report**: final numbers and charts, the redacted configuration,
**JSON report** / **CSV timeline** downloads, and **Run again** (re-opens the form pre-filled, with secrets cleared).

**History** lists past runs. Search by name, target or path, and filter by target, status or date range. Tick two
runs **against the same target** and press **Compare** for a side-by-side table (with better/worse changes) and a
p95 chart. Export the whole history as CSV or JSON, delete single runs, or **Delete all** (running tests are kept).

**Settings** has the API URL and token (needed only when the server uses token auth), theme (system/light/dark),
and **your safety limits** (max RPS, concurrency, duration, and the rate above which an extra warning is shown).
You can lower these freely but never raise them above the server's hard limits, which are shown read-only below.

### How to read the results

| Metric | Meaning |
|---|---|
| Achieved vs target rate | If achieved stays below target, check **Dropped** and the generator panel |
| Dropped | Requests skipped because every concurrency slot was busy: the target is slower than the rate requires. Raise concurrency or treat it as the capacity limit you were looking for |
| p95 / p99 | 95% / 99% of requests finished faster than this; the tail is where slowdowns show first |
| Error rate | Failed ÷ completed. Failures = 4xx/5xx plus timeouts and connection errors |

## Local development (without Docker)

Requirements: **Python 3.12+**, **Node.js 22+**.

```bash
# 1. backend
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:create_app --factory --reload --port 8000

# 2. mock target (second terminal, same venv)
cd backend && uvicorn app.mock_target:app --port 8080

# 3. frontend (third terminal)
cd frontend
npm ci
npm run dev                          # http://localhost:3000
```

Configuration is read from environment variables prefixed `LOADLAB_` (or `backend/.env`). Copy
[`.env.example`](.env.example) and adjust. The frontend reads `NEXT_PUBLIC_API_URL` at build time, and the
API URL and token can also be changed at runtime on the **Settings** page.

## Testing, linting and builds

```bash
# Backend: ruff + pytest (spins up a mock server on 127.0.0.1)
cd backend
ruff check . && ruff format --check .
pytest

# Backend tests without a local Python install
docker build --target dev -t loadlab-backend-dev backend
docker run --rm loadlab-backend-dev sh -c "ruff check . && pytest"

# Frontend
cd frontend
npm run typecheck && npm run lint && npm test && npm run build
```

What's covered:

- **Backend (111 tests):** URL normalization; approved-target enforcement; IP classification; SSRF (metadata, private
  ranges, IPv4-mapped IPv6, mixed DNS answers, DNS rebinding at connect time, pinned addresses); redirect validation;
  RPS/RPM conversion; preset shapes never exceeding the peak; rate accuracy; concurrency limit and backpressure;
  timeouts; connection failures and bounded retries; all HTTP methods, headers, query and JSON bodies; response-body
  limit; stop/cancellation; pause/resume; percentile maths (exact and bounded histogram); history search, CSV/JSON
  export, CSV formula-injection neutralisation, secret redaction; idempotent starts; per-owner limits; token auth and
  owner isolation; CSRF/Origin checks; API rate limiting; the SSE stream.
- **Frontend (19 tests):** rate conversion and formatting; SSE parser; config validation and limit enforcement; preset
  defaults within limits; live-state reducer; the configuration form (URL preview with masked secrets, RPM hint,
  client and server validation errors, confirmation gate, single submission); dashboard states (connecting, live,
  saturation warning, paused/reconnecting, finished).

## Safety model

| Safeguard | Where |
|---|---|
| Targets must be registered with an explicit authorization attestation | `services/targets.py` |
| Only `LOADLAB_LOCAL_TARGET_HOSTS` may resolve to loopback/private IPs; public internet blocked unless `LOADLAB_ALLOW_EXTERNAL_TARGETS=true`; link-local/metadata/multicast **always** blocked | `safety/url_policy.py` |
| Every TCP connection re-resolves and validates **all** addresses, then dials the validated IP (defeats DNS rebinding); the target's addresses are pinned at start | `safety/network.py` |
| Redirects off by default; when on, every hop must be a registered origin, credentials dropped cross-origin | `engine/runner.py` |
| Hard limits (rate, concurrency, duration, timeout, body size, active tests) set by the operator; user limits can only be lower; presets never exceed the configured peak | `config.py`, `services/planning.py` |
| Open-model scheduler with bounded concurrency: excess slots are **dropped and counted**, never queued; tasks ≤ concurrency | `engine/runner.py` |
| Response bodies streamed and discarded after 64 KB | `engine/runner.py` |
| Hard wall-clock deadline, auto-stop after max pause, graceful shutdown stops tests and persists partial results | `engine/manager.py`, `main.py` |
| No retries unless enabled (max 3, connection errors only, with backoff) | `engine/runner.py` |
| Proxy env vars ignored, no IP spoofing / forwarding headers (`X-Forwarded-For`, `Host`, …) | `schemas.py`, `safety/network.py` |
| Secrets redacted in logs, stored configs, error samples and exports; masked in the UI; drafts never persisted with secrets | `redaction.py`, `logging_setup.py` |
| Token auth (`LOADLAB_AUTH_MODE=token`, required in production), per-owner authorization on every test/target/report | `security.py`, `api/*` |
| CSRF: custom `X-LoadLab-Client` header (forces CORS preflight) + Origin allow-list; no wildcard CORS | `security.py`, `main.py` |
| API rate limiting (token bucket per client) and a stricter limit on test starts | `security.py` |
| Generator CPU / memory / event-loop lag reported live, with a saturation warning, so client-side bottlenecks aren't blamed on the target | `engine/sysmon.py` |

## Database

Tables (`targets`, `test_runs`, `user_settings`) are created automatically at startup (`create_all`), which is
idempotent. SQLite lives at `backend/data/loadlab.db` locally or in the `loadlab-data` volume under Docker.

**PostgreSQL:** set `LOADLAB_DATABASE_URL=postgresql+asyncpg://user:password@host:5432/loadlab` (the `asyncpg`
driver is already installed). The models use portable types (JSON, timezone-aware timestamps), so no code changes are
needed. To change the schema later, add Alembic (`alembic init -t async migrations`) and point `target_metadata` at
`app.db.Base.metadata`. Until then, schema changes require recreating the database.

## Deployment notes

- Set `LOADLAB_ENVIRONMENT=production`, `LOADLAB_AUTH_MODE=token`, and one or more long random
  `LOADLAB_AUTH_TOKEN` values (comma separated, one per user). The app refuses to start in production without auth.
- Put the API behind TLS and set `LOADLAB_CORS_ORIGINS` to the exact UI origin.
- Rebuild the frontend image with `NEXT_PUBLIC_API_URL` set to the public API URL, or set it on the Settings page.
- Run **one** backend worker: test state lives in process memory, which is what allows immediate cancellation.
- Disable buffering for `/api/tests/*/events` in reverse proxies (the API sends `X-Accel-Buffering: no`).

## Project layout

```
backend/
  app/
    main.py              app factory, error handlers, lifespan (graceful shutdown)
    config.py            settings + hard safety limits
    security.py          auth, CSRF, API rate limiting, security headers
    schemas.py           API contracts (pydantic)
    safety/              URL normalization, SSRF policy, guarded network backend
    engine/              rates & presets, runner (scheduler), metrics, manager, generator monitor
    services/            targets, planning/validation, reports & export
    api/                 routers: targets, tests (+SSE), system/settings
    mock_target.py       local service to test against
  tests/                 pytest suite
frontend/
  src/app/               pages: overview, targets, tests/new, tests/[id], history, history/compare, settings
  src/components/        app shell, charts, metrics, config form, live dashboard, report view, ui primitives
  src/lib/               API client, SSE parser, types, validation, hooks
docs/                    API reference, troubleshooting
examples/                example configurations (localhost only)
```

More: [API reference](docs/API.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Examples](examples/)

## Known limitations

- Single-process engine: one backend instance generates load. For more throughput, raise limits carefully and
  watch the generator panel; horizontal scaling would need a distributed coordinator.
- HTTP/1.1 only; no HTTP/2, WebSocket or gRPC load.
- Live state is in memory, so a backend restart stops running tests (partial results are saved on graceful shutdown).
- No Alembic migrations yet (see Database).
- One success rule: 2xx/3xx = success. Custom assertions on response bodies aren't supported.
- The guarded transport replaces a private HTTPX attribute (`_pool`). Versions are pinned and tests cover it, but
  re-run the tests when upgrading httpx/httpcore.
