"""Secret redaction for logs, persisted configs and error messages."""

from __future__ import annotations

import re
from collections.abc import Iterable

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_RE = re.compile(
    r"(authorization|cookie|token|secret|password|passwd|api[-_]?key|apikey|session|signature|"
    r"credential|private|access[-_]?key|auth)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/=]{4,}")
_URL_USERINFO_RE = re.compile(r"(?i)(https?://)[^/\s@]+@")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:[^=&\s]*(?:token|secret|password|key|signature|auth)[^=&\s]*)=)[^&\s#]+"
)


def is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(key))


def redact_pairs(pairs: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for p in pairs:
        key = p.get("key", "")
        out.append({"key": key, "value": REDACTED if is_sensitive_key(key) else p.get("value", "")})
    return out


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove known secret values plus common credential patterns from free text."""
    if not text:
        return text
    for s in sorted({s for s in secrets if s and len(s) >= 3}, key=len, reverse=True):
        text = text.replace(s, REDACTED)
    text = _BEARER_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _URL_USERINFO_RE.sub(lambda m: f"{m.group(1)}{REDACTED}@", text)
    text = _QUERY_SECRET_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    return text
