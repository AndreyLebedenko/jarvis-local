"""Stage 2 of install.cmd: dependencies, package, config, TTS models.

Run by tools/install/bootstrap.ps1 with the app home's venv interpreter.
Every step is idempotent, so re-running install.cmd resumes after a failure.
Ollama models are never downloaded here: missing ones, and a stopped Ollama,
become manual notes in the final summary.
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import site
import subprocess
import sys
import sysconfig
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.core.config import Settings, SileroTtsSettings

CONFIG_NAME = "config.toml"
EXAMPLE_CONFIG_NAME = "config.example.toml"
SILERO_SETUP_SCRIPT = "setup_tts_model.py"
RESUME_HINT = "Fix the problem above, then re-run install.cmd to resume."
LAUNCH_HINT = "Start Jarvis with Jarvis.cmd"
MANUAL_STEP_DETAIL = "manual step needed, see summary"
TAGS_TIMEOUT_SECONDS = 5.0

CommandRunner = Callable[[Sequence[str]], int]


class StepFailed(Exception):
    def __init__(self, message: str, retry_command: str | None = None):
        super().__init__(message)
        self.retry_command = retry_command


class OllamaUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class StepOutcome:
    status: str
    detail: str = ""


def done(detail: str = "") -> StepOutcome:
    return StepOutcome("done", detail)


def skipped(detail: str) -> StepOutcome:
    return StepOutcome("skipped", detail)


@dataclass(frozen=True)
class Step:
    name: str
    action: Callable[[], StepOutcome]


def run_steps(steps: Iterable[Step], output: Callable[[str], None]) -> int:
    for step in steps:
        try:
            outcome = step.action()
        except StepFailed as failure:
            output(f"[failed] {step.name}: {failure}")
            if failure.retry_command:
                output(f"Retry: {failure.retry_command}")
            output(RESUME_HINT)
            return 1
        detail = f" ({outcome.detail})" if outcome.detail else ""
        output(f"[{outcome.status}] {step.name}{detail}")
    return 0


def required_ollama_models(settings: Settings) -> list[str]:
    models = [settings.backend.model]
    semantic = settings.history.semantic
    if semantic.enabled:
        models.append(semantic.model)
    return list(dict.fromkeys(models))


def normalize_model_name(name: str) -> str:
    last_segment = name.rsplit("/", 1)[-1]
    return name if ":" in last_segment else f"{name}:latest"


def missing_models(required: Iterable[str], available: Iterable[str]) -> list[str]:
    present = {normalize_model_name(name) for name in available}
    return [name for name in required if normalize_model_name(name) not in present]


def command_line(args: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(args))


@dataclass
class Installer:
    app_home: Path
    python_executable: str
    run_command: CommandRunner
    load_settings: Callable[[Path], Settings]
    fetch_model_names: Callable[[str], list[str]]
    is_silero_model_cached: Callable[[SileroTtsSettings], bool]
    refresh_import_paths: Callable[[], None]
    manual_notes: list[str] = field(default_factory=list, init=False)
    _settings: Settings = field(init=False)

    def steps(self) -> list[Step]:
        return [
            Step("Install Python dependencies", self.install_dependencies),
            Step("Install the Jarvis package", self.install_package),
            Step("Create config.toml", self.create_config),
            Step("Load settings", self.load_config),
            Step("Check Ollama models", self.check_ollama_models),
            Step("Cache Silero TTS models", self.cache_silero_models),
            Step("Check Piper TTS models", self.check_piper_models),
        ]

    def install_dependencies(self) -> StepOutcome:
        self._run_in_app_home(
            [self.python_executable, "-m", "pip", "install", "-r", "requirements.txt"]
        )
        return done()

    def install_package(self) -> StepOutcome:
        self._run_in_app_home(
            [self.python_executable, "-m", "pip", "install", "-e", "."]
        )
        self.refresh_import_paths()
        return done()

    def create_config(self) -> StepOutcome:
        config = self.app_home / CONFIG_NAME
        if config.exists():
            return skipped("already present")
        try:
            shutil.copyfile(self.app_home / EXAMPLE_CONFIG_NAME, config)
        except OSError as error:
            raise StepFailed(
                f"cannot copy {EXAMPLE_CONFIG_NAME} to {CONFIG_NAME}: {error}"
            ) from error
        return done()

    def load_config(self) -> StepOutcome:
        from jarvis.core.config import ConfigError

        try:
            self._settings = self.load_settings(self.app_home / CONFIG_NAME)
        except ConfigError as error:
            raise StepFailed(f"{CONFIG_NAME} is invalid: {error}") from error
        return done()

    def check_ollama_models(self) -> StepOutcome:
        endpoint = self._settings.backend.endpoint
        required = required_ollama_models(self._settings)
        try:
            available = self.fetch_model_names(endpoint)
        except OllamaUnavailableError as error:
            pull_commands = "\n".join(f"ollama pull {model}" for model in required)
            self.manual_notes.append(
                f"Ollama is not running at {endpoint} ({error}), so its models "
                f"could not be checked. Start Ollama, then run:\n{pull_commands}"
            )
            return skipped(MANUAL_STEP_DETAIL)
        absent = missing_models(required, available)
        for model in absent:
            self.manual_notes.append(
                f"Ollama model {model} is not on {endpoint}. Run: ollama pull {model}"
            )
        return skipped(MANUAL_STEP_DETAIL if absent else "already present")

    def cache_silero_models(self) -> StepOutcome:
        uncached = [
            route
            for route in self._silero_routes()
            if not self.is_silero_model_cached(route)
        ]
        if not uncached:
            return skipped("already present")
        for route in uncached:
            self._run_in_app_home(
                [
                    self.python_executable,
                    SILERO_SETUP_SCRIPT,
                    "--language",
                    route.language,
                    "--model",
                    route.model,
                ]
            )
        return done(f"cached {', '.join(route.model for route in uncached)}")

    def check_piper_models(self) -> StepOutcome:
        piper_routes = {
            language: route
            for language, route in self._settings.tts.languages.items()
            if route.engine == "piper"
        }
        if not piper_routes:
            return skipped("no Piper routes configured")
        notes_before = len(self.manual_notes)
        for language, route in piper_routes.items():
            model_path = self.app_home / route.model
            if not model_path.is_file():
                self.manual_notes.append(
                    f"Piper model for [tts.languages.{language}] is missing: "
                    f"{model_path}. Place the .onnx model there yourself; "
                    "the installer does not download Piper models."
                )
        if len(self.manual_notes) > notes_before:
            return skipped(MANUAL_STEP_DETAIL)
        return skipped("already present")

    def _silero_routes(self) -> list[SileroTtsSettings]:
        unique = {
            (route.language, route.model): route
            for route in self._settings.tts.languages.values()
            if route.engine == "silero"
        }
        return list(unique.values())

    def _run_in_app_home(self, args: list[str]) -> None:
        return_code = self.run_command(args)
        if return_code != 0:
            raise StepFailed(
                f"command exited with code {return_code}",
                retry_command=f'cd /d "{self.app_home}" && {command_line(args)}',
            )


def summary_lines(manual_notes: Sequence[str]) -> list[str]:
    lines = ["", "Installation complete."]
    if manual_notes:
        lines.append("Manual steps still needed:")
        for note in manual_notes:
            first_line, *continuation = note.splitlines()
            lines.append(f"  - {first_line}")
            lines.extend(f"    {line}" for line in continuation)
    lines.append(LAUNCH_HINT)
    return lines


def install(installer: Installer, output: Callable[[str], None]) -> int:
    exit_code = run_steps(installer.steps(), output)
    if exit_code == 0:
        for line in summary_lines(installer.manual_notes):
            output(line)
    return exit_code


def run_subprocess(args: Sequence[str]) -> int:
    try:
        return subprocess.run(list(args), check=False).returncode
    except OSError as error:
        print(f"Cannot run {args[0]}: {error}", file=sys.stderr)
        return 1


def refresh_site_packages() -> None:
    importlib.invalidate_caches()
    # .pth files (how `pip install -e .` exposes jarvis) are read only at start-up.
    for site_dir in dict.fromkeys(
        [sysconfig.get_path("purelib"), sysconfig.get_path("platlib")]
    ):
        site.addsitedir(site_dir)


def load_jarvis_settings(path: Path) -> Settings:
    from jarvis.core.config import load_settings

    return load_settings(path)


def fetch_ollama_model_names(endpoint: str) -> list[str]:
    import httpx

    try:
        response = httpx.get(
            f"{endpoint.rstrip('/')}/api/tags", timeout=TAGS_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return [model["name"] for model in response.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise OllamaUnavailableError(str(error) or type(error).__name__) from error


def silero_model_cache_checker(
    app_home: Path,
) -> Callable[[SileroTtsSettings], bool]:
    def is_cached(route: SileroTtsSettings) -> bool:
        import silero

        from jarvis.audio.tts_silero import TtsModelNotCachedError, ensure_model_cached

        try:
            ensure_model_cached(silero, route, repo_root=app_home)
        except TtsModelNotCachedError:
            return False
        return True

    return is_cached


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install Jarvis into its app home.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    app_home = Path(__file__).resolve().parents[1]
    # Silero looks for its manifest in the process cwd, not next to the code.
    os.chdir(app_home)
    installer = Installer(
        app_home=app_home,
        python_executable=sys.executable,
        run_command=run_subprocess,
        load_settings=load_jarvis_settings,
        fetch_model_names=fetch_ollama_model_names,
        is_silero_model_cached=silero_model_cache_checker(app_home),
        refresh_import_paths=refresh_site_packages,
    )
    return install(installer, print)


if __name__ == "__main__":
    raise SystemExit(main())
