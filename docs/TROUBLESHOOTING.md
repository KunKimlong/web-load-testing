# Troubleshooting

### The UI shows a different app at `http://localhost:3000`
Another process (often a dev server bound to IPv6 `::1`/`[::]`) owns `localhost:3000`, while LoadLab's container is
bound to `127.0.0.1:3000`. Open **http://127.0.0.1:3000**, stop the other process, or change the published port in
`docker-compose.yml` (and add the new origin to `LOADLAB_CORS_ORIGINS`).

### "Cannot reach the LoadLab API"
- Check `curl http://127.0.0.1:8000/api/health`.
- On **Settings → API connection**, confirm the URL (default `http://localhost:8000`).
- If the UI is served from an origin other than `localhost:3000` or `127.0.0.1:3000`, add it to `LOADLAB_CORS_ORIGINS`.

### `403 csrf_header` / `403 csrf_origin`
Scripts must send `X-LoadLab-Client: 1` on POST/PUT/DELETE. A browser `Origin` must be listed in `LOADLAB_CORS_ORIGINS`.

### `401 unauthorized`
The server runs with `LOADLAB_AUTH_MODE=token`. Paste a token from `LOADLAB_AUTH_TOKEN` on the Settings page.

### `target_not_approved`
Register the exact origin (scheme + host + port) on the **Targets** page. `http://localhost:8080` and
`http://127.0.0.1:8080` are different origins.

### `internal_address` when registering a target
The host resolves to a private or loopback IP but isn't in `LOADLAB_LOCAL_TARGET_HOSTS`. Add it, e.g.
`LOADLAB_LOCAL_TARGET_HOSTS=localhost,127.0.0.1,::1,my-service`, and only for systems you're authorized to test.
Link-local addresses (e.g. `169.254.169.254`) are always blocked.

### `external_disabled`
Public internet targets are off by default. An operator can set `LOADLAB_ALLOW_EXTERNAL_TARGETS=true`, but only do this
for systems you own or have written permission to test.

### From Docker, `localhost:8080` doesn't reach my service
Inside the backend container, `localhost` is the container itself. Use `http://mock-target:8080` for the bundled mock,
or `http://host.docker.internal:<port>` for services on your machine.

### Achieved rate is lower than the target / "Dropped" keeps growing
All concurrency slots are busy: the target is slower than `rate × latency` allows. Either raise **Max concurrency**
(within limits) or accept that the target is saturated. That is often the finding you're looking for.
If the **Load generator** panel shows saturation (high CPU or event-loop lag), the bottleneck is LoadLab itself: lower
the rate or run the generator on a bigger machine.

### Many `timeout` errors
Requests didn't complete within the configured timeout. Check target health, or raise the timeout (≤ 60 s by default).

### The live dashboard says "Reconnecting…"
The SSE connection dropped. The UI retries with backoff, and the test keeps running server-side. Behind a reverse
proxy, disable response buffering for `/api/tests/*/events`.

### A test stopped by itself
Check the stop reason in the report: `pause_timeout` (paused longer than `LOADLAB_MAX_PAUSE_S`), `hard_deadline`
(safety deadline), or `shutdown` (server restarted; partial results were saved).

### Resetting all data
`docker compose down -v` removes the database volume. Locally, delete `backend/data/loadlab.db`.

### Running backend tests without Python installed
```bash
docker build --target dev -t loadlab-backend-dev backend
docker run --rm loadlab-backend-dev pytest
```
