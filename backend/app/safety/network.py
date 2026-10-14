"""Connection-level SSRF guard for HTTPX.

``GuardedNetworkBackend`` replaces httpcore's default network backend. Every TCP connection
(including those made after a redirect) resolves the host itself, validates *each* resolved
address against the :class:`DestinationPolicy`, and connects to the validated IP. Because the
address that is checked is the address that is dialed, DNS rebinding cannot bypass the check.
Hosts pinned at test start are dialed only at their pinned addresses.

TLS still uses the original host name for SNI and certificate verification because httpcore
performs ``start_tls`` with the request origin, not the dialed IP.
"""

from __future__ import annotations

import ipaddress
import ssl
from collections.abc import Iterable

import certifi
import httpcore
import httpx

from .url_policy import DestinationPolicy, PolicyError

BLOCKED_PREFIX = "blocked_destination:"


class GuardedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, policy: DestinationPolicy, pinned: dict[str, list[str]] | None = None):
        self._policy = policy
        self._pinned = {k.lower(): v for k, v in (pinned or {}).items()}
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        host_l = host.lower().strip("[]")
        try:
            ips = self._pinned.get(host_l)
            if ips is None:
                ips = await self._policy.resolve_and_check(host_l, port)
            else:
                for ip in ips:  # pinned addresses are re-checked; cheap and defensive
                    self._policy.check_ip(host_l, ipaddress.ip_address(ip))
        except PolicyError as exc:
            raise httpcore.ConnectError(f"{BLOCKED_PREFIX} {exc.message}") from exc
        last_exc: Exception | None = None
        for ip in ips:
            try:
                return await self._inner.connect_tcp(
                    ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError(f"{BLOCKED_PREFIX} unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def build_ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class GuardedTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport whose connection pool dials through :class:`GuardedNetworkBackend`.

    httpx 0.28 does not expose ``network_backend``, so the pool is replaced after init. The
    dependency versions are pinned and this behaviour is covered by tests.
    """

    def __init__(self, backend: GuardedNetworkBackend, *, max_connections: int, verify_tls: bool = True):
        ctx = build_ssl_context(verify_tls)
        super().__init__(verify=ctx, trust_env=False, retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ctx,
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
            keepalive_expiry=5.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=backend,
        )


def build_guarded_client(
    policy: DestinationPolicy,
    *,
    pinned: dict[str, list[str]] | None,
    max_connections: int,
    timeout_s: float,
    verify_tls: bool = True,
) -> httpx.AsyncClient:
    transport = GuardedTransport(
        GuardedNetworkBackend(policy, pinned), max_connections=max_connections, verify_tls=verify_tls
    )
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout_s),
        follow_redirects=False,  # redirects are handled (and validated) by the runner
        trust_env=False,  # never route through environment proxies
        headers={"User-Agent": "LoadLab/1.0 (authorized load test)"},
    )
