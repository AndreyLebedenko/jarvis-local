"""Read-only planning for a separate Jarvis application home."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NoReturn

from jarvis.core.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_UI_CONFIG_PATH,
    ConfigError,
    Settings,
    load_settings,
)

APPLICATION_FILES = tuple(
    Path(name)
    for name in (
        "LICENSE",
        "README.md",
        "README.ru.md",
        "Jarvis.cmd",
        "JarvisLauncher.cmd",
        "DeploymentWizard.cmd",
        "deploy.cmd",
        "install.cmd",
        "config.example.toml",
        "latest_silero_models.yml",
        "pyproject.toml",
        "requirements.txt",
        "requirements-stt.txt",
        "setup_stt_model.py",
        "setup_tts_model.py",
        "tools/build_launcher_icon.ps1",
        "tools/create_launcher_shortcut.ps1",
        "tools/deployment.py",
        "tools/deployment_brand.py",
        "tools/deployment_brand_check.py",
        "tools/deployment_plan.py",
        "tools/deployment_shortcut.py",
        "tools/deployment_snapshot.py",
        "tools/deployment_toml.py",
        "tools/generate_brand_icons.ps1",
        "tools/install/bootstrap.ps1",
        "tools/install/deploy.ps1",
        "tools/install/wizard.ps1",
        "tools/install/wizard.xaml",
        "tools/install/wizard_identity.ps1",
        "tools/install/wizard_job.ps1",
        "tools/install/wizard_pages.ps1",
        "tools/install/wizard_preview.ps1",
        "tools/install/wizard_start.ps1",
        "tools/install/wizard_worker.ps1",
        "tools/installer.py",
    )
)
PACKAGE_DIR = Path("src/jarvis")
PACKAGE_FILE_TYPES = frozenset({".css", ".html", ".ico", ".js", ".md", ".png", ".py"})


class DeploymentMode(StrEnum):
    CLEAN = "clean"
    COPY = "copy"


class DeploymentPlanError(ValueError):
    """A deployment request cannot be planned safely."""


@dataclass(frozen=True)
class SnapshotPlan:
    config_files: tuple[Path, ...]
    journal: Path
    memory: Path


@dataclass(frozen=True)
class DeploymentPlan:
    source: Path
    target: Path
    mode: DeploymentMode
    application_files: tuple[Path, ...]
    snapshot: SnapshotPlan | None


def plan_deployment(source: Path, target: Path, mode: DeploymentMode) -> DeploymentPlan:
    source = _resolve(source, "Source")
    target = _new_destination(source, target)
    application_files = application_inventory(source)
    snapshot = _snapshot_plan(source, target) if mode is DeploymentMode.COPY else None
    return DeploymentPlan(source, target, mode, application_files, snapshot)


def _resolve(path: Path, label: str) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError) as error:
        raise DeploymentPlanError(f"{label} path cannot be resolved: {path}") from error


def _overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)


def _new_destination(source: Path, requested: Path) -> Path:
    if requested.anchor and not requested.is_absolute():
        raise DeploymentPlanError(f"Destination path is ambiguous: {requested}")
    target = _resolve(requested, "Destination")
    if _overlap(source, target) or Path(os.path.abspath(requested)).is_relative_to(
        source
    ):
        raise DeploymentPlanError(f"Destination overlaps the source: {requested}")
    if os.path.lexists(requested) or os.path.lexists(target):
        raise DeploymentPlanError(f"Destination already exists: {requested}")
    for parent in target.parents:
        if os.path.lexists(parent):
            if not parent.is_dir():
                raise DeploymentPlanError(f"Destination parent is a file: {parent}")
            break
    return target


def _plain_app_path(source: Path, relative: Path) -> Path:
    path = source / relative
    if _resolve(path, "Application") != path:
        raise DeploymentPlanError(f"Application path is linked: {relative}")
    return path


def _inventory_error(error: OSError) -> NoReturn:
    raise DeploymentPlanError(f"Cannot read application inventory: {error}") from error


def application_inventory(source: Path) -> tuple[Path, ...]:
    for relative in (*APPLICATION_FILES, PACKAGE_DIR / "__init__.py"):
        if not _plain_app_path(source, relative).is_file():
            raise DeploymentPlanError(f"Application file is missing: {relative}")
    package_files: list[Path] = []
    for directory, children, files in os.walk(
        source / PACKAGE_DIR, onerror=_inventory_error
    ):
        root = Path(directory)
        children[:] = [name for name in children if name != "__pycache__"]
        for name in children:
            _plain_app_path(source, (root / name).relative_to(source))
        for name in files:
            relative = (root / name).relative_to(source)
            if relative.suffix in PACKAGE_FILE_TYPES:
                path = _plain_app_path(source, relative)
                try:
                    file_mode = path.lstat().st_mode
                except OSError as error:
                    raise DeploymentPlanError(
                        f"Cannot inspect application file {relative}: {error}"
                    ) from error
                if stat.S_ISREG(file_mode):
                    package_files.append(relative)
    return (*APPLICATION_FILES, *sorted(package_files))


def _configured_path(source: Path, value: str, key: str) -> Path:
    location = Path(value)
    if location.anchor and not location.is_absolute():
        raise DeploymentPlanError(f"{key} uses an ambiguous Windows path: {value}")
    return _resolve(source / location, key)


def _snapshot_root(source: Path, target: Path, value: str, key: str) -> Path:
    root = _configured_path(source, value, key)
    if source.is_relative_to(root):
        raise DeploymentPlanError(f"{key} contains the source home: {root}")
    if _overlap(target, root):
        raise DeploymentPlanError(f"Destination overlaps {key}: {root}")
    if os.path.lexists(source / value) and not root.is_dir():
        raise DeploymentPlanError(f"{key} is not a directory: {root}")
    return root


def check_snapshot_providers(settings: Settings) -> None:
    if not settings.mcp.enabled:
        return
    for name, provider in settings.mcp.servers.items():
        if provider.enabled:
            raise DeploymentPlanError(
                f"[mcp.servers.{name}] is enabled. "
                "Copy cannot verify that the provider's data stores are isolated."
            )


def _snapshot_plan(source: Path, target: Path) -> SnapshotPlan:
    try:
        settings = load_settings(source / DEFAULT_CONFIG_PATH)
    except ConfigError as error:
        raise DeploymentPlanError(f"Cannot read source settings: {error}") from error
    check_snapshot_providers(settings)

    journal = _snapshot_root(source, target, settings.journal.root, "[journal].root")
    memory = _snapshot_root(source, target, settings.memory.root, "[memory].root")
    if _overlap(journal, memory):
        raise DeploymentPlanError("[memory].root overlaps [journal].root")

    excluded_paths = (
        ("[logging].directory", settings.logging.directory),
        ("[mcp_mode].token_file", settings.mcp_mode.token_file),
    )
    for key, value in excluded_paths:
        excluded = _configured_path(source, value, key)
        if _overlap(excluded, target):
            raise DeploymentPlanError(f"Destination overlaps {key}: {excluded}")
        if any(excluded.is_relative_to(root) for root in (journal, memory)):
            raise DeploymentPlanError(f"{key} is inside a snapshot root: {excluded}")

    config_files = tuple(
        path
        for path in (DEFAULT_CONFIG_PATH, DEFAULT_UI_CONFIG_PATH)
        if (source / path).is_file()
    )
    return SnapshotPlan(config_files, journal, memory)
