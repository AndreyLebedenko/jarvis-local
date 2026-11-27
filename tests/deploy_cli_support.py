"""Helpers that run the real deploy scripts against a fake source home."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

CLI_REPOSITORY_FILES = (
    "deploy.cmd",
    "tools/install/deploy.ps1",
    "tools/deployment.py",
    "tools/deployment_brand.py",
    "tools/deployment_brand_check.py",
    "tools/deployment_plan.py",
    "tools/deployment_rebrand.py",
    "tools/deployment_shortcut.py",
    "tools/deployment_snapshot.py",
    "tools/deployment_toml.py",
    "tools/build_launcher_icon.ps1",
    "tools/generate_brand_icons.ps1",
    "src/jarvis/__init__.py",
    "src/jarvis/core/__init__.py",
    "src/jarvis/core/brand.py",
    "src/jarvis/core/brand_icon.py",
    "src/jarvis/core/brand_render.py",
    "src/jarvis/core/config.py",
    "src/jarvis/core/single_instance.py",
    "src/jarvis/launcher/__init__.py",
    "src/jarvis/launcher/identity.py",
)
FAKE_BOOTSTRAP = """param([switch]$Yes)
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
"""


def build_cli_home(home: Path) -> None:
    """A fake source home holding the real deploy scripts and tool modules."""
    repository = Path(__file__).resolve().parents[1]
    for name in CLI_REPOSITORY_FILES:
        destination = home / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repository / name, destination)
    mutex_module = home / "src/jarvis/core/single_instance.py"
    mutex_module.write_text(
        mutex_module.read_text(encoding="utf-8").replace(
            "Jarvis.SingleInstance", f"Jarvis.DeployCliTest.{uuid4().hex}"
        ),
        encoding="utf-8",
    )
    (home / "tools/install/bootstrap.ps1").write_text(FAKE_BOOTSTRAP, encoding="utf-8")


def run_deploy_cmd(
    home: Path, tmp_path: Path, *arguments: str, source_venv_ready: bool = True
) -> subprocess.CompletedProcess[str]:
    stale_module = tmp_path / "stale-env" / "jarvis" / "__init__.py"
    stale_module.parent.mkdir(parents=True, exist_ok=True)
    stale_module.write_text(
        'raise RuntimeError("imported stale Jarvis")\n', encoding="utf-8"
    )
    return subprocess.run(
        [str(home / "deploy.cmd"), *arguments],
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
