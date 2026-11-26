from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from deploy_cli_support import build_cli_home, run_deploy_cmd

from tools import deployment
from tools.deployment_plan import APPLICATION_FILES, PACKAGE_DIR


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "source"
    for name in (*APPLICATION_FILES, PACKAGE_DIR / "__init__.py"):
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Example\n" if name == Path("config.example.toml") else str(name),
            encoding="utf-8",
        )
    return home


@pytest.mark.parametrize("is_checkout", [True, False])
def test_clean_deploy_installs_at_final_location_without_source_state(
    home: Path, tmp_path: Path, is_checkout: bool
) -> None:
    if is_checkout:
        (home / ".git").mkdir()
    (home / "config.toml").touch()
    (home / "journal").mkdir()
    (home / ".venv").mkdir()
    target = tmp_path / "new home"

    def install(app_home: Path, assume_yes: bool) -> int:
        assert app_home == target
        assert assume_yes
        assert (target / "install.cmd").read_text(encoding="utf-8") == "install.cmd"
        assert not (target / "config.toml").exists()
        assert not (target / "journal").exists()
        assert not (target / ".git").exists()
        assert not (target / ".venv").exists()
        return 0

    assert deployment.deploy(home, target, assume_yes=True, installer=install) == 0
    assert manifest_phase(target) == "complete"


def test_failed_install_can_resume_without_recopying(
    home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "destination"
    assert deployment.deploy(home, target, installer=lambda *_: 7) == 7
    assert manifest_phase(target) == "ready"
    (home / "install.cmd").write_text("different source", encoding="utf-8")

    def install(app_home: Path, assume_yes: bool) -> int:
        assert app_home == target
        assert not assume_yes
        assert (target / "install.cmd").read_text(encoding="utf-8") == "install.cmd"
        return 0

    assert (
        deployment.deploy(tmp_path / "absent", target, resume=True, installer=install)
        == 0
    )
    assert manifest_phase(target) == "complete"
    with pytest.raises(deployment.DeploymentError, match="already complete"):
        deployment.deploy(home, target, resume=True, installer=install)


def test_partial_application_preparation_is_not_resumable(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "destination"

    def interrupted(source: Path, target: Path) -> None:
        raise OSError("interrupted copy")

    monkeypatch.setattr(deployment.shutil, "copy2", interrupted)
    with pytest.raises(deployment.DeploymentError, match="interrupted copy"):
        deployment.deploy(home, target)
    assert manifest_phase(target) == "preparing"
    with pytest.raises(
        deployment.DeploymentError,
        match=r"file preparation is incomplete.*Remove the incomplete directory",
    ):
        deployment.deploy(home, target, resume=True)


def test_resume_rejects_unrecognized_moved_and_corrupt_manifest(
    home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "unrelated"
    target.mkdir()
    with pytest.raises(
        deployment.DeploymentError, match="Cannot read deployment manifest"
    ):
        deployment.deploy(home, target, resume=True)

    original = tmp_path / "destination"
    assert deployment.deploy(home, original, installer=lambda *_: 7) == 7
    marker = target / deployment.MANIFEST
    marker.write_bytes((original / deployment.MANIFEST).read_bytes())
    with pytest.raises(deployment.DeploymentError, match="does not match the target"):
        deployment.deploy(home, target, resume=True)

    marker.write_text("{broken", encoding="utf-8")
    with pytest.raises(deployment.DeploymentError, match="deployment manifest"):
        deployment.deploy(home, target, resume=True)


def test_destination_is_reserved_for_only_one_deployment(
    home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "destination"

    def install(app_home: Path, assume_yes: bool) -> int:
        with pytest.raises(deployment.DeploymentError, match="already running for"):
            deployment.deploy(home, target, resume=True)
        return 0

    assert deployment.deploy(home, target, installer=install) == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction")
def test_resume_rejects_a_venv_linked_to_the_source(home: Path, tmp_path: Path) -> None:
    target = tmp_path / "destination"
    assert deployment.deploy(home, target, installer=lambda *_: 7) == 7
    source_venv = home / ".venv"
    source_venv.mkdir()
    subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/c",
            "mklink",
            "/J",
            str(target / ".venv"),
            str(source_venv),
        ],
        check=True,
        capture_output=True,
    )

    with pytest.raises(
        deployment.DeploymentError, match=r"linked installer path.*\.venv"
    ):
        deployment.deploy(
            home, target, resume=True, installer=lambda *_: pytest.fail("installer ran")
        )

    assert manifest_phase(target) == "ready"


@pytest.mark.skipif(os.name != "nt", reason="Windows deployment command")
@pytest.mark.parametrize("source_venv_ready", [True, False])
@pytest.mark.parametrize("mode", ["clean", "copy"])
def test_cli_loads_source_code_and_reaches_installer_in_final_directory(
    home: Path, tmp_path: Path, source_venv_ready: bool, mode: str
) -> None:
    build_cli_home(home)
    target = tmp_path / "new home"
    (home / "journal").mkdir()
    (home / "journal" / "events.jsonl").write_bytes(b"history")

    result = run_deploy_cmd(
        home,
        tmp_path,
        "-Target",
        target.name,
        "-Mode",
        mode,
        "-Yes",
        source_venv_ready=source_venv_ready,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "installer-cwd.txt").read_text(
        encoding="utf-8-sig"
    ).strip() == str(target)
    assert manifest_phase(target) == "complete"
    history = target / "journal" / "events.jsonl"
    if mode == "copy":
        assert history.read_bytes() == b"history"
    else:
        assert not history.exists()


def manifest_phase(target: Path) -> str:
    return json.loads((target / deployment.MANIFEST).read_text(encoding="utf-8"))[
        "phase"
    ]
