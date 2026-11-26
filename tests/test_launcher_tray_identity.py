from pathlib import Path
from unittest.mock import Mock

import pytest

from jarvis.core.config import BRAND_NAME_MAX_LENGTH
from jarvis.launcher.identity import DEFAULT_IDENTITY
from jarvis.launcher.model import LaunchMode
from jarvis.launcher.tray import (
    NIM_MODIFY,
    WM_REFRESH,
    WindowsTray,
    tray_tooltip,
)

SZ_TIP_USABLE = 127


@pytest.mark.parametrize(
    ("mode", "exiting", "expected"),
    [
        (None, False, "Work - waiting for a mode"),
        (LaunchMode.ASSISTANT, False, "Work - Assistant"),
        (LaunchMode.MCP, False, "Work - Mcp"),
        (LaunchMode.MCP, True, "Work - shutting down"),
        (None, True, "Work - shutting down"),
    ],
)
def test_the_tooltip_names_the_brand_and_the_state(mode, exiting, expected):
    assert tray_tooltip("Work", mode, exiting) == expected


def test_the_default_name_keeps_the_original_tooltips():
    assert tray_tooltip("Jarvis", None, False) == "Jarvis - waiting for a mode"
    assert tray_tooltip("Jarvis", LaunchMode.ASSISTANT, False) == "Jarvis - Assistant"


def test_the_longest_possible_tooltip_fits_the_notification_area_limit():
    name = "W" * BRAND_NAME_MAX_LENGTH
    longest = max(
        len(tray_tooltip(name, mode, exiting))
        for mode in (None, LaunchMode.ASSISTANT, LaunchMode.MCP)
        for exiting in (False, True)
    )

    assert longest <= SZ_TIP_USABLE


def make_tray(tmp_path, name="Jarvis", icon=None):
    tray = WindowsTray(
        icon or tmp_path / "icon.ico",
        lambda action: None,
        pytest.fail,
        name=name,
    )
    tray._user32 = Mock()
    tray._user32.LoadImageW.return_value = 77
    tray._shell32 = Mock()
    tray._hwnd = 42
    return tray


def test_a_branded_tray_starts_with_the_branded_idle_tooltip(tmp_path):
    tray = make_tray(tmp_path, name="Work")

    assert tray._tooltip == "Work - waiting for a mode"
    tray.update(None)
    tray._user32.PostMessageW.assert_not_called()


def test_updates_use_the_current_brand_name(tmp_path):
    tray = make_tray(tmp_path, name="Work")

    tray.update(LaunchMode.MCP)

    assert tray._tooltip == "Work - Mcp"


def test_a_new_identity_posts_one_refresh_and_keeps_the_mode_in_the_tooltip(tmp_path):
    tray = make_tray(tmp_path)
    tray.update(LaunchMode.ASSISTANT)
    tray._user32.PostMessageW.reset_mock()

    tray.set_identity("Work", tmp_path / "work.ico")

    assert tray._tooltip == "Work - Assistant"
    tray._user32.PostMessageW.assert_called_once_with(42, WM_REFRESH, 0, 0)


def test_the_same_identity_still_reloads_the_icon_because_the_file_may_be_new(
    tmp_path,
):
    tray = make_tray(tmp_path, name="Work", icon=tmp_path / "work.ico")
    tray._icon, tray._loaded_icon_path = 55, tmp_path / "work.ico"

    tray.set_identity("Work", tmp_path / "work.ico")
    tray._handle_message(42, WM_REFRESH, 0, 0)

    tray._user32.PostMessageW.assert_called_once_with(42, WM_REFRESH, 0, 0)
    tray._user32.LoadImageW.assert_called_once()
    tray._user32.DestroyIcon.assert_called_once_with(55)


def test_an_icon_only_change_refreshes_too(tmp_path):
    tray = make_tray(tmp_path, name="Work", icon=tmp_path / "a.ico")

    tray.set_identity("Work", tmp_path / "b.ico")

    tray._user32.PostMessageW.assert_called_once_with(42, WM_REFRESH, 0, 0)


def test_the_icon_is_reloaded_once_per_identity_change(tmp_path):
    tray = make_tray(tmp_path, name="Work", icon=tmp_path / "a.ico")
    tray._icon, tray._loaded_icon_path = 55, tmp_path / "a.ico"
    tray.set_identity("Work", tmp_path / "a.ico")

    tray._handle_message(42, WM_REFRESH, 0, 0)
    tray._handle_message(42, WM_REFRESH, 0, 0)

    tray._user32.LoadImageW.assert_called_once()


def test_the_refresh_loads_the_new_icon_modifies_and_frees_the_old_one(tmp_path):
    tray = make_tray(tmp_path, icon=tmp_path / "old.ico")
    tray._icon, tray._loaded_icon_path = 55, tmp_path / "old.ico"
    tray.set_identity("Work", tmp_path / "work.ico")

    assert tray._handle_message(42, WM_REFRESH, 0, 0) == 0

    assert tray._user32.LoadImageW.call_args.args[1] == str(tmp_path / "work.ico")
    assert tray._data.hIcon == 77
    assert tray._data.szTip == "Work - waiting for a mode"
    assert tray._shell32.Shell_NotifyIconW.call_args.args[0] == NIM_MODIFY
    tray._user32.DestroyIcon.assert_called_once_with(55)


def test_a_tooltip_only_refresh_does_not_reload_the_icon(tmp_path):
    tray = make_tray(tmp_path, icon=tmp_path / "old.ico")
    tray._icon, tray._loaded_icon_path = 55, tmp_path / "old.ico"
    tray.update(LaunchMode.MCP)

    tray._handle_message(42, WM_REFRESH, 0, 0)

    tray._user32.LoadImageW.assert_not_called()
    tray._user32.DestroyIcon.assert_not_called()


def test_an_icon_that_cannot_be_loaded_falls_back_to_the_packaged_one(tmp_path):
    tray = make_tray(tmp_path, icon=tmp_path / "old.ico")
    tray._icon, tray._loaded_icon_path = 55, tmp_path / "old.ico"
    tray._user32.LoadImageW.side_effect = [0, 88]
    tray.set_identity("Work", tmp_path / "broken.ico")

    tray._handle_message(42, WM_REFRESH, 0, 0)

    paths = [call.args[1] for call in tray._user32.LoadImageW.call_args_list]
    assert paths == [str(tmp_path / "broken.ico"), str(DEFAULT_IDENTITY.icon)]
    assert tray._data.hIcon == 88


def test_when_no_icon_can_be_loaded_the_old_icon_and_the_tray_stay(tmp_path):
    tray = make_tray(tmp_path, icon=tmp_path / "old.ico")
    tray._icon, tray._loaded_icon_path = 55, tmp_path / "old.ico"
    tray._data.hIcon = 55
    tray._user32.LoadImageW.return_value = 0
    tray.set_identity("Work", tmp_path / "broken.ico")

    tray._handle_message(42, WM_REFRESH, 0, 0)

    assert tray._data.hIcon == 55
    assert tray._data.szTip == "Work - waiting for a mode"
    tray._user32.DestroyIcon.assert_not_called()
    assert tray._shell32.Shell_NotifyIconW.call_args.args[0] == NIM_MODIFY


def test_the_packaged_icon_is_a_path_the_tray_can_load():
    assert isinstance(DEFAULT_IDENTITY.icon, Path)
    assert DEFAULT_IDENTITY.icon.is_file()
