import sys
from unittest.mock import MagicMock, Mock

import pytest

from jarvis.launcher.model import LaunchMode
from jarvis.launcher.startup import RUN_KEY, RUN_VALUE, WindowsStartupStore
from jarvis.launcher.tray import WM_RBUTTONUP, WM_TRAY, WindowsTray


@pytest.fixture
def registry(monkeypatch):
    registry = MagicMock()
    registry.REG_SZ = 1
    key = registry.OpenKey.return_value.__enter__.return_value = Mock()
    registry.CreateKey.return_value.__enter__.return_value = key
    registry.QueryValueEx.return_value = ("launcher command", registry.REG_SZ)
    monkeypatch.setitem(sys.modules, "winreg", registry)
    return registry


def test_startup_reads_only_the_named_current_user_value(registry):
    assert WindowsStartupStore().read() == "launcher command"
    registry.OpenKey.assert_called_once_with(registry.HKEY_CURRENT_USER, RUN_KEY)
    assert registry.QueryValueEx.call_args.args[1] == RUN_VALUE


def test_absent_startup_value_is_disabled_and_delete_is_idempotent(registry):
    registry.OpenKey.side_effect = FileNotFoundError
    assert WindowsStartupStore().read() is None
    WindowsStartupStore().delete()


def test_non_string_startup_data_is_reported(registry):
    registry.QueryValueEx.return_value = (123, 4)
    with pytest.raises(ValueError, match="not a string"):
        WindowsStartupStore().read()


def test_startup_only_writes_and_deletes_its_own_named_value(registry):
    store = WindowsStartupStore()
    store.write('"C:\\Jarvis\\pythonw.exe" -m jarvis.launcher')
    assert registry.SetValueEx.call_args.args[1:] == (
        RUN_VALUE,
        0,
        registry.REG_SZ,
        '"C:\\Jarvis\\pythonw.exe" -m jarvis.launcher',
    )
    store.delete()
    assert registry.DeleteValue.call_args.args[1] == RUN_VALUE


def test_registry_permission_failures_are_not_hidden(registry):
    registry.OpenKey.side_effect = PermissionError("registry denied")
    with pytest.raises(PermissionError, match="registry denied"):
        WindowsStartupStore().read()


@pytest.mark.parametrize("mode", [None, LaunchMode.ASSISTANT, LaunchMode.MCP])
def test_right_click_menu_has_the_owner_order_and_one_active_mode(mode, tmp_path):
    actions = []
    tray = WindowsTray(tmp_path / "icon.ico", actions.append, pytest.fail)
    tray._mode = mode
    tray._user32 = Mock()
    tray._user32.CreatePopupMenu.return_value = 99
    tray._user32.TrackPopupMenu.return_value = 3
    assert tray._handle_message(42, WM_TRAY, 0, WM_RBUTTONUP) == 0
    entries = [call.args for call in tray._user32.AppendMenuW.call_args_list]
    assert [(entry[2], entry[3]) for entry in entries] == [
        (1, "Assistant"),
        (2, "MCP"),
        (0, ""),
        (3, "Settings"),
        (0, ""),
        (4, "Exit"),
    ]
    checked = [entry[2] for entry in entries if entry[1] == 8]
    assert checked == (
        [] if mode is None else [1 if mode is LaunchMode.ASSISTANT else 2]
    )
    assert actions == [3]
    tray._user32.DestroyMenu.assert_called_once_with(99)


def test_dismissing_the_tray_menu_does_not_dispatch_an_action(tmp_path):
    actions = []
    tray = WindowsTray(tmp_path / "icon.ico", actions.append, pytest.fail)
    tray._user32 = Mock()
    tray._user32.TrackPopupMenu.return_value = 0
    tray._popup(42)
    assert actions == []
    tray._user32.DestroyMenu.assert_called_once()


def test_callback_failure_is_reported_without_crossing_the_native_boundary(tmp_path):
    errors = []
    tray = WindowsTray(tmp_path / "icon.ico", lambda action: None, errors.append)
    tray._user32 = Mock()
    tray._user32.CreatePopupMenu.side_effect = RuntimeError("menu failure")
    assert tray._window_proc(42, WM_TRAY, 0, WM_RBUTTONUP) == 0
    assert str(errors[0]) == "menu failure"
