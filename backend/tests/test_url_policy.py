import asyncio
import ipaddress
import socket

import httpx
import pytest

from app.safety.network import build_guarded_client
from app.safety.url_policy import (
    DestinationPolicy,
    PolicyError,
    classify_ip,
    normalize_base_url,
    normalize_path,
)


@pytest.mark.parametrize(
    "raw,origin",
    [
        ("http://localhost:8080", "http://localhost:8080"),
        ("HTTP://LocalHost:8080/", "http://localhost:8080"),
        ("http://127.0.0.1", "http://127.0.0.1"),
        ("https://example.com:443", "https://example.com"),
        ("http://[::1]:9000", "http://[::1]:9000"),
        ("https://bücher.example", "https://xn--bcher-kva.example"),
    ],
)
def test_normalize_base_url(raw, origin):
    assert normalize_base_url(raw).origin == origin


@pytest.mark.parametrize(
    "raw,code",
    [
        ("ftp://localhost", "invalid_scheme"),
        ("file:///etc/passwd", "invalid_scheme"),
        ("gopher://localhost:70", "invalid_scheme"),
        ("http://user:pass@localhost", "invalid_url"),
        ("http://localhost@evil.com", "invalid_url"),
        ("http://localhost/api", "invalid_url"),
        ("http://localhost?x=1", "invalid_url"),
        ("http://local host", "invalid_url"),
        ("http://localhost:99999", "invalid_url"),
        ("", "invalid_url"),
        ("localhost:8080", "invalid_scheme"),
    ],
)
def test_normalize_base_url_rejects(raw, code):
    with pytest.raises(PolicyError) as e:
        normalize_base_url(raw)
    assert e.value.code == code


def test_normalize_path():
    assert normalize_path("api/v1") == "/api/v1"
    assert normalize_path("") == "/"
    for bad in ("//evil.com/x", "/a?b=1", "http://x/y", "/a b", "/a#frag"):
        with pytest.raises(PolicyError):
            normalize_path(bad)


@pytest.mark.parametrize(
    "ip,kind",
    [
        ("127.0.0.1", "internal"),
        ("10.1.2.3", "internal"),
        ("172.16.0.1", "internal"),
        ("192.168.1.1", "internal"),
        ("100.64.0.1", "internal"),
        ("::1", "internal"),
        ("fc00::1", "internal"),
        ("169.254.169.254", "blocked"),
        ("0.0.0.0", "blocked"),
        ("224.0.0.1", "blocked"),
        ("fe80::1", "blocked"),
        ("::ffff:169.254.169.254", "blocked"),
        ("::ffff:127.0.0.1", "internal"),
        ("8.8.8.8", "public"),
        ("2606:4700:4700::1111", "public"),
    ],
)
def test_classify_ip(ip, kind):
    assert classify_ip(ipaddress.ip_address(ip)) == kind


def test_policy_internal_only_for_local_hosts(local_policy):
    local_policy.check_ip("localhost", ipaddress.ip_address("127.0.0.1"))
    with pytest.raises(PolicyError) as e:
        local_policy.check_ip("intranet.corp", ipaddress.ip_address("10.0.0.5"))
    assert e.value.code == "internal_address"


def test_policy_metadata_always_blocked():
    policy = DestinationPolicy(frozenset({"169.254.169.254"}), allow_external=True)
    with pytest.raises(PolicyError) as e:
        policy.check_ip("169.254.169.254", ipaddress.ip_address("169.254.169.254"))
    assert e.value.code == "blocked_address"


def test_policy_external_disabled_by_default(local_policy):
    with pytest.raises(PolicyError) as e:
        local_policy.check_ip("example.com", ipaddress.ip_address("93.184.216.34"))
    assert e.value.code == "external_disabled"
    DestinationPolicy(frozenset(), allow_external=True).check_ip(
        "example.com", ipaddress.ip_address("93.184.216.34")
    )


def test_origin_must_be_approved(local_policy):
    with pytest.raises(PolicyError) as e:
        local_policy.check_origin_approved(normalize_base_url("http://localhost:8080"))
    assert e.value.code == "target_not_approved"


def _fake_dns(monkeypatch, answers: dict[str, list[str]]):
    loop = asyncio.get_running_loop()
    real = loop.getaddrinfo

    async def fake(host, port, *args, **kwargs):
        if host in answers:
            fam = lambda a: socket.AF_INET6 if ":" in a else socket.AF_INET  # noqa: E731
            return [(fam(a), socket.SOCK_STREAM, 6, "", (a, port)) for a in answers[host]]
        return await real(host, port, *args, **kwargs)

    monkeypatch.setattr(loop, "getaddrinfo", fake)


async def test_resolve_rejects_mixed_answers(monkeypatch):
    """A rebinding-style answer mixing public and internal addresses must be refused entirely."""
    _fake_dns(monkeypatch, {"rebind.test": ["93.184.216.34", "127.0.0.1"]})
    policy = DestinationPolicy(frozenset({"localhost"}), allow_external=True)
    with pytest.raises(PolicyError) as e:
        await policy.resolve_and_check("rebind.test", 80)
    assert e.value.code == "internal_address"


async def test_resolve_localhost(local_policy):
    ips = await local_policy.resolve_and_check("localhost", 80)
    assert ips and all(classify_ip(ipaddress.ip_address(i)) == "internal" for i in ips)


async def test_guard_blocks_dns_rebinding_at_connect_time(monkeypatch, mock_server):
    """Even if a name validated earlier now resolves to loopback, the connection is refused."""
    port = int(mock_server.rsplit(":", 1)[1])
    _fake_dns(monkeypatch, {"rebind.test": ["127.0.0.1"]})
    policy = DestinationPolicy(frozenset({"localhost", "127.0.0.1"}), allow_external=True)
    client = build_guarded_client(policy, pinned=None, max_connections=2, timeout_s=2)
    async with client:
        with pytest.raises(httpx.ConnectError, match="blocked_destination"):
            await client.get(f"http://rebind.test:{port}/health")
        # the approved local host still works through the same guarded client
        r = await client.get(f"http://127.0.0.1:{port}/health")
        assert r.status_code == 200


async def test_guard_uses_pinned_addresses(monkeypatch, mock_server):
    port = int(mock_server.rsplit(":", 1)[1])
    _fake_dns(monkeypatch, {"localhost": ["93.184.216.34"]})  # DNS changed after validation
    policy = DestinationPolicy(frozenset({"localhost"}), allow_external=False)
    client = build_guarded_client(policy, pinned={"localhost": ["127.0.0.1"]}, max_connections=2, timeout_s=2)
    async with client:
        r = await client.get(f"http://localhost:{port}/health")
        assert r.status_code == 200  # dialed the pinned, validated address


async def test_guard_blocks_metadata_ip_literal():
    policy = DestinationPolicy(frozenset({"localhost"}), allow_external=True)
    client = build_guarded_client(policy, pinned=None, max_connections=1, timeout_s=1)
    async with client:
        with pytest.raises(httpx.ConnectError, match="blocked_destination"):
            await client.get("http://169.254.169.254/latest/meta-data/")
