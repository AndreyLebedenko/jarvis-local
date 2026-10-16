from unittest.mock import Mock

import pytest

import jarvis.launcher.__main__ as launcher
from jarvis.core.single_instance import AlreadyRunning
from jarvis.launcher.tray import SHOW_TOUCHSTRIP


def test_tray_actions_functional_start_refusal_and_orderly_exit(monkeypatch, tmp_path):
    home = tmp_path / "installed home"
    for filename in (".venv/Scripts/python.exe", "src/jarvis/launcher/runtime.py"):
        path = home / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    child = Mock()
    child.poll.return_value = None
    spawn = Mock(return_value=child)
    notice = Mock()
    monkeypatch.setattr(launcher, "ChildRuntime", spawn)
    monkeypatch.setattr(launcher, "runtime_is_busy", lambda: False)
    monkeypatch.setattr(launcher, "WindowsTray", Mock())
    monkeypatch.setattr(launcher, "dialog", notice)
    root = Mock()
    app = launcher.LauncherApp(root, tmp_path / "preferences", home)
    app._tick()
    spawn.assert_not_called()
    app.events.put(1)
    app._tick()
    spawn.assert_called_once()
    app.events.put(2)
    app._tick()
    spawn.assert_called_once()
    assert notice.call_args.args[1] == "Jarvis is already running"
    child.send.assert_not_called()
    app.events.put(4)
    app._tick()
    child.send.assert_called_once_with({"command": "shutdown"})
    root.quit.assert_not_called()
    child.poll.return_value = 0
    app._tick()
    root.quit.assert_called_once_with()


def test_show_touchstrip_action_is_ignored_while_idle_and_sent_while_running(
    monkeypatch, tmp_path
):
    home = tmp_path / "installed home"
    for filename in (".venv/Scripts/python.exe", "src/jarvis/launcher/runtime.py"):
        path = home / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    child = Mock()
    child.poll.return_value = None
    monkeypatch.setattr(launcher, "ChildRuntime", Mock(return_value=child))
    monkeypatch.setattr(launcher, "runtime_is_busy", lambda: False)
    monkeypatch.setattr(launcher, "WindowsTray", Mock())
    app = launcher.LauncherApp(Mock(), tmp_path / "preferences", home)
    app._action(SHOW_TOUCHSTRIP)
    child.send.assert_not_called()
    app._action(2)
    app._action(SHOW_TOUCHSTRIP)
    child.send.assert_called_once_with({"command": "touchstrip", "visible": True})


def test_duplicate_launcher_shows_a_dialog_without_constructing_another_tray(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(
        launcher, "acquire_single_instance", lambda **kwargs: AlreadyRunning()
    )
    monkeypatch.setattr(launcher.logging, "basicConfig", Mock())
    root = Mock()
    monkeypatch.setattr(launcher.tk, "Tk", lambda: root)
    notice = Mock()
    app_factory = Mock()
    monkeypatch.setattr(launcher, "dialog", notice)
    monkeypatch.setattr(launcher, "LauncherApp", app_factory)
    with pytest.raises(SystemExit) as result:
        launcher.main()
    assert result.value.code == 3
    assert notice.call_args.args[1] == "Launcher is already running"
    app_factory.assert_not_called()
    root.destroy.assert_called_once_with()


def test_launcher_log_is_bounded_with_one_backup(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(
        launcher, "acquire_single_instance", lambda **kwargs: AlreadyRunning()
    )
    configure = Mock()
    monkeypatch.setattr(launcher.logging, "basicConfig", configure)
    monkeypatch.setattr(launcher.tk, "Tk", Mock)
    monkeypatch.setattr(launcher, "dialog", Mock())
    with pytest.raises(SystemExit):
        launcher.main()
    (handler,) = configure.call_args.kwargs["handlers"]
    assert handler.baseFilename == str(tmp_path / "JarvisLauncher" / "launcher.log")
    assert handler.maxBytes == launcher.LAUNCHER_LOG_MAX_BYTES
    assert handler.backupCount == 1
