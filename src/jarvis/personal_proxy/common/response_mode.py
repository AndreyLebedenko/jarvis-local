"""The response mode as the proxy sees it: the string value of the
application's mode, read through a getter so the proxy imports nothing of the
application."""

from __future__ import annotations

from collections.abc import Callable

ResponseModeGetter = Callable[[], str]

TEXT_MODE = "text"


def always_text() -> str:
    return TEXT_MODE
