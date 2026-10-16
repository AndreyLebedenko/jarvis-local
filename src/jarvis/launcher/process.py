"""Subprocess adapter; the runtime inherits only its private command pipe."""

import json
import os
import subprocess
from pathlib import Path

from jarvis.core.single_instance import AlreadyRunning, acquire_single_instance
from jarvis.launcher.model import Command, LaunchRequest, launch_command


def runtime_is_busy() -> bool:
    guard = acquire_single_instance()
    if isinstance(guard, AlreadyRunning):
        return True
    guard.release()
    return False


class ChildRuntime:
    def __init__(self, request: LaunchRequest, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        with log_path.open("w", encoding="utf-8") as log:
            self._process = subprocess.Popen(
                launch_command(request.settings, request.mode),
                cwd=request.settings.home,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

    def poll(self) -> int | None:
        code = self._process.poll()
        if code is not None and self._process.stdin is not None:
            self._process.stdin.close()
        return code

    def send(self, command: Command) -> None:
        if self._process.stdin is None:
            raise RuntimeError("The runtime command pipe was not created.")
        self._process.stdin.write(json.dumps(command) + "\n")
        self._process.stdin.flush()
