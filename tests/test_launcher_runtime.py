import io
import json
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

from jarvis import app
from jarvis.core.run_mode import RunMode
from jarvis.core.single_instance import (
    AlreadyRunning,
    MutexCreation,
    acquire_single_instance,
)
from jarvis.launcher.model import LauncherSettings, LaunchMode, LaunchRequest
from jarvis.launcher.process import ChildRuntime, runtime_is_busy
from jarvis.launcher.runtime import main as runtime_main
from jarvis.launcher.startup import StartupRegistration
from jarvis.ui.desktop_control import StdinDesktopControl
from jarvis.ui.status_console import StatusConsoleWindow


class FakeStartupStore:
    def __init__(self) -> None:
        self.value: str | None = None

    def read(self) -> str | None:
        return self.value

    def write(self, command: str) -> None:
        self.value = command

    def delete(self) -> None:
        self.value = None


def test_autostart_is_explicit_current_user_registration_and_contains_no_mode():
    store = FakeStartupStore()
    registration = StartupRegistration(
        store, Path("C:/Jarvis home/.venv/Scripts/pythonw.exe")
    )
    assert not registration.enabled
    registration.set_enabled(True)
    assert registration.enabled
    assert (
        store.value
        == '"C:\\Jarvis home\\.venv\\Scripts\\pythonw.exe" -m jarvis.launcher'
    )
    assert "--mode" not in store.value
    registration.set_enabled(False)
    registration.set_enabled(False)
    assert not registration.enabled


def test_autostart_does_not_claim_another_installations_command_is_enabled():
    store = FakeStartupStore()
    store.value = '"C:\\Old Jarvis\\pythonw.exe" -m jarvis.launcher'
    registration = StartupRegistration(store, Path("C:/Current Jarvis/pythonw.exe"))
    assert not registration.enabled
    registration.set_enabled(True)
    assert registration.enabled


@pytest.mark.parametrize("mode", ["assistant", "mcp"])
@pytest.mark.parametrize("touchstrip", ["on", "off"])
def test_child_uses_the_canonical_main_guard_and_forwards_private_control(
    monkeypatch, mode, touchstrip
):
    calls = []
    monkeypatch.setattr(
        app, "main", lambda argv, **kwargs: calls.append((argv, kwargs))
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    runtime_main(["--mode", mode, "--touchstrip", touchstrip])
    command, kwargs = calls[0]
    assert command == (
        ["--status-console", "--mcp-mode"] if mode == "mcp" else ["--status-console"]
    )
    assert kwargs["desktop_control"].touchstrip_visible is (touchstrip == "on")
    assert callable(kwargs["show_message_box"])


def test_child_refuses_to_run_without_its_private_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    with pytest.raises(RuntimeError, match="command pipe"):
        runtime_main(["--mode", "assistant", "--touchstrip", "off"])


def test_canonical_main_passes_control_only_to_the_console(monkeypatch):
    calls = []
    control = StdinDesktopControl(io.StringIO(""))
    monkeypatch.setattr(
        app, "run_with_status_console", lambda **kwargs: calls.append(kwargs)
    )
    app.main(["--status-console", "--mcp-mode"], desktop_control=control)
    assert calls == [
        {
            "include_touchstrip": True,
            "debug": False,
            "run_mode": RunMode.MCP,
            "desktop_control": control,
        }
    ]


def test_runtime_probe_releases_the_existing_global_guard(monkeypatch):
    guard = Mock()
    monkeypatch.setattr(
        "jarvis.launcher.process.acquire_single_instance", lambda: guard
    )
    assert runtime_is_busy() is False
    guard.release.assert_called_once_with()
    monkeypatch.setattr(
        "jarvis.launcher.process.acquire_single_instance", AlreadyRunning
    )
    assert runtime_is_busy() is True


def test_launcher_mutex_can_use_its_own_name_without_changing_the_runtime_guard():
    api = Mock()
    api.create.return_value = MutexCreation(42, False)
    guard = acquire_single_instance(api, name=r"Local\Jarvis.Launcher.SingleInstance")
    guard.release()
    api.create.assert_called_once_with(r"Local\Jarvis.Launcher.SingleInstance")
    api.close.assert_called_once_with(42)


def test_child_process_has_explicit_home_private_pipe_hidden_console_and_local_log(
    monkeypatch, tmp_path
):
    captured = {}
    pipe = io.StringIO()
    process = types.SimpleNamespace(stdin=pipe, poll=lambda: None)

    def popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        kwargs["stdout"].write("startup diagnostics\n")
        return process

    monkeypatch.setattr("jarvis.launcher.process.subprocess.Popen", popen)
    home = tmp_path / "Other installation"
    request = LaunchRequest(LauncherSettings(home), LaunchMode.MCP)
    log = tmp_path / "launcher" / "runtime.log"
    child = ChildRuntime(request, log)
    child.send({"command": "touchstrip", "visible": False})
    assert json.loads(pipe.getvalue()) == {"command": "touchstrip", "visible": False}
    assert child.poll() is None
    assert captured["cwd"] == home
    assert captured["command"][0] == str(home / ".venv/Scripts/python.exe")
    assert captured["creationflags"] != 0
    assert captured["env"]["PYTHONUTF8"] == "1"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert log.read_text(encoding="utf-8") == "startup diagnostics\n"
    process.poll = lambda: 0
    assert child.poll() == 0
    assert pipe.closed


def test_missing_pipe_is_an_explicit_process_adapter_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "jarvis.launcher.process.subprocess.Popen",
        lambda *args, **kwargs: types.SimpleNamespace(stdin=None, poll=lambda: 3),
    )
    child = ChildRuntime(
        LaunchRequest(LauncherSettings(tmp_path), LaunchMode.MCP),
        tmp_path / "runtime.log",
    )
    with pytest.raises(RuntimeError, match="pipe"):
        child.send({"command": "shutdown"})
    assert child.poll() == 3


def launch_logging(monkeypatch, tmp_path, text):
    def popen(command, **kwargs):
        kwargs["stdout"].write(text)
        return types.SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)

    monkeypatch.setattr("jarvis.launcher.process.subprocess.Popen", popen)
    request = LaunchRequest(LauncherSettings(tmp_path), LaunchMode.MCP)
    ChildRuntime(request, tmp_path / "logs" / "runtime.log")


def test_first_launch_creates_the_log_and_no_backup(monkeypatch, tmp_path):
    launch_logging(monkeypatch, tmp_path, "first run\n")
    logs = tmp_path / "logs"
    assert (logs / "runtime.log").read_text(encoding="utf-8") == "first run\n"
    assert not (logs / "runtime.previous.log").exists()


def test_second_launch_keeps_the_previous_run_in_the_backup(monkeypatch, tmp_path):
    launch_logging(monkeypatch, tmp_path, "crashed run\n")
    launch_logging(monkeypatch, tmp_path, "second run\n")
    logs = tmp_path / "logs"
    assert (logs / "runtime.log").read_text(encoding="utf-8") == "second run\n"
    assert (logs / "runtime.previous.log").read_text(encoding="utf-8") == (
        "crashed run\n"
    )


def test_third_launch_replaces_the_backup_and_keeps_only_one(monkeypatch, tmp_path):
    for text in ("first\n", "second\n", "third\n"):
        launch_logging(monkeypatch, tmp_path, text)
    logs = tmp_path / "logs"
    assert (logs / "runtime.log").read_text(encoding="utf-8") == "third\n"
    assert (logs / "runtime.previous.log").read_text(encoding="utf-8") == "second\n"
    assert sorted(path.name for path in logs.iterdir()) == [
        "runtime.log",
        "runtime.previous.log",
    ]


class Event:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, callback):
        self.handlers.append(callback)
        return self


def test_touchstrip_close_hides_without_destroying_and_visibility_can_be_restored():
    window = Mock()
    window.events = types.SimpleNamespace(closing=Event(), closed=Event())
    factory = Mock(return_value=window)
    surface = StatusConsoleWindow(window_factory=factory)
    surface.set_initial_visibility(False)
    surface.create()
    assert factory.call_args.kwargs["hidden"] is True
    surface.hide_on_user_close()
    surface.set_visible(True)
    surface.set_visible(False)
    assert window.events.closing.handlers[0]() is False
    window.show.assert_called_once_with()
    assert window.hide.call_count == 2
    window.destroy.assert_not_called()
    surface.close()
    assert window.events.closing.handlers[0]() is True
    window.destroy.assert_called_once_with()
    surface.set_visible(True)
    window.show.assert_called_once_with()


def test_initial_visibility_cannot_be_changed_after_window_creation():
    window = Mock()
    window.events = None
    surface = StatusConsoleWindow(window_factory=Mock(return_value=window))
    with pytest.raises(RuntimeError, match="create"):
        surface.hide_on_user_close()
    surface.create()
    with pytest.raises(RuntimeError, match="before create"):
        surface.set_initial_visibility(False)


def test_private_pipe_failure_is_logged_and_requests_shutdown(caplog):
    shutdown = Mock()
    control = StdinDesktopControl(io.StringIO("{bad\n"))
    control._consume_safely(shutdown, Mock())
    shutdown.assert_called_once_with()
    assert "control pipe failed" in caplog.text


def test_controlled_windows_apply_initial_visibility_and_keep_console_shutdown():
    order = []
    console = Mock()
    touchstrip = Mock()
    touchstrip.set_initial_visibility.side_effect = lambda visible: order.append(
        ("visibility", visible)
    )
    touchstrip.create.side_effect = lambda: order.append("create")
    touchstrip.hide_on_user_close.side_effect = lambda: order.append("keep available")
    api = Mock()
    live = app.LiveStatusConsole(console, touchstrip, api)
    live.create_controlled_windows(
        StdinDesktopControl(io.StringIO(""), touchstrip_visible=False)
    )
    assert order == [("visibility", False), "create", "keep available"]
    console.create.assert_called_once_with(on_closed=api.request_shutdown)


def test_controlled_composition_requires_a_touchstrip_surface():
    live = app.LiveStatusConsole(Mock(), None, Mock())
    with pytest.raises(ValueError, match="touchstrip"):
        live.create_controlled_windows(StdinDesktopControl(io.StringIO("")))
