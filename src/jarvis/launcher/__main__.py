"""Run the idle Windows tray launcher, without importing the Jarvis engine."""

import logging
import os
import queue
import sys
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from jarvis.core.single_instance import (
    ALREADY_RUNNING_EXIT_CODE,
    AlreadyRunning,
    acquire_single_instance,
)
from jarvis.launcher.model import (
    LauncherController,
    LaunchMode,
    RuntimeBusyError,
    SettingsStore,
)
from jarvis.launcher.process import ChildRuntime, runtime_is_busy
from jarvis.launcher.startup import StartupRegistration, WindowsStartupStore
from jarvis.launcher.tray import SHOW_TOUCHSTRIP, WindowsTray
from jarvis.launcher.window import ICON_PATH, SettingsWindow, dialog

LAUNCHER_MUTEX = r"Local\Jarvis.Launcher.SingleInstance"
LAUNCHER_LOG_MAX_BYTES = 1_000_000
logger = logging.getLogger(__name__)


class LauncherApp:
    def __init__(self, root: tk.Tk, directory: Path, default_home: Path) -> None:
        self.root = root
        self.log_path = directory / "runtime.log"
        store = SettingsStore(directory / "settings.json")
        self.controller = LauncherController(
            store.load(default_home),
            store,
            lambda request: ChildRuntime(request, self.log_path),
            runtime_is_busy,
        )
        self.startup = StartupRegistration(
            WindowsStartupStore(), Path(sys.executable).with_name("pythonw.exe")
        )
        self.events: queue.Queue[int | Exception] = queue.Queue()
        self.tray = WindowsTray(ICON_PATH, self.events.put, self.events.put)
        self.settings: SettingsWindow | None = None
        self._tray_failed = False

    def run(self) -> None:
        self.root.report_callback_exception = self._callback_error
        self.tray.start()
        try:
            self.root.after(200, self._tick)
            self.root.mainloop()
        finally:
            self.tray.close()

    def _callback_error(
        self,
        kind: type[BaseException],
        error: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        logger.error("Launcher callback failed", exc_info=(kind, error, traceback))
        dialog(self.root, "Launcher error", str(error))

    def _show_error(self, error: Exception) -> None:
        logger.error("Launcher operation failed: %s", error)
        dialog(
            self.root,
            "Jarvis is already running"
            if isinstance(error, RuntimeBusyError)
            else "Could not complete the action",
            str(error),
        )

    def _action(self, identifier: int) -> None:
        try:
            if identifier in (1, 2):
                self.controller.start(
                    LaunchMode.ASSISTANT if identifier == 1 else LaunchMode.MCP
                )
            elif identifier == 3:
                self._open_settings()
            elif identifier == SHOW_TOUCHSTRIP:
                self.controller.show_touchstrip()
            elif identifier == 4:
                self.controller.request_exit()
        except (OSError, ValueError, RuntimeError) as error:
            self._show_error(error)

    def _open_settings(self) -> None:
        if self.settings is not None and self.settings.window.winfo_exists():
            self.settings.window.lift()
            self.settings.window.focus_force()
        else:
            self.settings = SettingsWindow(
                self.root, self.controller, self.startup, self._show_error
            )

    def _tick(self) -> None:
        self.root.after(200, self._tick)
        while not self.events.empty():
            event = self.events.get_nowait()
            if isinstance(event, Exception):
                if not self._tray_failed:
                    self._tray_failed = True
                    self._show_error(event)
                    self.controller.request_exit()
            else:
                self._action(event)
        result = self.controller.poll()
        if result is not None and result.code != 0:
            if result.code == ALREADY_RUNNING_EXIT_CODE:
                self._show_error(RuntimeBusyError())
            else:
                dialog(
                    self.root,
                    "Jarvis stopped unexpectedly",
                    f"{result.mode.value.title()} exited with code {result.code}.\n\n"
                    f"Startup details are saved in:\n{self.log_path}",
                )
        self.tray.update(self.controller.mode, exiting=self.controller.exiting)
        if self.settings is not None and self.settings.window.winfo_exists():
            self.settings.refresh()
        if self.controller.can_exit:
            self.root.quit()


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("The Jarvis tray launcher requires Windows 11.")
    directory = Path(os.environ["LOCALAPPDATA"]) / "JarvisLauncher"
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        handlers=[
            RotatingFileHandler(
                directory / "launcher.log",
                maxBytes=LAUNCHER_LOG_MAX_BYTES,
                backupCount=1,
                encoding="utf-8",
                delay=True,
            )
        ],
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    guard = acquire_single_instance(name=LAUNCHER_MUTEX)
    root: tk.Tk | None = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.iconbitmap(str(ICON_PATH))
        if isinstance(guard, AlreadyRunning):
            dialog(
                root,
                "Launcher is already running",
                "Jarvis Launcher is already in the Windows notification area.\n"
                "Right-click its icon to choose a mode or open Settings.",
            )
            raise SystemExit(ALREADY_RUNNING_EXIT_CODE)
        LauncherApp(root, directory, Path(__file__).resolve().parents[3]).run()
    except (OSError, ValueError, RuntimeError) as error:
        logger.exception("Launcher failed")
        if root is not None:
            dialog(root, "Could not start the launcher", str(error))
        raise SystemExit(1) from error
    finally:
        if root is not None:
            root.destroy()
        if not isinstance(guard, AlreadyRunning):
            guard.release()


if __name__ == "__main__":
    main()
