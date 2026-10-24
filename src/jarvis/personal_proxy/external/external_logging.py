"""Keeps the httpx library's own log lines (they name the endpoint) out of the
application log while the external client is inside one of its own calls.

A filter on the "httpx" logger drops a record only when a context variable set
by the client is true, so other httpx users running at the same time (for
example the Ollama backend) are not muted and no logger level is changed.
httpcore DEBUG logging, if the owner enables it, is outside this filter.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_inside_external_call: ContextVar[bool] = ContextVar(
    "personal_proxy_inside_external_call", default=False
)


class _DropDuringExternalCall(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _inside_external_call.get()


def _ensure_filter_installed() -> None:
    logger = logging.getLogger("httpx")
    if not any(isinstance(f, _DropDuringExternalCall) for f in logger.filters):
        logger.addFilter(_DropDuringExternalCall())


@contextmanager
def external_call_scope() -> Iterator[None]:
    _ensure_filter_installed()
    token = _inside_external_call.set(True)
    try:
        yield
    finally:
        _inside_external_call.reset(token)
