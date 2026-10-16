"""Explicit per-user Windows sign-in registration."""

import subprocess
from pathlib import Path
from typing import Protocol

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "JarvisLauncher"


class StartupStore(Protocol):
    def read(self) -> str | None: ...
    def write(self, command: str) -> None: ...
    def delete(self) -> None: ...


def startup_command(pythonw: Path) -> str:
    return subprocess.list2cmdline([str(pythonw), "-m", "jarvis.launcher"])


class StartupRegistration:
    def __init__(self, store: StartupStore, pythonw: Path) -> None:
        self.store = store
        self.command = startup_command(pythonw)

    @property
    def enabled(self) -> bool:
        return self.store.read() == self.command

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self.store.write(self.command)
        else:
            self.store.delete()


class WindowsStartupStore:
    def read(self) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, kind = winreg.QueryValueEx(key, RUN_VALUE)
        except FileNotFoundError:
            return None
        if kind != winreg.REG_SZ or not isinstance(value, str):
            raise ValueError("The JarvisLauncher startup entry is not a string.")
        return value

    def write(self, command: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)

    def delete(self) -> None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            return
