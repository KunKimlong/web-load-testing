# Example configurations

All examples target the bundled mock server on **localhost:8080**. Under Docker Compose, change `base_url` to
`http://mock-target:8080`. Register the target first (Targets page, or `POST /api/targets`).

| File | What it shows |
|---|---|
| `smoke-localhost.json` | Smoke preset with an RPM rate (120 RPM = 2 RPS, capped at 1 RPS by the preset) |
| `load-ramp-localhost.json` | Ramp 0→20 RPS with a bearer token (redacted in reports) |
| `post-json-localhost.json` | POST with a JSON body at a steady 5 RPS |
| `backpressure-demo-localhost.json` | 800 ms endpoint with 8 concurrent slots: watch "Dropped" and the saturation hint |

Validate without sending traffic:
```bash
curl -s -H "Content-Type: application/json" -H "X-LoadLab-Client: 1" \
  http://127.0.0.1:8000/api/tests/plan -d @examples/smoke-localhost.json
```
