"""The transport rule: the key and the cleaned text never cross the network
unencrypted."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from jarvis.personal_proxy.external.external_error import (
    ExternalClientError,
    ExternalErrorKind,
)

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_loopback(hostname: str) -> bool:
    return hostname in _LOOPBACK_HOSTS or hostname.endswith(".localhost")


def _is_allowed(endpoint: str) -> bool:
    try:
        parts = urlsplit(endpoint)
        hostname = (parts.hostname or "").lower()
        httpx.URL(endpoint)
    except (ValueError, httpx.InvalidURL):
        return False
    if not hostname:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and _is_loopback(hostname)


def require_secure_endpoint(endpoint: str) -> None:
    if not _is_allowed(endpoint):
        raise ExternalClientError(ExternalErrorKind.INSECURE_ENDPOINT)
