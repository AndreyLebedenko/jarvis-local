from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import deployment
from tools.deployment_plan import APPLICATION_FILES, PACKAGE_DIR, DeploymentMode


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "source"
    for name in (*APPLICATION_FILES, PACKAGE_DIR / "__init__.py"):
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(name), encoding="utf-8")
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


def test_copy_mode_waits_for_snapshot_implementation(
    home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "destination"
    with pytest.raises(deployment.DeploymentError, match="Copy mode"):
        deployment.deploy(home, target, mode=DeploymentMode.COPY)
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows deployment command")
@pytest.mark.parametrize("source_venv_ready", [True, False])
def test_cli_loads_source_code_and_reaches_installer_in_final_directory(
    home: Path, tmp_path: Path, source_venv_ready: bool
) -> None:
    repository = Path(__file__).resolve().parents[1]
    for name in (
        "deploy.cmd",
        "tools/install/deploy.ps1",
        "tools/deployment.py",
        "tools/deployment_plan.py",
        "src/jarvis/__init__.py",
        "src/jarvis/core/__init__.py",
        "src/jarvis/core/config.py",
        "src/jarvis/core/single_instance.py",
    ):
        destination = home / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repository / name, destination)
    (home / "tools/install/bootstrap.ps1").write_text(
        """param([switch]$Yes)
function Get-VenvPython($AppHome) { return $env:TEST_DEPLOY_PYTHON }
function Test-IsPython311($Exe) { return $env:TEST_DEPLOY_VENV_READY -eq '1' }
function Get-OrInstallPython311([bool]$AssumeYes) {
    if ($env:TEST_DEPLOY_VENV_READY -eq '1' -or -not $AssumeYes) { exit 8 }
    return $env:TEST_DEPLOY_PYTHON
}
if ($MyInvocation.InvocationName -ne '.') {
    if (-not $Yes -or $env:PYTHONPATH) { exit 9 }
    $location = (Get-Location).Path
    Set-Content -LiteralPath 'installer-cwd.txt' -Value $location -Encoding UTF8
    exit 0
}
""",
        encoding="utf-8",
    )
    target = tmp_path / "new home"
    stale_module = tmp_path / "stale-env" / "jarvis" / "__init__.py"
    stale_module.parent.mkdir(parents=True)
    stale_module.write_text(
        'raise RuntimeError("imported stale Jarvis")\n', encoding="utf-8"
    )

    result = subprocess.run(
        [str(home / "deploy.cmd"), "-Target", target.name, "-Mode", "clean", "-Yes"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(stale_module.parents[1]),
            "TEST_DEPLOY_PYTHON": sys.executable,
            "TEST_DEPLOY_VENV_READY": str(int(source_venv_ready)),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "installer-cwd.txt").read_text(
        encoding="utf-8-sig"
    ).strip() == str(target)
    assert manifest_phase(target) == "complete"


def manifest_phase(target: Path) -> str:
    return json.loads((target / deployment.MANIFEST).read_text(encoding="utf-8"))[
        "phase"
    ]
