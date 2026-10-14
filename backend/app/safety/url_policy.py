"""URL normalization and destination (SSRF) policy.

The policy is applied in three places:
  1. when a target is registered,
  2. when a test is validated / started (DNS is resolved and every address is checked),
  3. at connection time inside the HTTP client (see ``network.py``), so DNS rebinding and
     redirects can never reach an address that was not authorized.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

ALLOWED_SCHEMES = {"http", "https"}
DEFAULT_PORTS = {"http": 80, "https": 443}

# Never reachable, regardless of configuration: link-local (incl. cloud metadata services),
# "this network", multicast and broadcast.
ALWAYS_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("fd00:ec2::254/128"),
]


class PolicyError(Exception):
    """A URL or destination was rejected by the safety policy."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class NormalizedOrigin:
    scheme: str
    host: str  # lower-case, IDNA-encoded, IPv6 without brackets
    port: int

    @property
    def origin(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        default = DEFAULT_PORTS[self.scheme]
        return f"{self.scheme}://{host}" + ("" if self.port == default else f":{self.port}")


def _check_text(value: str, what: str) -> None:
    if any(ord(c) < 0x21 or ord(c) == 0x7F for c in value):
        raise PolicyError("invalid_url", f"{what} must not contain whitespace or control characters.")


def normalize_base_url(raw: str) -> NormalizedOrigin:
    """Parse a base URL like ``http://localhost:8080`` into a canonical origin."""
    raw = (raw or "").strip()
    if not raw:
        raise PolicyError("invalid_url", "Base URL is required.")
    if len(raw) > 2048:
        raise PolicyError("invalid_url", "Base URL is too long.")
    _check_text(raw, "Base URL")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise PolicyError("invalid_url", f"Base URL could not be parsed: {exc}") from exc
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise PolicyError("invalid_scheme", "Only http:// and https:// URLs are supported.")
    if parts.username or parts.password or "@" in parts.netloc:
        raise PolicyError(
            "invalid_url", "Credentials in the URL are not allowed; use the Authentication section."
        )
    if parts.query or parts.fragment:
        raise PolicyError("invalid_url", "Base URL must not contain a query string or fragment.")
    if parts.path not in ("", "/"):
        raise PolicyError(
            "invalid_url", "Base URL must not contain a path; put it in the endpoint path field."
        )
    host = parts.hostname
    if not host:
        raise PolicyError("invalid_url", "Base URL must include a host name.")
    host = host.lower().rstrip(".")
    try:
        ip = ipaddress.ip_address(host)
        host = ip.compressed
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise PolicyError("invalid_url", "Host name is not a valid domain name.") from exc
        if not all(label and len(label) <= 63 for label in host.split(".")):
            raise PolicyError("invalid_url", "Host name is not a valid domain name.") from None
    return NormalizedOrigin(scheme=scheme, host=host, port=port or DEFAULT_PORTS[scheme])


def normalize_path(path: str) -> str:
    path = (path or "").strip() or "/"
    if len(path) > 2048:
        raise PolicyError("invalid_path", "Endpoint path is too long.")
    _check_text(path, "Endpoint path")
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith("//") or "://" in path:
        raise PolicyError("invalid_path", "Endpoint path must be a path, not a URL.")
    if "?" in path or "#" in path:
        raise PolicyError("invalid_path", "Put query parameters in the Query Parameters section.")
    return path


def _unwrap(ip: IPAddress) -> IPAddress:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
    return ip


def classify_ip(ip: IPAddress) -> str:
    """Return 'blocked', 'internal' or 'public'."""
    ip = _unwrap(ip)
    if any(ip in net for net in ALWAYS_BLOCKED_NETWORKS) or ip.is_link_local or ip.is_multicast:
        return "blocked"
    if ip.is_unspecified:
        return "blocked"
    if ip.is_global:
        return "public"
    return "internal"  # loopback, RFC1918, CGNAT, ULA, reserved...


@dataclass
class DestinationPolicy:
    local_target_hosts: frozenset[str]
    allow_external: bool
    approved_origins: frozenset[str] = field(default_factory=frozenset)

    def check_origin_approved(self, origin: NormalizedOrigin) -> None:
        if origin.origin not in self.approved_origins:
            raise PolicyError(
                "target_not_approved",
                f"{origin.origin} is not a registered target. Register and approve it on the Targets page first.",
            )

    def check_ip(self, host: str, ip: IPAddress) -> None:
        kind = classify_ip(ip)
        if kind == "blocked":
            raise PolicyError(
                "blocked_address", f"{host} resolves to {ip}, which is never allowed (link-local/reserved)."
            )
        if kind == "internal":
            if host.lower() not in self.local_target_hosts:
                raise PolicyError(
                    "internal_address",
                    f"{host} resolves to internal address {ip}. Only operator-approved local development hosts "
                    f"({', '.join(sorted(self.local_target_hosts)) or 'none'}) may use internal addresses.",
                )
            return
        if not self.allow_external:
            raise PolicyError(
                "external_disabled",
                f"{host} resolves to public address {ip}. External targets are disabled by the operator "
                "(LOADLAB_ALLOW_EXTERNAL_TARGETS=false).",
            )

    def check_host_static(self, host: str) -> None:
        """Checks possible without DNS (used at registration time for IP literals)."""
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return
        self.check_ip(host, ip)

    async def resolve_and_check(self, host: str, port: int) -> list[str]:
        """Resolve ``host`` and validate *every* returned address. Returns the IPs to pin."""
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            self.check_ip(host, literal)
            return [literal.compressed]
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP), timeout=5.0
            )
        except (TimeoutError, OSError) as exc:
            raise PolicyError("dns_failure", f"Could not resolve {host}: {exc}") from exc
        ips: list[str] = []
        for info in infos:
            addr = info[4][0].split("%", 1)[0]
            if addr not in ips:
                ips.append(addr)
        if not ips:
            raise PolicyError("dns_failure", f"{host} did not resolve to any address.")
        for addr in ips:  # all must pass, otherwise a rebinding answer could slip through
            self.check_ip(host, ipaddress.ip_address(addr))
        return ips
