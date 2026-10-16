import io
import json
from pathlib import Path

import pytest

from jarvis.launcher.model import (
    LauncherController,
    LauncherSettings,
    LaunchMode,
    RuntimeBusyError,
    SettingsStore,
    launch_command,
    validate_home,
)
from jarvis.ui.desktop_control import StdinDesktopControl, dispatch_command


@pytest.fixture
def home(tmp_path: Path) -> Path:
    root = tmp_path / "Jarvis home"
    for name in (".venv/Scripts/python.exe", "src/jarvis/launcher/runtime.py"):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    return root


class FakeProcess:
    def __init__(self) -> None:
        self.exit_code: int | None = None
        self.commands: list[dict[str, str | bool]] = []

    def poll(self) -> int | None:
        return self.exit_code

    def send(self, command: dict[str, str | bool]) -> None:
        self.commands.append(command)


def make_controller(home: Path, tmp_path: Path):
    process = FakeProcess()
    requests = []

    def launch(request):
        requests.append(request)
        return process

    store = SettingsStore(tmp_path / "preferences.json")
    controller = LauncherController(
        LauncherSettings(home), store, launch, runtime_busy=lambda: False
    )
    return controller, process, requests


def test_preferences_default_without_creating_a_file(home, tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.load(home) == LauncherSettings(home, touchstrip=True)
    assert not store.path.exists()


def test_preferences_round_trip_unicode_and_spaces(home, tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    settings = LauncherSettings(home / "Проект один", touchstrip=False)
    store.save(settings)
    assert store.load(home) == settings
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "payload",
    [
        "{broken",
        "[]",
        "{}",
        '{"home": 3, "touchstrip": true}',
        '{"home": "relative", "touchstrip": true}',
        '{"home": "C:/Jarvis", "touchstrip": "false"}',
        '{"home": "C:/Jarvis", "touchstrip": 1}',
    ],
)
def test_invalid_preferences_are_reported_without_overwriting(home, tmp_path, payload):
    store = SettingsStore(tmp_path / "settings.json")
    store.path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="settings"):
        store.load(home)
    assert store.path.read_text(encoding="utf-8") == payload


def test_home_validation_accepts_an_installed_home(home):
    assert validate_home(home) == home.resolve()


def test_home_rejects_cwd_dependent_relative_paths():
    with pytest.raises(ValueError, match="absolute"):
        validate_home(Path("relative installation"))


def test_failed_atomic_preference_write_preserves_the_previous_file(
    home, tmp_path, monkeypatch
):
    store = SettingsStore(tmp_path / "settings.json")
    store.save(LauncherSettings(home))
    original = store.path.read_bytes()

    def reject_replace(source, destination):
        raise OSError("disk write refused")

    monkeypatch.setattr("jarvis.launcher.model.os.replace", reject_replace)
    with pytest.raises(OSError, match="disk write refused"):
        store.save(LauncherSettings(home, touchstrip=False))
    assert store.path.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "missing", [".venv/Scripts/python.exe", "src/jarvis/launcher/runtime.py"]
)
def test_home_validation_names_the_missing_requirement(home, missing):
    (home / missing).unlink()
    with pytest.raises(ValueError, match="Jarvis Home Folder"):
        validate_home(home)


@pytest.mark.parametrize("mode", list(LaunchMode))
@pytest.mark.parametrize("touchstrip", [True, False])
def test_command_selects_the_target_installation_mode_and_touchstrip(
    home, mode, touchstrip
):
    command = launch_command(LauncherSettings(home, touchstrip), mode)
    assert command == [
        str(home / ".venv/Scripts/python.exe"),
        "-m",
        "jarvis.launcher.runtime",
        "--mode",
        mode.value,
        "--touchstrip",
        "on" if touchstrip else "off",
    ]


def test_launcher_starts_idle_without_spawning_or_loading_a_model(home, tmp_path):
    controller, _, requests = make_controller(home, tmp_path)
    assert controller.mode is None
    assert controller.poll() is None
    assert requests == []


@pytest.mark.parametrize("mode", list(LaunchMode))
def test_start_passes_the_saved_home_mode_and_preferences(home, tmp_path, mode):
    controller, _, requests = make_controller(home, tmp_path)
    controller.start(mode)
    assert controller.mode is mode
    assert requests[0].settings == controller.settings
    assert requests[0].mode is mode


@pytest.mark.parametrize("requested", list(LaunchMode))
def test_either_mode_is_refused_while_the_owned_runtime_lives(
    home, tmp_path, requested
):
    controller, process, requests = make_controller(home, tmp_path)
    controller.start(LaunchMode.ASSISTANT)
    with pytest.raises(RuntimeBusyError, match="finish"):
        controller.start(requested)
    assert len(requests) == 1
    assert process.commands == []


def test_external_runtime_prevents_a_start_without_being_controlled(home, tmp_path):
    controller, _, requests = make_controller(home, tmp_path)
    controller.runtime_busy = lambda: True
    with pytest.raises(RuntimeBusyError):
        controller.start(LaunchMode.MCP)
    assert requests == []


def test_finishing_a_runtime_leaves_launcher_idle_and_allows_another_mode(
    home, tmp_path
):
    controller, process, requests = make_controller(home, tmp_path)
    controller.start(LaunchMode.ASSISTANT)
    process.exit_code = 0
    result = controller.poll()
    assert result.mode is LaunchMode.ASSISTANT
    assert result.code == 0
    assert controller.mode is None
    process.exit_code = None
    controller.start(LaunchMode.MCP)
    assert len(requests) == 2


def test_touchstrip_changes_live_and_persists_without_restarting(home, tmp_path):
    controller, process, requests = make_controller(home, tmp_path)
    controller.start(LaunchMode.MCP)
    controller.set_touchstrip(False)
    assert process.commands == [{"command": "touchstrip", "visible": False}]
    assert controller.store.load(home).touchstrip is False
    assert len(requests) == 1


def test_touchstrip_can_be_saved_while_idle(home, tmp_path):
    controller, process, _ = make_controller(home, tmp_path)
    controller.set_touchstrip(False)
    assert controller.settings.touchstrip is False
    assert process.commands == []


def test_show_touchstrip_reveals_it_live_without_changing_the_saved_preference(
    home, tmp_path
):
    controller, process, _ = make_controller(home, tmp_path)
    controller.set_touchstrip(False)
    controller.start(LaunchMode.ASSISTANT)
    controller.show_touchstrip()
    assert process.commands == [{"command": "touchstrip", "visible": True}]
    assert controller.settings.touchstrip is False
    assert controller.store.load(home).touchstrip is False


def test_show_touchstrip_without_a_running_runtime_does_nothing(home, tmp_path):
    controller, process, requests = make_controller(home, tmp_path)
    controller.show_touchstrip()
    assert process.commands == []
    assert requests == []
    assert not controller.store.path.exists()


def test_home_cannot_change_until_owned_runtime_exits(home, tmp_path):
    controller, process, _ = make_controller(home, tmp_path)
    controller.start(LaunchMode.ASSISTANT)
    with pytest.raises(RuntimeBusyError):
        controller.set_home(home)
    assert process.commands == []


def test_home_is_validated_and_persisted_when_idle(home, tmp_path):
    controller, _, _ = make_controller(home, tmp_path)
    controller.set_home(home)
    assert controller.store.load(home).home == home.resolve()


def test_spawn_failure_leaves_launcher_idle(home, tmp_path):
    controller, _, _ = make_controller(home, tmp_path)

    def fail(request):
        raise OSError("cannot create process")

    controller.launch = fail
    with pytest.raises(OSError, match="cannot create process"):
        controller.start(LaunchMode.MCP)
    assert controller.mode is None


def test_exit_requests_orderly_shutdown_once_and_waits_for_completion(home, tmp_path):
    controller, process, _ = make_controller(home, tmp_path)
    controller.start(LaunchMode.MCP)
    controller.request_exit()
    controller.request_exit()
    assert process.commands == [{"command": "shutdown"}]
    assert not controller.can_exit
    with pytest.raises(RuntimeBusyError):
        controller.start(LaunchMode.ASSISTANT)
    process.exit_code = 0
    controller.poll()
    assert controller.can_exit


def test_exit_while_idle_does_not_touch_an_external_runtime(home, tmp_path):
    controller, process, _ = make_controller(home, tmp_path)
    controller.runtime_busy = lambda: True
    controller.request_exit()
    assert controller.can_exit
    assert process.commands == []


@pytest.mark.parametrize("visible", [True, False])
def test_private_command_dispatches_touchstrip_visibility(visible):
    visibility = []
    assert dispatch_command(
        json.dumps({"command": "touchstrip", "visible": visible}),
        lambda: pytest.fail("shutdown was not requested"),
        visibility.append,
    )
    assert visibility == [visible]


def test_private_command_dispatches_shutdown_and_ends_reader():
    shutdowns = []
    assert not dispatch_command(
        '{"command":"shutdown"}',
        lambda: shutdowns.append(True),
        lambda value: pytest.fail("visibility was not requested"),
    )
    assert shutdowns == [True]


@pytest.mark.parametrize(
    "payload",
    ["[]", "{}", "{bad", '{"command":"touchstrip","visible":1}', '{"command":"erase"}'],
)
def test_invalid_private_commands_fail_explicitly(payload):
    with pytest.raises(ValueError):
        dispatch_command(payload, lambda: None, lambda value: None)


def test_pipe_eof_requests_orderly_shutdown_of_an_orphaned_runtime():
    shutdowns = []
    control = StdinDesktopControl(io.StringIO(""))
    control.consume(lambda: shutdowns.append(True), lambda visible: None)
    assert shutdowns == [True]


def test_private_pipe_functional_sequence_touchstrip_then_shutdown():
    events = []
    control = StdinDesktopControl(
        io.StringIO(
            '{"command":"touchstrip","visible":false}\n'
            '{"command":"touchstrip","visible":true}\n'
            '{"command":"shutdown"}\n'
        )
    )
    control.consume(lambda: events.append("shutdown"), events.append)
    assert events == [False, True, "shutdown"]


def test_launcher_functional_lifecycle_persists_visibility_and_waits_for_orderly_exit(
    home, tmp_path
):
    controller, process, requests = make_controller(home, tmp_path)
    controller.set_home(home)
    controller.start(LaunchMode.ASSISTANT)
    controller.set_touchstrip(False)
    with pytest.raises(RuntimeBusyError):
        controller.start(LaunchMode.MCP)
    assert controller.poll() is None
    controller.request_exit()
    assert not controller.can_exit
    events = []
    private_input = io.StringIO(
        "".join(json.dumps(command) + "\n" for command in process.commands)
    )
    StdinDesktopControl(private_input).consume(
        lambda: events.append("shutdown"), events.append
    )
    assert events == [False, "shutdown"]
    process.exit_code = 0
    assert controller.poll().code == 0
    assert controller.can_exit
    assert len(requests) == 1
    reloaded = controller.store.load(home)
    assert reloaded == LauncherSettings(home.resolve(), touchstrip=False)
