"""How the wizard's brand reaches deploy.ps1: worker environment, job, scripts."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from brand_deployment_support import make_source_home
from deploy_cli_support import FAKE_BOOTSTRAP, build_cli_home
from wizard_ps_support import WIZARD_DIR, json_lines, run_powershell, run_snippet

from jarvis.core.config import BrandSettings, load_brand
from tools import deployment
from tools.deployment_brand_check import BRAND_CHECK_PREFIX

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell worker")

HOSTILE = 'Say "hi" & 5% <b> Раб t\\'


def test_the_worker_hands_the_brand_to_the_backend_and_nothing_else(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "fake backend.ps1"
    backend.write_text(
        """param([string]$Target, [string]$Mode, [switch]$Preview, [switch]$Resume,
    [switch]$Yes, [switch]$NonInteractive, [switch]$CheckBrand, [string]$Name,
    [string]$Monogram, [string]$Accent, [string]$Icon, [switch]$NoIcon,
    [switch]$DefaultBrand)
$bound = [ordered]@{}
foreach ($pair in $PSBoundParameters.GetEnumerator()) {
    $value = $pair.Value
    $bound[$pair.Key] = if ($value -is [switch]) { $value.IsPresent } else { $value }
}
[Console]::WriteLine(($bound | ConvertTo-Json -Compress))
exit 0
""",
        encoding="utf-8",
    )
    body = r"""
. $env:WORKER
$cases = @(
    @{ Brand = ''; Check = $false; Target = 'C:\t' },
    @{ Brand = $env:BRAND_TEXT; Check = $false; Target = 'C:\t' },
    @{ Brand = '{"no_icon": true}'; Check = $false; Target = 'C:\t' },
    @{ Brand = '{"default_brand": true}'; Check = $false; Target = 'C:\t' },
    @{ Brand = $env:BRAND_TEXT; Check = $true; Target = '' }
)
foreach ($case in $cases) {
    $worker = Start-DeploymentWorker $env:BACKEND $case.Target 'copy' `
        $true $false $false $case.Brand $case.Check
    $lines = @()
    do {
        $batch = Receive-DeploymentWorker $worker
        $lines += @($batch.Lines | ForEach-Object { $_ })
        if (-not $batch.Done) { Start-Sleep -Milliseconds 20 }
    } until ($batch.Done)
    $worker.Process.Dispose()
    $lines[0]
}
"""
    brand = {
        "name": HOSTILE,
        "monogram": "S",
        "accent": "#E0A03F",
        "icon": r"C:\pics\a b.png",
    }
    result = run_snippet(
        tmp_path,
        body,
        "wizard_worker.ps1",
        env={
            "WORKER": str(WIZARD_DIR / "wizard_worker.ps1"),
            "BACKEND": str(backend),
            "BRAND_TEXT": json.dumps(brand),
            "JARVIS_WIZARD_BRAND": '{"name": "STALE"}',
        },
    )

    none, full, no_icon, default, check = json_lines(result)
    brand_keys = {"Name", "Monogram", "Accent", "Icon", "NoIcon", "DefaultBrand"}
    assert not brand_keys & set(none), "no edits must send no brand data"
    assert none["Mode"] == "copy" and none["Preview"] is True
    assert {k: full[k] for k in ("Name", "Monogram", "Accent", "Icon")} == {
        "Name": HOSTILE,
        "Monogram": "S",
        "Accent": "#E0A03F",
        "Icon": r"C:\pics\a b.png",
    }
    assert no_icon["NoIcon"] is True and "Name" not in no_icon
    assert default["DefaultBrand"] is True and "Name" not in default
    assert set(check) == {
        "CheckBrand",
        "Mode",
        "NonInteractive",
        "Name",
        "Monogram",
        "Accent",
        "Icon",
    }


def test_the_job_parameter_mapping_keeps_empty_values_so_the_planner_can_answer(
    tmp_path: Path,
) -> None:
    body = r"""
$map = ConvertTo-DeployBrandParameters '{"name": "", "accent": "red"}'
$map.Keys | Sort-Object
$map.Name.Length
(ConvertTo-DeployBrandParameters '').Count
"""
    result = run_snippet(tmp_path, body, "wizard_worker.ps1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.split() == ["Accent", "Name", "0", "0"]


def test_the_brand_check_line_parser_ignores_everything_else(tmp_path: Path) -> None:
    body = r"""
$prefix = 'JARVIS_DEPLOY_BRAND_CHECK:'
$answer = ConvertFrom-BrandCheckLine ($prefix + '{"ok": false, "field": "name"}')
$answer.field
$others = @('', ($prefix + '{broken'), 'JARVIS_DEPLOY_PREVIEW:{}', 'ERROR: x')
foreach ($line in $others) {
    if (ConvertFrom-BrandCheckLine $line) { exit 9 }
}
"""
    result = run_snippet(tmp_path, body, "wizard_worker.ps1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.split() == ["name"]


# --- the real job and the real deploy.ps1, against a fake source home --------


@pytest.fixture
def home(tmp_path: Path) -> Path:
    source = make_source_home(tmp_path / "source")
    build_cli_home(source)
    for name in ("wizard_job.ps1", "wizard_worker.ps1"):
        shutil.copy2(WIZARD_DIR / name, source / "tools" / "install" / name)
    (source / "tools/install/bootstrap.ps1").write_text(
        FAKE_BOOTSTRAP + "\nfunction Find-Python311 { return $null }\n",
        encoding="utf-8",
    )
    return source


def run_job(home: Path, tmp_path: Path, **wizard: str) -> tuple[int, list[str], str]:
    stale = tmp_path / "stale-env" / "jarvis" / "__init__.py"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text('raise RuntimeError("imported stale Jarvis")\n', encoding="utf-8")
    result = run_powershell(
        home / "tools" / "install" / "wizard_job.ps1",
        env={
            "PYTHONPATH": str(stale.parents[1]),
            "PYTHONIOENCODING": "utf-8",
            "TEST_DEPLOY_PYTHON": sys.executable,
            "TEST_DEPLOY_VENV_READY": wizard.pop("ready", "1"),
            "JARVIS_WIZARD_SCRIPT": str(home / "tools" / "install" / "deploy.ps1"),
            "JARVIS_WIZARD_TARGET": "",
            "JARVIS_WIZARD_MODE": "clean",
            "JARVIS_WIZARD_PREVIEW": "False",
            "JARVIS_WIZARD_RESUME": "False",
            "JARVIS_WIZARD_CONSENT": "False",
            "JARVIS_WIZARD_BRAND": "",
            "JARVIS_WIZARD_CHECK_BRAND": "False",
            **wizard,
        },
    )
    return result.returncode, result.stdout.splitlines(), result.stderr


def answer_of(lines: list[str], prefix: str) -> dict:
    found = [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]
    assert len(found) == 1, lines
    return json.loads(found[0])


def test_a_check_through_the_job_needs_no_target_and_keeps_a_hostile_name(
    home: Path, tmp_path: Path
) -> None:
    code, lines, errors = run_job(
        home,
        tmp_path,
        JARVIS_WIZARD_CHECK_BRAND="True",
        JARVIS_WIZARD_BRAND=json.dumps({"name": HOSTILE, "monogram": "S"}),
    )

    assert code == 0, errors
    answer = answer_of(lines, BRAND_CHECK_PREFIX)
    assert answer["ok"] is True
    assert answer["brand"]["name"] == HOSTILE
    assert answer["brand"]["origin"] == "requested"


def test_a_check_through_the_job_answers_the_planners_message(
    home: Path, tmp_path: Path
) -> None:
    code, lines, _ = run_job(
        home,
        tmp_path,
        JARVIS_WIZARD_CHECK_BRAND="True",
        JARVIS_WIZARD_BRAND=json.dumps({"monogram": "AB"}),
    )

    assert code == 0
    assert answer_of(lines, BRAND_CHECK_PREFIX) == {
        "ok": False,
        "field": "monogram",
        "message": "[brand].monogram must be exactly one Latin or Cyrillic letter "
        "or digit, got 'AB'",
    }


def test_a_check_never_installs_python_even_when_consent_is_in_the_environment(
    home: Path, tmp_path: Path
) -> None:
    code, lines, errors = run_job(
        home,
        tmp_path,
        ready="0",
        JARVIS_WIZARD_CHECK_BRAND="True",
        JARVIS_WIZARD_CONSENT="True",
    )

    assert code == 1
    assert "Python 3.11 was not found" in errors
    assert not any(line.startswith(BRAND_CHECK_PREFIX) for line in lines)


def test_a_review_through_the_job_validates_the_brand_and_creates_nothing(
    home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "new home"

    code, lines, errors = run_job(
        home,
        tmp_path,
        JARVIS_WIZARD_PREVIEW="True",
        JARVIS_WIZARD_TARGET=str(target),
        JARVIS_WIZARD_BRAND=json.dumps({"name": HOSTILE, "monogram": "S"}),
    )

    assert code == 0, errors
    preview = answer_of(lines, deployment.PREVIEW_PREFIX)
    assert preview["brand"]["name"] == HOSTILE
    assert not target.exists()


def test_a_deployment_through_the_job_applies_the_brand_with_real_icons(
    home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "work home"

    code, lines, errors = run_job(
        home,
        tmp_path,
        JARVIS_WIZARD_TARGET=str(target),
        JARVIS_WIZARD_CONSENT="True",
        JARVIS_WIZARD_BRAND=json.dumps(
            {"name": HOSTILE, "monogram": "S", "accent": "#E0A03F"}
        ),
    )

    assert code == 0, errors + "\n".join(lines)
    assert load_brand(target / "config.toml") == BrandSettings(HOSTILE, "S", "#E0A03F")
    assert (target / "brand" / "brand.ico").is_file()


def test_a_deployment_through_the_job_without_a_brand_is_the_old_deployment(
    home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "plain home"

    code, lines, errors = run_job(
        home,
        tmp_path,
        JARVIS_WIZARD_TARGET=str(target),
        JARVIS_WIZARD_CONSENT="True",
    )

    assert code == 0, errors + "\n".join(lines)
    assert not (target / "brand").exists()
    assert not (target / "brand-source").exists()
