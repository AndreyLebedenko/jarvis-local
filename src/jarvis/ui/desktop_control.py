"""Private inherited command pipe from the tray launcher to its runtime."""

import json
import logging
import threading
from collections.abc import Callable
from typing import Protocol, TextIO

logger = logging.getLogger(__name__)


class DesktopControl(Protocol):
    touchstrip_visible: bool

    def start(
        self, shutdown: Callable[[], None], visibility: Callable[[bool], None]
    ) -> None: ...


def dispatch_command(
    line: str, shutdown: Callable[[], None], visibility: Callable[[bool], None]
) -> bool:
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError("Launcher command must be an object.")
    command = data.get("command")
    if command == "shutdown":
        shutdown()
        return False
    if command == "touchstrip" and type(data.get("visible")) is bool:
        visibility(data["visible"])
        return True
    raise ValueError("Unknown or invalid launcher command.")


class StdinDesktopControl:
    def __init__(self, stream: TextIO, *, touchstrip_visible: bool = True) -> None:
        self._stream = stream
        self.touchstrip_visible = touchstrip_visible

    def start(
        self, shutdown: Callable[[], None], visibility: Callable[[bool], None]
    ) -> None:
        threading.Thread(
            target=self._consume_safely,
            args=(shutdown, visibility),
            name="launcher-control",
            daemon=True,
        ).start()

    def _consume_safely(
        self, shutdown: Callable[[], None], visibility: Callable[[bool], None]
    ) -> None:
        try:
            self.consume(shutdown, visibility)
        except Exception:
            logger.exception(
                "Launcher control pipe failed; requesting orderly shutdown"
            )
            shutdown()

    def consume(
        self, shutdown: Callable[[], None], visibility: Callable[[bool], None]
    ) -> None:
        for line in self._stream:
            if not dispatch_command(line, shutdown, visibility):
                return
        # EOF means the supervisor has gone away, including a launcher crash.
        shutdown()
