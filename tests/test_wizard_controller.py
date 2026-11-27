"""The wizard controller (wizard.ps1) driven without showing its window.

The XAML is loaded into objects and the controller's own functions and event
handlers run against a fake source home, but `ShowDialog` is replaced by a
driver, so no window ever appears. The real `deploy.ps1 -CheckBrand` answers.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
from brand_deployment_support import make_source_home
from deploy_cli_support import FAKE_BOOTSTRAP, build_cli_home
from wizard_ps_support import WIZARD_DIR, json_lines, run_powershell

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell and WPF")

DRIVER = r"""
function Pump([string]$Until) {
    for ($i = 0; $i -lt 200; $i++) {
        Start-Sleep -Milliseconds 50
        if ($debounce.IsEnabled -and $i -gt 8) {
            $debounce.Stop()
            Start-IdentityProcessIfNeeded
        }
        Receive-IdentityWorker
        if ($script:identity.CheckStatus -eq $Until) { return }
    }
    throw "The check never reached '$Until': $($script:identity.CheckStatus)"
}
function Snapshot([string]$Label) {
    $image = $controls.PreviewLarge.Source
    [ordered]@{
        label = $Label
        page = $script:page
        status = $script:identity.CheckStatus
        name = $controls.IdentityName.Text
        accent = $controls.IdentityAccent.Text
        nameEnabled = $controls.IdentityName.IsEnabled
        next = $controls.NextButton.IsEnabled
        summary = $controls.IdentitySummary.Text
        caption = $controls.PreviewCaption.Text
        image = if ($image) { $image.GetType().Name } else { $null }
        accentMessage = $controls.IdentityAccentMessage.Text
        monogramMessage = $controls.IdentityMonogramMessage.Text
        hint = $controls.IdentityMonogramHint.Text
        title = $controls.PageTitle.Text
    } | ConvertTo-Json -Compress
}
Snapshot 'first page'
Enter-IdentityPage
Snapshot 'entered'
Pump 'ok'
Snapshot 'read'
$controls.IdentityName.Text = 'Work'
Snapshot 'typed'
Pump 'ok'
Snapshot 'checked'
$controls.IdentityAccent.Text = 'red'
Pump 'invalid'
Snapshot 'bad accent'
$controls.IdentityAccent.Text = '#E0A03F'
$controls.IdentityMonogram.Text = 'AB'
Pump 'invalid'
Snapshot 'bad monogram'
$controls.IdentityMonogram.Text = ''
Pump 'ok'
Snapshot 'fixed'
$clickEvent = [Windows.Controls.Primitives.ButtonBase]::ClickEvent
$click = New-Object Windows.RoutedEventArgs $clickEvent
$controls.NextButton.RaiseEvent($click)
Snapshot 'review started'
[ordered]@{
    label = 'request'
    brand = $script:request.BrandJson
    fromIdentity = $script:request.CameFromIdentity
    mode = $script:request.Mode
} | ConvertTo-Json -Compress
if ($script:worker) { $script:worker.Process.Kill() }
Stop-IdentityCheckProcess
"""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    source = make_source_home(tmp_path / "source")
    build_cli_home(source)
    install = source / "tools" / "install"
    for path in WIZARD_DIR.iterdir():
        shutil.copy2(path, install / path.name)
    packaged = Path("src/jarvis/launcher/assets/jarvis.png")
    (source / packaged).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(WIZARD_DIR.parents[1] / packaged, source / packaged)
    (install / "bootstrap.ps1").write_text(
        FAKE_BOOTSTRAP + "\nfunction Find-Python311 { return $null }\n",
        encoding="utf-8",
    )
    return source


def driven_controller(home: Path, driver: str = DRIVER) -> Path:
    text = (WIZARD_DIR / "wizard.ps1").read_text(encoding="utf-8")
    cut = text.index("Show-WizardPage 'choice'\n$timer.Start()")
    path = home / "tools" / "install" / "wizard_driven.ps1"
    path.write_text(
        text[:cut]
        + "Show-WizardPage 'choice'\n$controls.TargetText.Text = $env:DRIVEN_TARGET\n"
        + driver,
        encoding="utf-8",
    )
    return path


def test_the_identity_page_works_end_to_end_without_a_window(
    home: Path, tmp_path: Path
) -> None:
    result = run_powershell(
        driven_controller(home),
        env={
            "PYTHONIOENCODING": "utf-8",
            "TEST_DEPLOY_PYTHON": sys.executable,
            "TEST_DEPLOY_VENV_READY": "1",
            "DRIVEN_TARGET": str(tmp_path / "never-created"),
        },
        sta=True,
    )

    steps = {step["label"]: step for step in json_lines(result)}
    assert steps["first page"]["summary"] == "Identity: default"
    assert steps["entered"]["status"] == "loading"
    assert steps["entered"]["nameEnabled"] is False
    assert steps["entered"]["next"] is False
    read = steps["read"]
    assert (read["name"], read["accent"], read["next"]) == ("Jarvis", "#3FE0D0", True)
    assert read["caption"] == "The standard Jarvis icon"
    assert read["image"] == "BitmapImage"
    assert steps["typed"]["status"] == "pending" and steps["typed"]["next"] is False
    assert steps["checked"]["caption"] == "Generated monogram W on accent #3FE0D0"
    assert steps["checked"]["image"] == "DrawingImage"
    assert steps["checked"]["hint"] == "Empty keeps the current letter: W"
    assert steps["bad accent"]["accentMessage"] == (
        "[brand].accent must be a #RRGGBB colour, got 'red'"
    )
    assert steps["bad accent"]["next"] is False
    assert steps["bad monogram"]["monogramMessage"].startswith(
        "[brand].monogram must be exactly one Latin or Cyrillic letter or digit"
    )
    assert steps["fixed"]["next"] is True and steps["fixed"]["accentMessage"] == ""
    assert steps["review started"]["page"] == "busy"
    assert steps["review started"]["title"] == "Checking deployment"
    request = steps["request"]
    assert request["brand"] == '{"name":"Work","accent":"#E0A03F"}'
    assert request["fromIdentity"] is True and request["mode"] == "clean"
    assert not (tmp_path / "never-created").exists()


COPY_DRIVER = (
    DRIVER.split("Snapshot 'first page'")[0]
    + r"""
function Press($control) {
    $clickEvent = [Windows.Controls.Primitives.ButtonBase]::ClickEvent
    $control.RaiseEvent((New-Object Windows.RoutedEventArgs $clickEvent))
}
$controls.CopyMode.IsChecked = $true
Enter-IdentityPage
Pump 'ok'
Snapshot 'inherited'
$controls.IdentityName.Text = 'Home'
$controls.CleanMode.IsChecked = $true
[ordered]@{
    label = 'mode changed'
    status = $controls.PageStatus.Text
    summary = $controls.IdentitySummary.Text
    mode = $script:identity.Mode
} | ConvertTo-Json -Compress
$controls.CopyMode.IsChecked = $true
Enter-IdentityPage
Pump 'ok'
Press $controls.RestoreDefaultButton
Pump 'ok'
Snapshot 'restored'
[ordered]@{
    label = 'restored fields'
    readOnly = $controls.IdentityName.IsReadOnly
    name = $controls.IdentityName.Text
    request = (ConvertTo-BrandRequestJson (Get-BrandRequest $script:identity))
    restore = $controls.RestoreDefaultButton.IsEnabled
} | ConvertTo-Json -Compress
Press $controls.DiscardButton
Pump 'ok'
Snapshot 'discarded'
Stop-IdentityCheckProcess
"""
)


def test_a_copy_inherits_the_source_identity_and_offers_the_two_resets(
    home: Path, tmp_path: Path
) -> None:
    (home / "config.toml").write_text(
        '[brand]\nname = "Work"\nmonogram = "W"\naccent = "#E0A03F"\n',
        encoding="utf-8",
    )
    result = run_powershell(
        driven_controller(home, COPY_DRIVER),
        env={
            "PYTHONIOENCODING": "utf-8",
            "TEST_DEPLOY_PYTHON": sys.executable,
            "TEST_DEPLOY_VENV_READY": "1",
            "DRIVEN_TARGET": str(tmp_path / "never-created"),
        },
        sta=True,
    )

    steps = {step["label"]: step for step in json_lines(result)}
    assert (steps["inherited"]["name"], steps["inherited"]["accent"]) == (
        "Work",
        "#E0A03F",
    )
    assert steps["inherited"]["caption"] == "Generated monogram W on accent #E0A03F"
    assert steps["mode changed"] == {
        "label": "mode changed",
        "status": "Identity changes were discarded because the mode changed.",
        "summary": "Identity: default",
        "mode": "clean",
    }
    assert steps["restored fields"]["readOnly"] is True
    assert steps["restored fields"]["name"] == "Jarvis"
    assert steps["restored fields"]["request"] == '{"default_brand":true}'
    assert steps["restored fields"]["restore"] is False
    assert steps["discarded"]["name"] == "Work" and steps["discarded"]["next"]
