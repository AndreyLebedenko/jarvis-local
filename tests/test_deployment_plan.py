from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.deployment_plan import (
    APPLICATION_FILES,
    PACKAGE_DIR,
    PACKAGE_FILE_TYPES,
    DeploymentMode,
    DeploymentPlanError,
    plan_deployment,
)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    for name in (*APPLICATION_FILES, Path("src/jarvis/__init__.py")):
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return home


def link_directory(link: Path, target: Path) -> None:
    if os.name == "nt":
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


def test_deployment_inventory_supports_every_file_in_the_repository_package() -> None:
    package = Path(__file__).resolve().parents[1] / PACKAGE_DIR
    unsupported = sorted(
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if "__pycache__" not in path.relative_to(package).parts
        and path.is_file()
        and path.suffix not in PACKAGE_FILE_TYPES
    )

    assert not unsupported, f"Deployment would omit package files: {unsupported}"


def test_clean_plan_includes_app_files_without_reading_user_settings(
    home: Path, tmp_path: Path
) -> None:
    for name in (
        "src/jarvis/__pycache__/app.pyc",
        "src/jarvis/launcher/assets/jarvis.ico",
        "src/jarvis/ui/status_console_ui/index.html",
        ".git/HEAD",
        ".venv/Scripts/python.exe",
        "journal/session/events.jsonl",
        "memory/memory.md",
    ):
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (home / "config.toml").write_text("[broken", encoding="utf-8")
    target = tmp_path / "clean"

    plan = plan_deployment(home, target, DeploymentMode.CLEAN)

    assert plan.source == home
    assert plan.target == target
    assert plan.mode is DeploymentMode.CLEAN
    assert plan.snapshot is None
    assert set(plan.application_files) == {
        *APPLICATION_FILES,
        Path("src/jarvis/__init__.py"),
        Path("src/jarvis/launcher/assets/jarvis.ico"),
        Path("src/jarvis/ui/status_console_ui/index.html"),
    }
    assert not target.exists()


def test_copy_plan_uses_effective_roots_and_follows_junctions(
    home: Path, tmp_path: Path
) -> None:
    external_journal = tmp_path / "external-journal"
    external_journal.mkdir()
    (external_journal / "events.jsonl").touch()
    link_directory(home / "journal-link", external_journal)
    memory = tmp_path / "external-memory"
    memory.mkdir()
    (home / "config.toml").write_text(
        f'[journal]\nroot = "journal-link"\n[memory]\nroot = {json.dumps(str(memory))}',
        encoding="utf-8",
    )
    (home / "config.ui.toml").write_text(
        '[memory]\nroot = "memory-override"\n', encoding="utf-8"
    )
    target = tmp_path / "copy"

    plan = plan_deployment(home, target, DeploymentMode.COPY)

    assert plan.snapshot is not None
    assert plan.snapshot.config_files == (Path("config.toml"), Path("config.ui.toml"))
    assert plan.snapshot.journal == external_journal
    assert plan.snapshot.memory == home / "memory-override"
    assert (external_journal / "events.jsonl").is_file()
    assert not target.exists()


def test_copy_plan_accepts_default_roots_without_local_config(
    home: Path, tmp_path: Path
) -> None:
    plan = plan_deployment(home, tmp_path / "copy", DeploymentMode.COPY)

    assert plan.snapshot is not None
    assert plan.snapshot.config_files == ()
    assert plan.snapshot.journal == home / "journal"
    assert plan.snapshot.memory == home / "memory"


def test_copy_plan_reports_invalid_config(home: Path, tmp_path: Path) -> None:
    (home / "config.toml").write_text("[broken", encoding="utf-8")

    with pytest.raises(DeploymentPlanError, match=r"source settings.*config\.toml"):
        plan_deployment(home, tmp_path / "copy", DeploymentMode.COPY)


def test_copy_plan_rejects_active_mcp_provider_but_honors_ui_disable(
    home: Path, tmp_path: Path
) -> None:
    (home / "config.toml").write_text(
        '[mcp]\nenabled = true\n[mcp.servers.database]\ncommand = "provider.exe"\n',
        encoding="utf-8",
    )
    target = tmp_path / "copy"

    with pytest.raises(DeploymentPlanError, match=r"\[mcp.servers.database\]"):
        plan_deployment(home, target, DeploymentMode.COPY)

    (home / "config.ui.toml").write_text("[mcp]\nenabled = false\n", encoding="utf-8")
    assert plan_deployment(home, target, DeploymentMode.COPY).snapshot is not None

    (home / "config.ui.toml").write_text(
        '[mcp.servers.database]\ncommand = "provider.exe"\nenabled = false\n',
        encoding="utf-8",
    )
    assert plan_deployment(home, target, DeploymentMode.COPY).snapshot is not None


@pytest.mark.parametrize("relative", [".", "new/home", "existing", "existing.txt"])
def test_clean_plan_rejects_existing_or_overlapping_destination(
    home: Path, tmp_path: Path, relative: str
) -> None:
    (tmp_path / "existing").mkdir()
    (tmp_path / "existing.txt").touch()
    target = home / relative if relative in {".", "new/home"} else tmp_path / relative

    with pytest.raises(DeploymentPlanError, match="Destination"):
        plan_deployment(home, target, DeploymentMode.CLEAN)


def test_destination_junction_cannot_hide_overlap_with_source(
    home: Path, tmp_path: Path
) -> None:
    alias = tmp_path / "alias"
    link_directory(alias, home)

    with pytest.raises(DeploymentPlanError, match="overlaps the source"):
        plan_deployment(home, alias / "new", DeploymentMode.CLEAN)


def test_destination_parent_must_be_a_directory(home: Path, tmp_path: Path) -> None:
    parent = tmp_path / "file"
    parent.touch()

    with pytest.raises(DeploymentPlanError, match="Destination parent is a file"):
        plan_deployment(home, parent / "new", DeploymentMode.CLEAN)


@pytest.mark.skipif(os.name != "nt", reason="Windows path syntax")
def test_copy_plan_rejects_a_drive_relative_root(home: Path, tmp_path: Path) -> None:
    (home / "config.toml").write_text(
        '[journal]\nroot = "C:session-data"', encoding="utf-8"
    )

    with pytest.raises(DeploymentPlanError, match=r"\[journal\]\.root.*ambiguous"):
        plan_deployment(home, tmp_path / "copy", DeploymentMode.COPY)


@pytest.mark.parametrize(
    ("config", "key"),
    [
        ('[journal]\nroot = "."', "journal"),
        ('[memory]\nroot = "journal/memory"', "memory"),
        ('[logging]\ndirectory = "journal/logs"', "logging"),
        ('[mcp_mode]\ntoken_file = "memory/token"', "mcp_mode"),
    ],
)
def test_copy_plan_rejects_overlapping_snapshot_paths(
    home: Path, tmp_path: Path, config: str, key: str
) -> None:
    (home / "config.toml").write_text(config, encoding="utf-8")

    with pytest.raises(DeploymentPlanError, match=rf"\[{key}\]\."):
        plan_deployment(home, tmp_path / "copy", DeploymentMode.COPY)


def test_copy_destination_cannot_overlap_an_external_snapshot_root(
    home: Path, tmp_path: Path
) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    (home / "config.toml").write_text(
        f"[journal]\nroot = {json.dumps(str(storage))}", encoding="utf-8"
    )

    with pytest.raises(DeploymentPlanError, match=r"Destination.*\[journal\]\.root"):
        plan_deployment(home, storage / "copy", DeploymentMode.COPY)


def test_copy_destination_cannot_overlap_external_logs(
    home: Path, tmp_path: Path
) -> None:
    logs = tmp_path / "logs"
    (home / "config.toml").write_text(
        f"[logging]\ndirectory = {json.dumps(str(logs))}", encoding="utf-8"
    )

    with pytest.raises(
        DeploymentPlanError, match=r"Destination.*\[logging\]\.directory"
    ):
        plan_deployment(home, logs, DeploymentMode.COPY)


def test_copy_plan_rejects_a_snapshot_root_that_is_a_file(
    home: Path, tmp_path: Path
) -> None:
    (home / "journal").touch()

    with pytest.raises(
        DeploymentPlanError, match=r"\[journal\]\.root.*not a directory"
    ):
        plan_deployment(home, tmp_path / "copy", DeploymentMode.COPY)


def test_plan_reports_missing_application_file(home: Path, tmp_path: Path) -> None:
    (home / "install.cmd").unlink()

    with pytest.raises(DeploymentPlanError, match=r"install\.cmd"):
        plan_deployment(home, tmp_path / "clean", DeploymentMode.CLEAN)


def test_plan_rejects_linked_application_directory(home: Path, tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    (external / "app.py").touch()
    link_directory(home / "src" / "jarvis" / "external", external)

    with pytest.raises(DeploymentPlanError, match="Application path is linked"):
        plan_deployment(home, tmp_path / "clean", DeploymentMode.CLEAN)


def test_plan_reports_package_file_access_error(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unreadable = home / PACKAGE_DIR / "app.py"
    unreadable.touch()
    original_lstat = Path.lstat

    def lstat(path: Path) -> os.stat_result:
        if path == unreadable:
            raise PermissionError("access denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", lstat)

    with pytest.raises(
        DeploymentPlanError, match=r"Cannot inspect application file.*app\.py"
    ):
        plan_deployment(home, tmp_path / "clean", DeploymentMode.CLEAN)
