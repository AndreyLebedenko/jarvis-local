import tkinter as tk
from unittest.mock import Mock

import pytest
from png_fixtures import make_ico, make_png

import jarvis.launcher.__main__ as launcher
import jarvis.launcher.window as window_module
from jarvis.core.brand_icon import ICO_FRAME_SIZES
from jarvis.launcher.branding import RegenerationResult
from jarvis.launcher.identity import DEFAULT_IDENTITY, LauncherIdentity
from jarvis.launcher.window import ICON_PATH, set_window_icon

GOOD_ICO = make_ico([(side, make_png(side, side)) for side in ICO_FRAME_SIZES])


@pytest.fixture
def home(tmp_path):
    root = tmp_path / "installed home"
    for filename in (".venv/Scripts/python.exe", "src/jarvis/launcher/runtime.py"):
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return root


@pytest.fixture
def parts(monkeypatch):
    child = Mock()
    child.poll.return_value = None
    tray_class, dialog_mock = Mock(), Mock()
    monkeypatch.setattr(launcher, "ChildRuntime", Mock(return_value=child))
    monkeypatch.setattr(launcher, "runtime_is_busy", lambda: False)
    monkeypatch.setattr(launcher, "WindowsTray", tray_class)
    monkeypatch.setattr(launcher, "dialog", dialog_mock)
    monkeypatch.setattr(launcher, "set_window_icon", Mock())
    return tray_class, dialog_mock


def make_app(home, tmp_path):
    return launcher.LauncherApp(Mock(), tmp_path / "preferences", home)


def brand(home, text):
    (home / "config.toml").write_text(text, encoding="utf-8")


def test_an_unbranded_home_gives_the_tray_the_default_identity(home, tmp_path, parts):
    tray_class, _ = parts

    app = make_app(home, tmp_path)

    args = tray_class.call_args.args
    assert (args[0], args[3]) == (DEFAULT_IDENTITY.icon, "Jarvis")
    assert app.identity == DEFAULT_IDENTITY


def test_a_branded_home_gives_the_tray_its_name_and_icon(home, tmp_path, parts):
    tray_class, _ = parts
    brand(home, '[brand]\nname = "Work"\n')
    (home / "brand").mkdir()
    (home / "brand" / "brand.ico").write_bytes(GOOD_ICO)

    app = make_app(home, tmp_path)

    args = tray_class.call_args.args
    assert (args[0], args[3]) == (home / "brand" / "brand.ico", "Work")
    launcher.set_window_icon.assert_called_with(app.root, home / "brand" / "brand.ico")


def test_starting_a_mode_picks_up_a_name_edited_in_the_config(home, tmp_path, parts):
    app = make_app(home, tmp_path)
    brand(home, '[brand]\nname = "Work"\n')

    app._action(1)

    app.tray.set_identity.assert_called_with("Work", DEFAULT_IDENTITY.icon)
    assert app.identity.name == "Work"


def test_an_invalid_brand_at_mode_start_falls_back_and_still_starts(
    home, tmp_path, parts
):
    app = make_app(home, tmp_path)
    brand(home, '[brand]\nmonogram = "AB"\n')

    app._action(1)

    app.tray.set_identity.assert_called_with("Jarvis", DEFAULT_IDENTITY.icon)
    launcher.ChildRuntime.assert_called_once()


def test_a_home_change_reloads_the_identity_and_clears_the_icon_status(
    home, tmp_path, parts
):
    app = make_app(home, tmp_path)
    app.regeneration.status = "Generated brand icons in somewhere"
    other = tmp_path / "other"
    (other / ".venv/Scripts").mkdir(parents=True)
    (other / "src/jarvis/launcher").mkdir(parents=True)
    (other / ".venv/Scripts/python.exe").write_text("", encoding="utf-8")
    (other / "src/jarvis/launcher/runtime.py").write_text("", encoding="utf-8")
    brand(other, '[brand]\nname = "Other"\n')
    app.controller.set_home(other)

    app._home_changed()

    assert app.regeneration.status == ""
    app.tray.set_identity.assert_called_with("Other", DEFAULT_IDENTITY.icon)


def test_the_open_settings_window_is_re_skinned_on_reload(home, tmp_path, parts):
    app = make_app(home, tmp_path)
    app.settings = Mock()
    app.settings.window.winfo_exists.return_value = True
    brand(home, '[brand]\nname = "Work"\n')

    app.refresh_identity()

    app.settings.apply_identity.assert_called_once_with(
        LauncherIdentity("Work", DEFAULT_IDENTITY.icon)
    )


def test_a_finished_regeneration_reloads_the_identity_in_the_tick(
    home, tmp_path, parts
):
    app = make_app(home, tmp_path)
    brand(home, '[brand]\nname = "Work"\n')
    job = Mock()
    job.poll.return_value = RegenerationResult("Generated brand icons in X")
    app.regeneration._job = job

    app._tick()

    app.tray.set_identity.assert_called_with("Work", DEFAULT_IDENTITY.icon)
    assert app.regeneration.status == "Generated brand icons in X"


def test_a_failed_regeneration_shows_the_exact_message_in_a_branded_dialog(
    home, tmp_path, parts
):
    _, dialog_mock = parts
    app = make_app(home, tmp_path)
    error = ValueError('[brand].icon "x.png": is not a PNG file (bad signature)')
    job = Mock()
    job.poll.return_value = RegenerationResult(str(error), error)
    app.regeneration._job = job

    app._tick()

    args, options = dialog_mock.call_args
    assert args[1:] == ("Could not complete the action", str(error))
    assert options["identity"] == app.identity


def test_the_unexpected_exit_dialog_names_the_selected_instance(home, tmp_path, parts):
    _, dialog_mock = parts
    brand(home, '[brand]\nname = "Work"\n')
    app = make_app(home, tmp_path)
    app._action(1)
    app.controller._runtime[1].poll.return_value = 1

    app._tick()

    assert dialog_mock.call_args.args[1] == "Work stopped unexpectedly"
    assert dialog_mock.call_args.kwargs["identity"].name == "Work"


def chrome_identity(dialog_mock):
    return dialog_mock.call_args.kwargs.get("identity", DEFAULT_IDENTITY)


def test_the_busy_dialog_keeps_the_product_wording_and_default_chrome(
    home, tmp_path, parts
):
    _, dialog_mock = parts
    brand(home, '[brand]\nname = "Work"\n')
    app = make_app(home, tmp_path)
    app._action(1)
    app._action(2)

    assert dialog_mock.call_args.args[1] == "Jarvis is already running"
    assert chrome_identity(dialog_mock) == DEFAULT_IDENTITY
    assert app.identity.name == "Work"


def test_the_busy_exit_code_dialog_also_keeps_the_default_chrome(home, tmp_path, parts):
    _, dialog_mock = parts
    brand(home, '[brand]\nname = "Work"\n')
    app = make_app(home, tmp_path)
    app._action(1)
    app.controller._runtime[1].poll.return_value = launcher.ALREADY_RUNNING_EXIT_CODE

    app._tick()

    assert dialog_mock.call_args.args[1] == "Jarvis is already running"
    assert chrome_identity(dialog_mock) == DEFAULT_IDENTITY


def test_the_launcher_error_dialog_keeps_the_default_chrome(home, tmp_path, parts):
    _, dialog_mock = parts
    brand(home, '[brand]\nname = "Work"\n')
    app = make_app(home, tmp_path)

    app._callback_error(ValueError, ValueError("boom"), None)

    assert dialog_mock.call_args.args[1:] == ("Launcher error", "boom")
    assert chrome_identity(dialog_mock) == DEFAULT_IDENTITY


def test_the_about_dialog_keeps_the_product_chrome(monkeypatch):
    shown = Mock()
    monkeypatch.setattr(window_module, "dialog", shown)

    window_module.SettingsWindow._about(Mock())

    assert shown.call_args.args[1] == "Jarvis"
    assert shown.call_args.kwargs.get("identity", DEFAULT_IDENTITY) == DEFAULT_IDENTITY


def test_a_window_icon_that_tk_rejects_falls_back_to_the_packaged_icon():
    window = Mock()
    window.iconbitmap.side_effect = [tk.TclError("bad"), None]

    set_window_icon(window, ICON_PATH.with_name("broken.ico"))

    assert [call.args[0] for call in window.iconbitmap.call_args_list] == [
        str(ICON_PATH.with_name("broken.ico")),
        str(ICON_PATH),
    ]
