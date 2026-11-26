from __future__ import annotations

import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

import pytest

from tools import deployment
from tools.deployment_plan import (
    APPLICATION_FILES,
    PACKAGE_DIR,
    DeploymentMode,
    DeploymentPlanError,
)

WIZARD_DIR = Path(__file__).resolve().parents[1] / "tools/install"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "source"
    for path in (*APPLICATION_FILES, PACKAGE_DIR / "__init__.py"):
        home_file = home / path
        home_file.parent.mkdir(parents=True, exist_ok=True)
        home_file.touch()
    monkeypatch.setattr(
        deployment, "MUTEX_NAME", f"Local\\Jarvis.Preview.{uuid4().hex}"
    )
    return home


@pytest.mark.parametrize("mode", list(DeploymentMode))
def test_preview_returns_resolved_paths_without_creating_target(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: DeploymentMode
) -> None:
    target = tmp_path / "new home"
    command = ["--source", str(home), "--target", str(target), "--mode", mode.value]

    assert deployment.main([*command, "--preview"]) == 0

    output = capsys.readouterr().out.strip()
    assert output.startswith(deployment.PREVIEW_PREFIX)
    preview = json.loads(output.removeprefix(deployment.PREVIEW_PREFIX))
    assert preview["target"] == str(target)
    assert preview["journal"] == str(target / "journal")
    assert preview["memory"] == str(target / "memory")
    assert preview["mode"] == mode
    assert ("source_journal" in preview) == (mode is DeploymentMode.COPY)
    assert not target.exists()


def test_copy_preview_validates_unsupported_configuration_before_writing(
    home: Path, tmp_path: Path
) -> None:
    (home / "config.toml").write_text('journal.root = "journal"', encoding="utf-8")
    target = tmp_path / "new home"

    with pytest.raises(DeploymentPlanError, match=r"Cannot rebase \[journal\]\.root"):
        deployment.preview_deployment(home, target, DeploymentMode.COPY, resume=False)

    assert not target.exists()


def test_resume_preview_requires_ready_manifest_without_using_source(
    home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "new home"
    assert deployment.deploy(home, target, installer=lambda *_: 7) == 7
    original = (target / deployment.MANIFEST).read_bytes()

    preview = deployment.preview_deployment(
        tmp_path / "absent", target, DeploymentMode.CLEAN, resume=True
    )

    assert preview == {"target": str(target), "mode": "clean"}
    assert (target / deployment.MANIFEST).read_bytes() == original
    with pytest.raises(deployment.DeploymentError, match="target or mode"):
        deployment.preview_deployment(home, target, DeploymentMode.COPY, resume=True)


def test_background_installer_streams_python_output_without_console_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", "source code")
    monkeypatch.setenv("JARVIS_DEPLOY_NONINTERACTIVE", "1")

    def run(args: list[str], *, cwd: Path, env: dict[str, str], check: bool):
        assert cwd == tmp_path
        assert not check
        assert "-NonInteractive" in args
        assert "-Yes" not in args
        assert env["PYTHONUNBUFFERED"] == "1"
        assert "PYTHONPATH" not in env
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(deployment.subprocess, "run", run)
    assert deployment._run_installer(tmp_path, False) == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell worker")
def test_wizard_worker_streams_results_and_reports_retry(tmp_path: Path) -> None:
    fake = tmp_path / "fake deploy.ps1"
    fake.write_text(
        """param($Target, $Mode, [switch]$Preview, [switch]$Resume,
    [switch]$Yes, [switch]$NonInteractive)
if (-not $NonInteractive -or -not $Yes -or $Mode -ne 'copy') { exit 9 }
if ($Preview) { [Console]::WriteLine('JARVIS_DEPLOY_PREVIEW:{}'); exit 0 }
if ($Resume) { [Console]::WriteLine('complete'); exit 0 }
Write-Host "preparing $Target"
[Console]::Error.WriteLine('fake installer failed')
exit 7
""",
        encoding="utf-8",
    )
    marker = tmp_path / deployment.MANIFEST
    marker.write_text(
        json.dumps(
            {"schema": 1, "mode": "copy", "phase": "ready", "target": str(tmp_path)}
        ),
        encoding="utf-8",
    )
    script = tmp_path / "exercise worker.ps1"
    script.write_text(
        """param($Worker, $Backend, $Target)
$ErrorActionPreference = 'Stop'
. $Worker
foreach ($request in @(@($true, $false), @($false, $false), @($false, $true))) {
    $preview = $request[0]
    $resume = $request[1]
    $process = Start-DeploymentWorker $Backend $Target 'copy' $preview $resume $true
    $lines = @()
    do {
        $batch = Receive-DeploymentWorker $process
        $lines += @($batch.Lines | ForEach-Object { $_ })
        if (-not $batch.Done) { Start-Sleep -Milliseconds 20 }
    } until ($batch.Done)
    $retry = (Get-DeploymentWizardPhase $Target 'copy') -eq 'ready'
    $page = Get-DeploymentWizardOutcome $request[0] ($batch.ExitCode -eq 0) $retry
    [pscustomobject]@{ page = $page; code = $batch.ExitCode; lines = $lines } |
        ConvertTo-Json -Compress
    $process.Process.Dispose()
}
""",
        encoding="utf-8",
    )
    result = run_powershell_script(
        script, WIZARD_DIR / "wizard_worker.ps1", fake, tmp_path
    )

    assert result.returncode == 0, result.stdout + result.stderr
    preview, failed, resume = map(json.loads, result.stdout.splitlines())
    assert preview == {
        "page": "review",
        "code": 0,
        "lines": ["JARVIS_DEPLOY_PREVIEW:{}"],
    }
    assert failed["page"] == "retry"
    assert failed["code"] == 7
    assert set(failed["lines"]) == {f"preparing {tmp_path}", "fake installer failed"}
    assert resume == {"page": "finish", "code": 0, "lines": ["complete"]}


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell startup")
def test_wizard_startup_reports_error_and_returns_failure(tmp_path: Path) -> None:
    script = tmp_path / "startup check.ps1"
    script.write_text(
        """param($Startup)
. $Startup
$opened = Invoke-WizardStartup {} { throw 'Unexpected error report' }
$failed = Invoke-WizardStartup { throw 'Invalid XAML fixture' } {
    param($message)
    [Console]::WriteLine($message)
}
[Console]::WriteLine("$opened,$failed")
""",
        encoding="utf-8",
    )

    result = run_powershell_script(script, WIZARD_DIR / "wizard_start.ps1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == ["Invalid XAML fixture", "0,1"]


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell wizard state")
def test_wizard_recognizes_interrupted_preparation_and_ignores_unrelated_marker(
    tmp_path: Path,
) -> None:
    target = tmp_path / "copy"
    target.mkdir()
    marker = target / deployment.MANIFEST
    record = {"schema": 1, "mode": "copy", "phase": "preparing", "target": str(target)}
    marker.write_text(json.dumps(record), encoding="utf-8")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / deployment.MANIFEST).write_text(json.dumps(record), encoding="utf-8")
    script = tmp_path / "preparation phase.ps1"
    script.write_text(
        """param($Worker, $Target, $Unrelated)
$ErrorActionPreference = 'Stop'
. $Worker
[Console]::WriteLine((Get-DeploymentWizardPhase $Target 'clean'))
[Console]::WriteLine((Get-DeploymentPreparationHint $Target))
if (Get-DeploymentWizardPhase $Unrelated 'copy') { exit 9 }
""",
        encoding="utf-8",
    )

    result = run_powershell_script(
        script, WIZARD_DIR / "wizard_worker.ps1", target, unrelated
    )

    assert result.returncode == 0, result.stdout + result.stderr
    phase, hint = result.stdout.splitlines()
    assert phase == "preparing"
    assert str(target) in hint
    assert "Remove the incomplete directory" in hint
    assert "choose a new destination" in hint


def run_powershell_script(
    script: Path, *args: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *(str(arg) for arg in args),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_wizard_xaml_has_every_control_requested_by_controller() -> None:
    tree = ET.parse(WIZARD_DIR / "wizard.xaml")
    tag = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
    names = {node.attrib[tag] for node in tree.iter() if tag in node.attrib}
    controller = (WIZARD_DIR / "wizard.ps1").read_text(encoding="utf-8")
    declared = controller.partition("foreach ($name in @(")[2].partition(")) {")[0]

    assert set(declared.split("'")[1::2]) == names


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell worker")
def test_wizard_worker_reads_the_deployment_result_line(tmp_path: Path) -> None:
    script = tmp_path / "result line.ps1"
    script.write_text(
        r"""param($Worker)
$ErrorActionPreference = 'Stop'
. $Worker
$ok = ConvertFrom-DeploymentResultLine ('JARVIS_DEPLOY_RESULT:' +
    '{"target": "C:\\x", "shortcut_file": "Caf\u00e9 - x.lnk", ' +
    '"shortcut_icon": "C:\\x\\i.ico"}')
[Console]::WriteLine($ok.shortcut_file.Length)
[Console]::WriteLine([int]$ok.shortcut_file[3])
[Console]::WriteLine($ok.shortcut_icon)
foreach ($line in @('Installing Jarvis in C:\x', '', 'JARVIS_DEPLOY_RESULT:{broken',
                    'JARVIS_DEPLOY_PREVIEW:{}')) {
    if (ConvertFrom-DeploymentResultLine $line) { exit 9 }
}
""",
        encoding="utf-8",
    )

    result = run_powershell_script(script, WIZARD_DIR / "wizard_worker.ps1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == ["12", "233", "C:\\x\\i.ico"]
