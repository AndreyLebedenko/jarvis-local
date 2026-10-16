"""Launcher preferences and process lifecycle, independent of native UI."""

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class LaunchMode(StrEnum):
    ASSISTANT = "assistant"
    MCP = "mcp"


@dataclass(frozen=True)
class LauncherSettings:
    home: Path
    touchstrip: bool = True


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, default_home: Path) -> LauncherSettings:
        if not self.path.exists():
            return LauncherSettings(default_home.resolve())
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as error:
            raise ValueError(f"Invalid launcher settings: {self.path}") from error
        if not isinstance(data, dict):
            raise ValueError("Launcher settings must be an object.")
        home, touchstrip = data.get("home"), data.get("touchstrip")
        if not isinstance(home, str) or not home or type(touchstrip) is not bool:
            raise ValueError("Launcher settings require home and boolean touchstrip.")
        if not Path(home).is_absolute():
            raise ValueError("Launcher settings home must be an absolute path.")
        return LauncherSettings(Path(home), touchstrip)

    def save(self, settings: LauncherSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"home": str(settings.home), "touchstrip": settings.touchstrip},
            ensure_ascii=False,
            indent=2,
        )
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload + "\n")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()


def validate_home(home: Path) -> Path:
    if not home.expanduser().is_absolute():
        raise ValueError("Jarvis Home Folder must be an absolute path.")
    home = home.expanduser().resolve()
    for filename in (".venv/Scripts/python.exe", "src/jarvis/launcher/runtime.py"):
        if not (home / filename).is_file():
            raise ValueError(
                f"Jarvis Home Folder is not a launcher-ready installation.\n"
                f"Missing: {home / filename}\n"
                "Choose an installed copy containing the launcher update."
            )
    return home


def launch_command(settings: LauncherSettings, mode: LaunchMode) -> list[str]:
    return [
        str(settings.home / ".venv/Scripts/python.exe"),
        "-m",
        "jarvis.launcher.runtime",
        "--mode",
        mode.value,
        "--touchstrip",
        "on" if settings.touchstrip else "off",
    ]


Command = dict[str, str | bool]


class RuntimeProcess(Protocol):
    def poll(self) -> int | None: ...
    def send(self, command: Command) -> None: ...


@dataclass(frozen=True)
class LaunchRequest:
    settings: LauncherSettings
    mode: LaunchMode


@dataclass(frozen=True)
class RuntimeExit:
    mode: LaunchMode
    code: int


class RuntimeBusyError(ValueError):
    def __init__(self) -> None:
        super().__init__(
            "Jarvis is already running. Please finish the current session first "
            "using Shutdown in Jarvis or by closing its Status Console."
        )


class LauncherController:
    def __init__(
        self,
        settings: LauncherSettings,
        store: SettingsStore,
        launch: Callable[[LaunchRequest], RuntimeProcess],
        runtime_busy: Callable[[], bool],
    ) -> None:
        self.settings = settings
        self.store = store
        self.launch = launch
        self.runtime_busy = runtime_busy
        self.exiting = False
        self._runtime: tuple[LaunchMode, RuntimeProcess] | None = None

    @property
    def mode(self) -> LaunchMode | None:
        return self._runtime[0] if self._runtime is not None else None

    @property
    def can_exit(self) -> bool:
        return self.exiting and self._runtime is None

    def start(self, mode: LaunchMode) -> None:
        if self.exiting or self._runtime is not None or self.runtime_busy():
            raise RuntimeBusyError()
        validate_home(self.settings.home)
        process = self.launch(LaunchRequest(self.settings, mode))
        self._runtime = (mode, process)

    def poll(self) -> RuntimeExit | None:
        if self._runtime is None:
            return None
        mode, process = self._runtime
        code = process.poll()
        if code is None:
            return None
        result = RuntimeExit(mode, code)
        self._runtime = None
        return result

    def set_touchstrip(self, visible: bool) -> None:
        settings = replace(self.settings, touchstrip=visible)
        self.store.save(settings)
        self.settings = settings
        if self._runtime is not None:
            self._runtime[1].send({"command": "touchstrip", "visible": visible})

    def show_touchstrip(self) -> None:
        if self._runtime is not None:
            self._runtime[1].send({"command": "touchstrip", "visible": True})

    def set_home(self, home: Path) -> None:
        if self._runtime is not None:
            raise RuntimeBusyError()
        settings = replace(self.settings, home=validate_home(home))
        self.store.save(settings)
        self.settings = settings

    def request_exit(self) -> None:
        if self.exiting:
            return
        if self._runtime is not None:
            self._runtime[1].send({"command": "shutdown"})
        self.exiting = True
