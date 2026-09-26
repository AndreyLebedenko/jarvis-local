from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.core.config import (
    BackendSettings,
    ConfigError,
    HistorySemanticSettings,
    HistorySettings,
    PiperTtsSettings,
    Settings,
    SileroTtsSettings,
    TtsSettings,
)
from tools import installer

BACKEND_MODEL = "gemma4:12b-it-qat"
SEMANTIC_MODEL = "blaifa/multilingual-e5-large-instruct:latest"
ENDPOINT = "http://localhost:11434"
PYTHON = r"C:\app\.venv\Scripts\python.exe"


def settings_with(
    *,
    backend_model: str = BACKEND_MODEL,
    semantic_enabled: bool = True,
    semantic_model: str = SEMANTIC_MODEL,
    tts_languages: dict | None = None,
) -> Settings:
    settings = Settings(
        backend=BackendSettings(model=backend_model, endpoint=ENDPOINT),
        history=HistorySettings(
            semantic=HistorySemanticSettings(
                enabled=semantic_enabled, model=semantic_model
            )
        ),
    )
    if tts_languages is not None:
        settings = replace(settings, tts=TtsSettings(languages=tts_languages))
    return settings


class FakeCommands:
    def __init__(self, failing_prefixes: tuple[tuple[str, ...], ...] = ()):
        self.commands: list[list[str]] = []
        self._failing_prefixes = failing_prefixes

    def __call__(self, args) -> int:
        self.commands.append(list(args))
        for prefix in self._failing_prefixes:
            if tuple(args[: len(prefix)]) == prefix:
                return 1
        return 0


class FakeOllama:
    def __init__(self, model_names: list[str], reachable: bool = True):
        self.model_names = model_names
        self.reachable = reachable
        self.requested_endpoints: list[str] = []

    def __call__(self, endpoint: str) -> list[str]:
        self.requested_endpoints.append(endpoint)
        if not self.reachable:
            raise installer.OllamaUnavailableError("connection refused")
        return self.model_names


def app_home_with_example_config(tmp_path: Path) -> Path:
    (tmp_path / "config.example.toml").write_text("# example\n", encoding="utf-8")
    return tmp_path


def make_installer(
    tmp_path: Path,
    *,
    settings: Settings | None = None,
    commands: FakeCommands | None = None,
    ollama: FakeOllama | None = None,
    cached_silero_models: set[str] | None = None,
    load_settings=None,
    refresh_import_paths=None,
) -> installer.Installer:
    loaded = settings or settings_with()
    cached = cached_silero_models if cached_silero_models is not None else set()
    return installer.Installer(
        app_home=app_home_with_example_config(tmp_path),
        python_executable=PYTHON,
        run_command=commands or FakeCommands(),
        load_settings=load_settings or (lambda _path: loaded),
        fetch_model_names=ollama or FakeOllama([BACKEND_MODEL, SEMANTIC_MODEL]),
        is_silero_model_cached=lambda route: route.model in cached,
        refresh_import_paths=refresh_import_paths or (lambda: None),
    )


def run_install(tool: installer.Installer) -> tuple[int, list[str]]:
    lines: list[str] = []
    exit_code = installer.install(tool, lines.append)
    return exit_code, lines


def step(name: str, action) -> installer.Step:
    return installer.Step(name=name, action=action)


def fail(message: str, retry_command: str | None = None):
    def action():
        raise installer.StepFailed(message, retry_command=retry_command)

    return action


# Step runner


def test_runner_runs_steps_in_order_and_reports_each_status():
    order: list[str] = []

    def record(name: str, outcome: installer.StepOutcome):
        def action():
            order.append(name)
            return outcome

        return action

    lines: list[str] = []
    exit_code = installer.run_steps(
        [
            step("First", record("First", installer.done())),
            step("Second", record("Second", installer.skipped("already present"))),
        ],
        lines.append,
    )

    assert exit_code == 0
    assert order == ["First", "Second"]
    assert lines == ["[done] First", "[skipped] Second (already present)"]


def test_runner_stops_at_first_failure_with_retry_command_and_exit_code_one():
    later_step_ran = []
    lines: list[str] = []

    exit_code = installer.run_steps(
        [
            step("First", installer.done),
            step("Broken", fail("it broke", retry_command="tool --again")),
            step("Later", lambda: later_step_ran.append(True) or installer.done()),
        ],
        lines.append,
    )

    assert exit_code == 1
    assert later_step_ran == []
    assert lines[:3] == [
        "[done] First",
        "[failed] Broken: it broke",
        "Retry: tool --again",
    ]
    assert "install.cmd" in lines[3]


def test_runner_omits_retry_line_when_failure_has_no_command():
    lines: list[str] = []

    installer.run_steps([step("Broken", fail("no command"))], lines.append)

    assert not any(line.startswith("Retry:") for line in lines)
    assert "install.cmd" in lines[-1]


def test_all_output_lines_are_ascii(tmp_path):
    exit_code, lines = run_install(make_installer(tmp_path))

    assert exit_code == 0
    assert all(line.isascii() for line in lines)


# Whole installation


def test_successful_install_runs_every_step_and_ends_with_launch_hint(tmp_path):
    exit_code, lines = run_install(make_installer(tmp_path))

    assert exit_code == 0
    step_names = [line.split("] ", 1)[1].split(" (")[0] for line in lines[:7]]
    assert step_names == [
        "Install Python dependencies",
        "Install the Jarvis package",
        "Create config.toml",
        "Load settings",
        "Check Ollama models",
        "Cache Silero TTS models",
        "Check Piper TTS models",
    ]
    assert lines[-1] == "Start Jarvis with Jarvis.cmd"


def test_dependencies_install_before_the_package(tmp_path):
    commands = FakeCommands()

    run_install(make_installer(tmp_path, commands=commands))

    assert commands.commands[:2] == [
        [PYTHON, "-m", "pip", "install", "-r", "requirements.txt"],
        [PYTHON, "-m", "pip", "install", "-e", "."],
    ]


class EventLog:
    def __init__(self, failing_prefixes: tuple[tuple[str, ...], ...] = ()):
        self.events: list[str] = []
        self._commands = FakeCommands(failing_prefixes)

    def run_command(self, args) -> int:
        if list(args[:5]) == [PYTHON, "-m", "pip", "install", "-e"]:
            self.events.append("package install")
        return self._commands(args)

    def refresh_import_paths(self) -> None:
        self.events.append("refresh import paths")

    def load_settings(self, _path: Path) -> Settings:
        self.events.append("load settings")
        return settings_with()


def test_import_paths_refresh_after_package_install_before_settings_load(tmp_path):
    log = EventLog()

    exit_code, _lines = run_install(
        make_installer(
            tmp_path,
            commands=log.run_command,
            load_settings=log.load_settings,
            refresh_import_paths=log.refresh_import_paths,
        )
    )

    assert exit_code == 0
    assert log.events == ["package install", "refresh import paths", "load settings"]


def test_import_paths_are_not_refreshed_when_package_install_fails(tmp_path):
    log = EventLog(failing_prefixes=((PYTHON, "-m", "pip", "install", "-e"),))

    exit_code, _lines = run_install(
        make_installer(
            tmp_path,
            commands=log.run_command,
            load_settings=log.load_settings,
            refresh_import_paths=log.refresh_import_paths,
        )
    )

    assert exit_code == 1
    assert log.events == ["package install"]


def test_failed_dependency_install_stops_before_package_install(tmp_path):
    commands = FakeCommands(failing_prefixes=((PYTHON, "-m", "pip", "install", "-r"),))

    exit_code, lines = run_install(make_installer(tmp_path, commands=commands))

    assert exit_code == 1
    assert len(commands.commands) == 1
    assert lines[0].startswith("[failed] Install Python dependencies")
    assert lines[1].startswith("Retry: ")
    assert "pip install -r requirements.txt" in lines[1]
    assert str(tmp_path) in lines[1]


# Config copy


def test_config_is_copied_from_example_when_absent(tmp_path):
    exit_code, lines = run_install(make_installer(tmp_path))

    assert exit_code == 0
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == "# example\n"
    assert "[done] Create config.toml" in lines


def test_existing_config_is_never_overwritten(tmp_path):
    (tmp_path / "config.toml").write_text("# mine\n", encoding="utf-8")

    exit_code, lines = run_install(make_installer(tmp_path))

    assert exit_code == 0
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == "# mine\n"
    assert "[skipped] Create config.toml (already present)" in lines


def test_settings_are_loaded_from_config_toml_in_app_home(tmp_path):
    loaded_paths: list[Path] = []

    def load(path: Path) -> Settings:
        loaded_paths.append(path)
        return settings_with()

    run_install(make_installer(tmp_path, load_settings=load))

    assert loaded_paths == [tmp_path / "config.toml"]


def test_invalid_config_fails_naming_config_toml_and_the_error(tmp_path):
    def load(_path: Path) -> Settings:
        raise ConfigError("[backend].model must be str")

    exit_code, lines = run_install(make_installer(tmp_path, load_settings=load))

    assert exit_code == 1
    failure = next(line for line in lines if line.startswith("[failed]"))
    assert "config.toml" in failure
    assert "[backend].model must be str" in failure


# Model inventory


def test_inventory_includes_backend_and_enabled_semantic_model():
    assert installer.required_ollama_models(settings_with()) == [
        BACKEND_MODEL,
        SEMANTIC_MODEL,
    ]


def test_inventory_excludes_semantic_model_when_semantic_history_disabled():
    settings = settings_with(semantic_enabled=False)

    assert installer.required_ollama_models(settings) == [BACKEND_MODEL]


def test_inventory_deduplicates_semantic_model_equal_to_backend_model():
    settings = settings_with(semantic_model=BACKEND_MODEL)

    assert installer.required_ollama_models(settings) == [BACKEND_MODEL]


@pytest.mark.parametrize(
    ("name", "normalized"),
    [
        ("gemma4", "gemma4:latest"),
        ("gemma4:12b-it-qat", "gemma4:12b-it-qat"),
        (
            "blaifa/multilingual-e5-large-instruct",
            "blaifa/multilingual-e5-large-instruct:latest",
        ),
        ("registry.local:5000/team/model", "registry.local:5000/team/model:latest"),
        ("registry.local:5000/team/model:v2", "registry.local:5000/team/model:v2"),
    ],
)
def test_model_name_without_tag_means_latest(name, normalized):
    assert installer.normalize_model_name(name) == normalized


def test_missing_models_ignore_present_ones_including_implicit_latest():
    missing = installer.missing_models(
        required=["gemma4:12b-it-qat", "embed", "absent"],
        available=["gemma4:12b-it-qat", "embed:latest"],
    )

    assert missing == ["absent"]


# Ollama models


def summary_notes(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("  - ")]


def test_present_ollama_models_need_no_manual_note(tmp_path):
    ollama = FakeOllama(["gemma4:12b-it-qat", SEMANTIC_MODEL])

    exit_code, lines = run_install(make_installer(tmp_path, ollama=ollama))

    assert exit_code == 0
    assert ollama.requested_endpoints == [ENDPOINT]
    assert "[skipped] Check Ollama models (already present)" in lines
    assert not any("ollama pull" in line for line in lines)


def test_each_missing_ollama_model_becomes_a_manual_pull_note(tmp_path):
    commands = FakeCommands()

    exit_code, lines = run_install(
        make_installer(tmp_path, commands=commands, ollama=FakeOllama([]))
    )

    assert exit_code == 0
    assert "[skipped] Check Ollama models (manual step needed, see summary)" in lines
    pull_notes = [line for line in summary_notes(lines) if "ollama pull" in line]
    assert len(pull_notes) == 2
    assert f"ollama pull {BACKEND_MODEL}" in pull_notes[0]
    assert f"ollama pull {SEMANTIC_MODEL}" in pull_notes[1]
    assert not any("pull" in args for args in commands.commands)
    assert lines[-1] == "Start Jarvis with Jarvis.cmd"


def test_unreachable_ollama_is_one_manual_note_listing_every_required_model(
    tmp_path,
):
    ollama = FakeOllama([], reachable=False)

    exit_code, lines = run_install(make_installer(tmp_path, ollama=ollama))

    assert exit_code == 0
    assert ollama.requested_endpoints == [ENDPOINT]
    assert "[skipped] Check Ollama models (manual step needed, see summary)" in lines
    notes = summary_notes(lines)
    assert len(notes) == 1
    assert "not running" in notes[0]
    assert ENDPOINT in notes[0]
    output = "\n".join(lines)
    assert f"ollama pull {BACKEND_MODEL}" in output
    assert f"ollama pull {SEMANTIC_MODEL}" in output
    assert not any(line.startswith("[failed]") for line in lines)


def test_installer_takes_no_arguments():
    installer.parse_args([])

    with pytest.raises(SystemExit):
        installer.parse_args(["--ollama-exe", r"C:\o.exe"])


# Silero


def test_cached_silero_route_is_skipped(tmp_path):
    commands = FakeCommands()
    settings = settings_with(tts_languages={"ru": SileroTtsSettings(model="v3_1_ru")})

    exit_code, lines = run_install(
        make_installer(
            tmp_path,
            settings=settings,
            commands=commands,
            cached_silero_models={"v3_1_ru"},
        )
    )

    assert exit_code == 0
    assert not any("setup_tts_model.py" in args for args in commands.commands)
    assert "[skipped] Cache Silero TTS models (already present)" in lines


def test_uncached_silero_route_runs_setup_script_with_its_language_and_model(tmp_path):
    commands = FakeCommands()
    settings = settings_with(
        tts_languages={
            "ru": SileroTtsSettings(model="v3_1_ru", language="ru"),
            "en": SileroTtsSettings(model="v3_en", language="en"),
        }
    )

    exit_code, _lines = run_install(
        make_installer(
            tmp_path,
            settings=settings,
            commands=commands,
            cached_silero_models={"v3_1_ru"},
        )
    )

    assert exit_code == 0
    setup_calls = [args for args in commands.commands if "setup_tts_model.py" in args]
    assert setup_calls == [
        [PYTHON, "setup_tts_model.py", "--language", "en", "--model", "v3_en"]
    ]


def test_failed_silero_setup_reports_the_setup_command_as_retry(tmp_path):
    commands = FakeCommands(failing_prefixes=((PYTHON, "setup_tts_model.py"),))

    exit_code, lines = run_install(make_installer(tmp_path, commands=commands))

    assert exit_code == 1
    failure_index = next(
        i for i, line in enumerate(lines) if line.startswith("[failed]")
    )
    assert lines[failure_index].startswith("[failed] Cache Silero TTS models")
    assert (
        "setup_tts_model.py --language ru --model v3_1_ru" in lines[failure_index + 1]
    )


# Piper


def test_missing_piper_model_becomes_a_manual_note_not_a_failure(tmp_path):
    settings = settings_with(
        tts_languages={
            "ru": SileroTtsSettings(),
            "en": PiperTtsSettings(model="models/en.onnx"),
        }
    )

    exit_code, lines = run_install(
        make_installer(tmp_path, settings=settings, cached_silero_models={"v3_1_ru"})
    )

    assert exit_code == 0
    notes = [line for line in lines if "en.onnx" in line]
    assert len(notes) == 1
    assert "[tts.languages.en]" in notes[0]
    assert lines[-1] == "Start Jarvis with Jarvis.cmd"


def test_present_piper_model_needs_no_manual_note(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "en.onnx").write_bytes(b"")
    settings = settings_with(
        tts_languages={
            "ru": SileroTtsSettings(),
            "en": PiperTtsSettings(model="models/en.onnx"),
        }
    )

    exit_code, lines = run_install(
        make_installer(tmp_path, settings=settings, cached_silero_models={"v3_1_ru"})
    )

    assert exit_code == 0
    assert not any("en.onnx" in line for line in lines)
    assert "[skipped] Check Piper TTS models (already present)" in lines
