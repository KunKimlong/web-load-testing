"""API-level tests: validation, authorization, lifecycle, history and export."""

import csv
import io
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models_db import TestRun
from app.services.reports import timeline_csv
from tests.conftest import HEADERS, live_server, make_settings


def register(client, base, name="Mock target"):
    r = client.post("/api/targets", json={"name": name, "base_url": base, "authorized": True})
    assert r.status_code == 201, r.text
    return r.json()


def config(base, **kw):
    cfg = {
        "name": "API test",
        "base_url": base,
        "path": "/api/v1/patients",
        "method": "GET",
        "rate": 5,
        "rate_unit": "rps",
        "duration_s": 2,
        "max_concurrency": 5,
        "timeout_s": 2,
    }
    cfg.update(kw)
    return cfg


def wait_finished(client, test_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/tests/{test_id}").json()
        if body["status"] not in ("pending", "running", "paused"):
            return body
        time.sleep(0.2)
    raise AssertionError("test did not finish")


# --- targets ---------------------------------------------------------------------------


def test_register_requires_attestation(client, mock_server):
    r = client.post("/api/targets", json={"name": "x", "base_url": mock_server})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "authorization_required"


@pytest.mark.parametrize(
    "url,code",
    [
        ("http://169.254.169.254", "blocked_address"),
        ("http://10.0.0.1", "internal_address"),
        ("http://192.168.1.10:8080", "internal_address"),
        ("http://8.8.8.8", "external_disabled"),
        ("ftp://localhost", "invalid_scheme"),
        ("http://admin:pw@localhost", "invalid_url"),
    ],
)
def test_register_rejects_forbidden_targets(client, url, code):
    r = client.post("/api/targets", json={"name": "bad", "base_url": url, "authorized": True})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == code


def test_target_crud_and_duplicates(client, mock_server):
    t = register(client, mock_server)
    assert t["is_local"] is True
    assert (
        client.post(
            "/api/targets", json={"name": "dup", "base_url": mock_server + "/", "authorized": True}
        ).status_code
        == 400
    )
    assert [x["id"] for x in client.get("/api/targets").json()] == [t["id"]]
    assert client.delete(f"/api/targets/{t['id']}").status_code == 204
    assert client.get("/api/targets").json() == []


def test_validate_endpoint(client, mock_server):
    r = client.post("/api/targets/validate", json={"base_url": mock_server, "path": "/health"}).json()
    assert r["ok"] is False and r["errors"][0]["code"] == "target_not_approved"
    register(client, mock_server)
    r = client.post("/api/targets/validate", json={"base_url": mock_server, "path": "health"}).json()
    assert r["ok"] is True and r["approved"] is True
    assert r["normalized_url"] == mock_server + "/health"
    assert "127.0.0.1" in r["resolved_ips"]


# --- plan validation ---------------------------------------------------------------------


def test_plan_rpm_conversion_and_preview(client, mock_server):
    register(client, mock_server)
    cfg = config(
        mock_server,
        rate=120,
        rate_unit="rpm",
        duration_s=10,
        query=[{"key": "ward", "value": "A"}, {"key": "api_key", "value": "hunter2"}],
    )
    r = client.post("/api/tests/plan", json=cfg).json()
    assert r["ok"], r
    plan = r["plan"]
    assert plan["peak_rps"] == pytest.approx(2.0)
    assert plan["expected_requests"] == 20
    assert "ward=A" in plan["url_preview"]
    assert "hunter2" not in plan["url_preview"]


def test_plan_enforces_limits(client, mock_server):
    register(client, mock_server)
    r = client.post(
        "/api/tests/plan",
        json=config(mock_server, rate=10_000, max_concurrency=10_000, duration_s=99_999, timeout_s=999),
    ).json()
    codes = {e["code"] for e in r["errors"]}
    assert {"rate_too_high", "concurrency_too_high", "duration_too_long", "timeout_too_long"} <= codes


def test_plan_requires_approved_target(client, mock_server):
    r = client.post("/api/tests/plan", json=config(mock_server)).json()
    assert r["ok"] is False
    assert r["errors"][0]["code"] == "target_not_approved"


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"method": "GET", "body": {"type": "json", "content": '{"a":1}'}}, "body_not_allowed"),
        ({"method": "POST", "body": {"type": "json", "content": "{bad"}}, "invalid_json"),
        ({"follow_redirects": True, "max_redirects": 0}, "invalid_redirects"),
        ({"retries": 99}, "too_many_retries"),
    ],
)
def test_plan_request_validation(client, mock_server, overrides, code):
    register(client, mock_server)
    r = client.post("/api/tests/plan", json=config(mock_server, **overrides)).json()
    assert code in {e["code"] for e in r["errors"]}


@pytest.mark.parametrize("header", ["Host", "X-Forwarded-For", "Content-Length", "Bad Header"])
def test_forbidden_headers_rejected(client, mock_server, header):
    register(client, mock_server)
    r = client.post("/api/tests/plan", json=config(mock_server, headers=[{"key": header, "value": "x"}]))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"


def test_presets_respect_user_maximum(client, mock_server):
    register(client, mock_server)
    assert (
        client.put(
            "/api/settings", json={"max_rps": 20, "max_concurrency": 10, "max_duration_s": 60}
        ).status_code
        == 200
    )
    for preset in ("smoke", "baseline", "load", "spike", "stress"):
        r = client.post(
            "/api/tests/plan", json=config(mock_server, preset=preset, rate=20, duration_s=60)
        ).json()
        assert r["ok"], r
        assert r["plan"]["peak_rps"] <= 20
        assert all(max(s["from_rps"], s["to_rps"]) <= 20 for s in r["plan"]["stages"])
    smoke = client.post(
        "/api/tests/plan", json=config(mock_server, preset="smoke", rate=20, duration_s=60)
    ).json()
    assert smoke["plan"]["peak_rps"] == 1 and smoke["plan"]["duration_s"] == 30
    # a preset must not be used to sneak past the user maximum
    over = client.post("/api/tests/plan", json=config(mock_server, preset="stress", rate=21)).json()
    assert over["ok"] is False and over["errors"][0]["code"] == "rate_too_high"


def test_user_settings_cannot_exceed_hard_limits(client):
    r = client.put("/api/settings", json={"max_rps": 1e9, "max_concurrency": 5, "max_duration_s": 60})
    assert r.status_code == 422


# --- lifecycle -------------------------------------------------------------------------


def test_start_requires_confirmation(client, mock_server):
    register(client, mock_server)
    r = client.post("/api/tests", json={"config": config(mock_server), "confirm": False})
    assert r.status_code == 400


def test_full_lifecycle_history_and_export(client, reset_mock):
    register(client, reset_mock)
    cfg = config(
        reset_mock,
        auth={"type": "bearer", "token": "super-secret-token-value"},
        headers=[{"key": "X-Api-Key", "value": "another-secret"}],
    )
    r = client.post("/api/tests", json={"config": cfg, "confirm": True, "client_request_id": "req-1"})
    assert r.status_code == 201, r.text
    run = r.json()
    # duplicate submission returns the same run instead of starting a second test
    dup = client.post("/api/tests", json={"config": cfg, "confirm": True, "client_request_id": "req-1"})
    assert dup.status_code == 200 and dup.json()["id"] == run["id"]

    final = wait_finished(client, run["id"])
    assert final["status"] == "completed"
    assert 8 <= final["total"] <= 11
    assert final["success"] == final["total"]
    assert final["p95_ms"] is not None and final["achieved_rps"] > 0

    report = client.get(f"/api/tests/{run['id']}/results").json()
    assert report["timeline"] and report["summary"]["status_codes"] == {"200": final["total"]}
    raw = json.dumps(report)
    assert "super-secret-token-value" not in raw and "another-secret" not in raw

    exp = client.get(f"/api/tests/{run['id']}/export?format=json")
    assert exp.status_code == 200 and "attachment" in exp.headers["content-disposition"]
    assert "sensitive" in exp.json()["warning"]
    csv_resp = client.get(f"/api/tests/{run['id']}/export?format=csv")
    rows = list(csv.reader(io.StringIO(csv_resp.text)))
    assert rows[0][:3] == ["t", "target_rps", "sent"]
    assert sum(int(r[2]) for r in rows[1:]) == final["total"]

    hist = client.get("/api/tests", params={"q": "api test"}).json()
    assert hist["total"] == 1
    assert client.get("/api/tests", params={"q": "nomatch"}).json()["total"] == 0
    assert client.get("/api/tests", params={"target": reset_mock}).json()["total"] == 1
    hcsv = client.get("/api/tests/export?format=csv")
    assert hcsv.status_code == 200 and run["id"] in hcsv.text

    assert client.delete(f"/api/tests/{run['id']}").status_code == 204
    assert client.get(f"/api/tests/{run['id']}").status_code == 404


def test_stop_and_events_stream(settings, reset_mock):
    """SSE needs a real server: Starlette's TestClient buffers streaming bodies."""
    with live_server(create_app(settings)) as api:
        c = httpx.Client(base_url=api, headers=HEADERS, timeout=10)
        register(c, reset_mock)
        r = c.post(
            "/api/tests",
            json={
                "config": config(
                    reset_mock,
                    path="/slow",
                    query=[{"key": "ms", "value": "5000"}],
                    duration_s=30,
                    timeout_s=10,
                ),
                "confirm": True,
            },
        )
        test_id = r.json()["id"]
        events, started, acted = [], time.monotonic(), False
        with c.stream("GET", f"/api/tests/{test_id}/events") as s:
            assert s.headers["content-type"].startswith("text/event-stream")
            for line in s.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
                    if events.count("snapshot") == 2 and not acted:
                        acted = True
                        assert c.post(f"/api/tests/{test_id}/pause").status_code == 200
                        assert c.post(f"/api/tests/{test_id}/resume").status_code == 200
                        assert c.post(f"/api/tests/{test_id}/stop").json()["status"] == "stopped"
                if events and events[-1] == "done":
                    break
        assert time.monotonic() - started < 10, "stop must not wait for the 30 s duration"
        assert events[0] == "init" and "snapshot" in events and "status" in events and events[-1] == "done"
        final = wait_finished(c, test_id)
        assert final["status"] == "stopped"
        detail = c.get(f"/api/tests/{test_id}").json()
        assert detail["summary"]["cancelled"] >= 1 and detail["summary"]["in_flight"] == 0
        # stream for a finished test returns the final report immediately
        with c.stream("GET", f"/api/tests/{test_id}/events") as s:
            assert any(line == "event: done" for line in s.iter_lines())


def test_compare_same_target_only(client, reset_mock, mock_server):
    register(client, reset_mock)
    ids = []
    for i in range(2):
        r = client.post(
            "/api/tests", json={"config": config(reset_mock, name=f"run {i}", duration_s=1), "confirm": True}
        )
        ids.append(r.json()["id"])
        wait_finished(client, ids[-1])
    cmp = client.get("/api/tests/compare", params={"a": ids[0], "b": ids[1]})
    assert cmp.status_code == 200 and cmp.json()["a"]["id"] == ids[0]


def test_concurrent_test_limit(tmp_path, reset_mock):
    s = make_settings(tmp_path, max_active_tests_per_owner=1)
    with TestClient(create_app(s), headers=HEADERS) as c:
        register(c, reset_mock)
        first = c.post("/api/tests", json={"config": config(reset_mock, duration_s=10), "confirm": True})
        assert first.status_code == 201
        second = c.post("/api/tests", json={"config": config(reset_mock, duration_s=10), "confirm": True})
        assert second.status_code == 409 and second.json()["error"]["code"] == "capacity"
        c.post(f"/api/tests/{first.json()['id']}/stop")


# --- security --------------------------------------------------------------------------


def test_csrf_header_and_origin_required(settings):
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/targets", json={"name": "x", "base_url": "http://localhost", "authorized": True})
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_header"
        r = c.post("/api/targets", json={}, headers={**HEADERS, "Origin": "https://evil.example"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_origin"
        assert c.get("/api/health").status_code == 200  # safe methods unaffected


def test_token_auth_and_owner_isolation(tmp_path, mock_server):
    tok_a, tok_b = "a" * 24, "b" * 24
    s = make_settings(tmp_path, auth_mode="token", auth_token=f"{tok_a},{tok_b}")
    with TestClient(create_app(s), headers=HEADERS) as c:
        assert c.get("/api/targets").status_code == 401
        assert (
            c.get("/api/targets", headers={"Authorization": "Bearer wrong-token-xxxxxxxx"}).status_code == 401
        )
        a = {"Authorization": f"Bearer {tok_a}"}
        b = {"Authorization": f"Bearer {tok_b}"}
        r = c.post("/api/targets", json={"name": "m", "base_url": mock_server, "authorized": True}, headers=a)
        assert r.status_code == 201
        assert c.get("/api/targets", headers=b).json() == []
        # user B cannot use user A's approval
        plan = c.post("/api/tests/plan", json=config(mock_server), headers=b).json()
        assert plan["errors"][0]["code"] == "target_not_approved"
        run = c.post(
            "/api/tests", json={"config": config(mock_server, duration_s=1), "confirm": True}, headers=a
        ).json()
        assert c.get(f"/api/tests/{run['id']}", headers=b).status_code == 404
        assert c.post(f"/api/tests/{run['id']}/stop", headers=b).status_code == 404
        assert c.get(f"/api/tests/{run['id']}/export", headers=b).status_code == 404


def test_api_rate_limit(tmp_path):
    s = make_settings(tmp_path, api_rate_limit_per_s=0.01, api_rate_limit_burst=3)
    with TestClient(create_app(s), headers=HEADERS) as c:
        codes = [c.get("/api/targets").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and codes[-1] == 429


def test_production_requires_auth(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(make_settings(tmp_path, environment="production"))


def test_csv_formula_injection_neutralised():
    row = TestRun(timeline=[{"t": "=cmd()", "sent": 1}])
    assert "'=cmd()" in timeline_csv(row)
