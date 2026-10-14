# LoadLab API reference

Interactive OpenAPI docs: **http://127.0.0.1:8000/docs** (schema at `/openapi.json`).
TypeScript mirrors of every contract are in `frontend/src/lib/types.ts`.

## Conventions

- JSON in and out. Every state-changing request (`POST`/`PUT`/`DELETE`) **must** send `X-LoadLab-Client: 1`
  (CSRF protection; browsers can't send it cross-origin without a CORS preflight, which is restricted to allowed origins).
- Authentication: when `LOADLAB_AUTH_MODE=token`, send `Authorization: Bearer <token>`. Every resource belongs to the
  token that created it, and other tokens get `404`.
- Errors always look like:

```json
{ "error": { "code": "validation_failed", "message": "Human readable", "details": [ { "field": "rate", "message": "...", "code": "rate_too_high" } ] } }
```

| Status | Typical codes |
|---|---|
| 400 | `bad_request`, `invalid_url`, `invalid_scheme`, `blocked_address`, `internal_address`, `external_disabled`, `dns_failure`, `authorization_required`, `duplicate_target` |
| 401 | `unauthorized` |
| 403 | `csrf_header`, `csrf_origin` |
| 404 | `not_found` |
| 409 | `conflict`, `capacity` (too many running tests) |
| 422 | `validation_failed` (details list each problem) |
| 429 | `rate_limited` |

## Endpoints

### System

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Liveness + number of active tests |
| GET | `/api/settings` | Your limits, hard limits, auth mode, target policy |
| PUT | `/api/settings` | Update your limits (`max_rps`, `max_concurrency`, `max_duration_s`, `confirm_above_rps`); cannot exceed hard limits |
| GET | `/api/presets` | Preset descriptions |
| GET | `/api/system` | Load generator CPU / memory / event-loop lag |

### Targets

| Method | Path | Description |
|---|---|---|
| GET | `/api/targets` | List your registered targets |
| POST | `/api/targets` | `{name, base_url, notes?, authorized: true}`: register (validated + DNS-checked) |
| DELETE | `/api/targets/{id}` | Remove approval |
| POST | `/api/targets/validate` | `{base_url, path}` → `{ok, normalized_url, origin, approved, resolved_ips, errors, warnings}` |

### Tests

| Method | Path | Description |
|---|---|---|
| POST | `/api/tests/plan` | Body: `TestConfig`. Validates everything and returns `{ok, plan, errors}` without sending traffic |
| POST | `/api/tests` | `{config: TestConfig, confirm: true, client_request_id?}`. Starts a test. `201` with the run; a repeated `client_request_id` returns the original run (`200`) |
| GET | `/api/tests` | Query: `q`, `target`, `status`, `date_from`, `date_to` (ISO 8601), `limit` ≤ 200, `offset` |
| GET | `/api/tests/{id}` | Run detail (redacted config, plan, summary) |
| GET | `/api/tests/{id}/results` | Detail + per-second `timeline` |
| GET | `/api/tests/{id}/events` | **SSE** stream (see below) |
| POST | `/api/tests/{id}/stop` | Cancel immediately (in-flight requests are cancelled) |
| POST | `/api/tests/{id}/pause` / `/resume` | Pause scheduling (in-flight requests finish). Auto-stops after `LOADLAB_MAX_PAUSE_S` |
| GET | `/api/tests/{id}/export?format=json\|csv` | Download report (JSON) or per-second timeline (CSV) |
| GET | `/api/tests/export?format=csv\|json` | Download history summary |
| GET | `/api/tests/compare?a={id}&b={id}` | Two reports; `400` if the targets differ |
| DELETE | `/api/tests/{id}` | Delete a finished run |
| DELETE | `/api/tests?confirm=true` | Delete all finished runs |

### TestConfig

```jsonc
{
  "name": "Patients smoke",
  "base_url": "http://localhost:8080",      // must be a registered origin
  "path": "/api/v1/patients",
  "method": "GET",                          // GET | POST | PUT | PATCH | DELETE
  "query":   [{ "key": "ward", "value": "A" }],
  "headers": [{ "key": "X-Trace", "value": "loadlab" }],
  "body": { "type": "none", "content": "" },        // none | json | text
  "auth": { "type": "bearer", "token": "…" },        // none | bearer | basic (username/password)
  "timeout_s": 10,
  "duration_s": 60,
  "rate_unit": "rpm",                       // rps | rpm  (120 rpm = 2 rps)
  "rate": 120,                              // peak rate for ramp/spike/stress presets
  "max_concurrency": 10,
  "preset": "custom",                       // custom | smoke | baseline | load | spike | stress
  "follow_redirects": false,
  "max_redirects": 0,
  "retries": 0,                             // connection errors only, ≤ 3
  "verify_tls": true
}
```

Presets: **smoke** is ≤ 1 RPS, ≤ 30 s, ≤ 2 concurrent. **baseline** is a constant rate. **load** ramps 0→peak over 30%,
then holds. **spike** holds 20% of peak, then goes to 100% for the middle 10%. **stress** steps 25/50/75/100% of peak.
The peak never exceeds your limits; the request is rejected rather than clamped silently.

### SSE stream: `GET /api/tests/{id}/events`

```
event: init      data: {"snapshot": MetricsSnapshot, "timeline": TimelinePoint[], "plan": TestPlan}
event: snapshot  data: MetricsSnapshot           (every second; includes the newly closed `point`)
event: status    data: {"status": "paused" | "running"}
event: done      data: final MetricsSnapshot (+ stop_reason, achieved_rps, max_in_flight)
: keepalive                                      (comment every 10 s)
```

For a finished test the stream sends a single `done` event. `MetricsSnapshot` fields: `status, elapsed_s,
remaining_s, progress, target_rps, configured_peak_rps, actual_rps, total, success, failure, cancelled, in_flight,
dropped, retries, error_rate, bytes_received, latency{avg,min,max,p50,p90,p95,p99}, status_codes, errors[],
generator{cpu_percent, rss_mb, loop_lag_ms, saturated, reasons[]}, eta, point`.

**dropped** counts scheduled requests that were not sent because every concurrency slot was busy, or because the
scheduler fell more than 1 s behind. Backpressure is visible here instead of in an unbounded queue.

## End-to-end example with curl

```bash
A=http://127.0.0.1:8000
H=(-H "Content-Type: application/json" -H "X-LoadLab-Client: 1")

curl -s "${H[@]}" $A/api/targets -d '{"name":"Mock","base_url":"http://localhost:8080","authorized":true}'
curl -s "${H[@]}" $A/api/tests/plan -d @examples/smoke-localhost.json
ID=$(curl -s "${H[@]}" $A/api/tests -d "{\"config\": $(cat examples/smoke-localhost.json), \"confirm\": true}" | jq -r .id)
curl -N $A/api/tests/$ID/events            # live stream; Ctrl+C to detach
curl -s "${H[@]}" -X POST $A/api/tests/$ID/stop
curl -s "$A/api/tests/$ID/export?format=csv" -o report.csv
```

(Under Docker Compose use `http://mock-target:8080` as the base URL.)
