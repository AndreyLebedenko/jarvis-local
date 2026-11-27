"""The wizard's third mode: change the identity of an existing home."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from wizard_ps_support import json_lines, report, run_snippet

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell wizard")

MODULES = ("wizard_worker.ps1", "wizard_pages.ps1", "wizard_identity.ps1")
STORED = {
    "name": "Work",
    "monogram": "W",
    "accent": "#E0A03F",
    "icon": None,
    "is_default": False,
    "origin": "inherited",
}
ANSWERS = {
    "stored": {
        "ok": True,
        "brand": STORED,
        "icon_preview": {"kind": "monogram", "art": {"code_point": 87}},
    },
    "renamed": {
        "ok": True,
        "brand": {**STORED, "name": "Lab", "origin": "requested"},
        "icon_preview": {"kind": "monogram", "art": {"code_point": 87}},
    },
    "png": {
        "ok": True,
        "brand": {**STORED, "icon": "brand-source/icon.png"},
        "icon_preview": {"kind": "image", "path": "C:\\home\\brand-source\\icon.png"},
    },
    "default": {
        "ok": True,
        "brand": {
            "name": "Jarvis",
            "monogram": "J",
            "accent": "#3FE0D0",
            "icon": None,
            "is_default": True,
            "origin": "default",
        },
        "icon_preview": {"kind": "packaged", "path": "C:\\src\\jarvis.png"},
    },
    "too_old": {
        "ok": False,
        "field": None,
        "message": "C:\\old predates instance branding; update this home first",
    },
}
OPEN = """
$s = New-IdentityState 'rebrand' 'C:\\home'
Request-IdentityStart $s
$null = Start-IdentityCheck $s ([datetime]::Now)
Complete-IdentityCheckProcess $s
[void](Receive-IdentityAnswer $s $s.RequestId $A.{answer})
"""


def drive(tmp_path: Path, body: str) -> list:
    prelude = "$A = $env:ANSWERS | ConvertFrom-Json\n"
    result = run_snippet(
        tmp_path, prelude + body, *MODULES, env={"ANSWERS": json.dumps(ANSWERS)}
    )
    return json_lines(result)


def page(tmp_path: Path, call: str) -> dict:
    body = f"{call} | ConvertTo-Json -Compress\n"
    return json_lines(run_snippet(tmp_path, body, "wizard_pages.ps1"))[0]


# --- pages ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "title", "next_content"),
    [
        ("choice", "Change identity", "Customize identity"),
        ("identity", "Change identity", "Review"),
        ("review", "Review identity change", "Apply"),
        ("busy", "Changing identity", "Continue"),
        ("error", "The identity was not changed", "Continue"),
        ("finish", "Identity changed", "Continue"),
    ],
)
def test_the_rebrand_pages_have_their_own_titles_and_buttons(
    tmp_path: Path, name: str, title: str, next_content: str
) -> None:
    state = page(tmp_path, f"Get-WizardPageState '{name}' -Rebrand $true")

    assert (state["Title"], state["NextContent"]) == (title, next_content)


def test_the_rebrand_pages_show_the_same_panes_as_the_deployment_pages(
    tmp_path: Path,
) -> None:
    for name in ("choice", "identity", "review", "busy", "error", "finish"):
        rebrand = page(tmp_path, f"Get-WizardPageState '{name}' -Rebrand $true")
        deploy = page(tmp_path, f"Get-WizardPageState '{name}'")
        flags = {key for key in deploy if key not in ("Title", "NextContent")}
        assert {key: rebrand[key] for key in flags} == {
            key: deploy[key] for key in flags
        }, name


# --- identity state ---------------------------------------------------------------


def test_the_state_remembers_which_home_it_was_read_from(tmp_path: Path) -> None:
    body = "$s = New-IdentityState 'rebrand' 'C:\\home'\n" + report(
        home="$s.Home", mode="$s.Mode"
    )

    (state,) = drive(tmp_path, body)

    assert state == {"home": "C:\\home", "mode": "rebrand"}


def test_a_rebrand_starts_from_the_stored_brand_and_waits_for_a_change(
    tmp_path: Path,
) -> None:
    body = (
        OPEN.format(answer="stored")
        + "$v = Get-IdentityView $s\n"
        + report(
            name="$v.NameText",
            accent="$v.AccentText",
            request="Get-BrandRequest $s",
            ready="$v.Ready",
            status="$v.Status",
            restore="$v.CanRestoreDefault",
        )
    )

    (state,) = drive(tmp_path, body)

    assert (state["name"], state["accent"], state["request"]) == (
        "Work",
        "#E0A03F",
        None,
    )
    assert state["ready"] is False
    assert state["status"] == "Change at least one value to continue."
    assert state["restore"] is True


def test_an_edit_makes_a_rebrand_ready_once_the_check_agrees(tmp_path: Path) -> None:
    body = (
        OPEN.format(answer="stored")
        + "Set-IdentityText $s 'name' 'Lab'\n"
        + "$pending = Get-IdentityView $s\n"
        + "$null = Start-IdentityCheck $s ([datetime]::Now)\n"
        + "Complete-IdentityCheckProcess $s\n"
        + "[void](Receive-IdentityAnswer $s $s.RequestId $A.renamed)\n"
        + "$done = Get-IdentityView $s\n"
        + report(
            pending="$pending.Ready",
            done="$done.Ready",
            request="ConvertTo-BrandRequestJson (Get-BrandRequest $s)",
        )
    )

    (state,) = drive(tmp_path, body)

    assert state == {"pending": False, "done": True, "request": '{"name":"Lab"}'}


def test_an_unavailable_check_does_not_let_a_rebrand_go_on(tmp_path: Path) -> None:
    body = (
        OPEN.format(answer="stored")
        + "Set-IdentityText $s 'name' 'Lab'\n"
        + "$null = Start-IdentityCheck $s ([datetime]::Now)\n"
        + "Complete-IdentityCheckProcess $s\n"
        + "[void](Receive-IdentityFailure $s $s.RequestId 'no python')\n"
        + "$v = Get-IdentityView $s\n"
        + "$clean = New-IdentityState 'clean'\n"
        + "$clean.CheckStatus = 'unavailable'\n"
        + report(rebrand="$v.Ready", clean="(Get-IdentityView $clean).Ready")
    )

    (state,) = drive(tmp_path, body)

    assert state == {"rebrand": False, "clean": True}


def test_a_home_that_cannot_be_rebranded_keeps_its_own_message(tmp_path: Path) -> None:
    body = (
        OPEN.format(answer="too_old")
        + "$v = Get-IdentityView $s\n"
        + report(general="$v.Messages['general']", ready="$v.Ready")
    )

    (state,) = drive(tmp_path, body)

    assert state == {
        "general": "C:\\old predates instance branding; update this home first",
        "ready": False,
    }


def test_the_png_row_says_which_png_the_home_has_now(tmp_path: Path) -> None:
    body = OPEN.format(answer="png") + report(text="(Get-IdentityView $s).IconText")

    (state,) = drive(tmp_path, body)

    assert state["text"] == "Current PNG: brand-source/icon.png"


def test_restoring_the_default_is_a_request_that_stands_alone(tmp_path: Path) -> None:
    body = (
        OPEN.format(answer="stored")
        + "Use-DefaultIdentity $s\n"
        + report(request="ConvertTo-BrandRequestJson (Get-BrandRequest $s)")
    )

    (state,) = drive(tmp_path, body)

    assert state["request"] == '{"default_brand":true}'


# --- texts ------------------------------------------------------------------------


def test_the_review_names_the_home_the_identity_and_the_files(tmp_path: Path) -> None:
    body = report(
        text="(Get-RebrandReviewLines 'C:\\home' $A.renamed.brand "
        "'C:\\pics\\logo.png') -join '|'"
    )

    (state,) = drive(tmp_path, body)

    assert state["text"] == "|".join(
        [
            "Change the identity of an existing Jarvis home.",
            "Home: C:\\home",
            "",
            "Identity: Lab (changed)",
            "Monogram: W on #E0A03F",
            "",
            "Files that will change:",
            "  config.toml: the [brand] section",
            "  brand-source\\icon.png: a copy of C:\\pics\\logo.png",
            "  brand\\brand.png and brand\\brand.ico: regenerated",
            "",
            "Everything else in the home stays as it is.",
        ]
    )


def test_the_review_of_a_restored_default_says_nothing_is_deleted(
    tmp_path: Path,
) -> None:
    body = report(
        text="(Get-RebrandReviewLines 'C:\\home' $A.default.brand '') -join '|'"
    )

    (state,) = drive(tmp_path, body)

    assert state["text"] == "|".join(
        [
            "Change the identity of an existing Jarvis home.",
            "Home: C:\\home",
            "",
            "Identity: the default Jarvis identity",
            "",
            "Files that will change:",
            "  config.toml: the [brand] section is removed",
            "  brand\\ and brand-source\\ stay as they are; Jarvis ignores them",
            "",
            "Everything else in the home stays as it is.",
        ]
    )


def test_the_finish_text_says_what_refreshes_when(tmp_path: Path) -> None:
    result = {
        "ok": True,
        "brand": STORED,
        "files": ["config.toml", "brand/brand.png", "brand/brand.ico"],
    }
    body = "$r = $env:RESULT | ConvertFrom-Json\n" + report(
        text="(Get-RebrandFinishLines $r) -join '|'"
    )
    result_ = run_snippet(tmp_path, body, *MODULES, env={"RESULT": json.dumps(result)})

    (state,) = json_lines(result_)

    assert state["text"] == "|".join(
        [
            "The identity of this home was changed.",
            "Written: config.toml, brand/brand.png, brand/brand.ico",
            "",
            "The Status Console and window titles change when Jarvis starts next.",
            "The tray name and icon change at the next mode start from the tray,"
            " or after Regenerate icons.",
            "A shortcut you saved earlier keeps its name; save a new one to get"
            " the new name and icon.",
        ]
    )


def test_the_finish_text_warns_that_old_shortcuts_keep_the_old_icon_after_a_restore(
    tmp_path: Path,
) -> None:
    result = {
        "ok": True,
        "brand": ANSWERS["default"]["brand"],
        "files": ["config.toml"],
    }
    body = "$r = $env:RESULT | ConvertFrom-Json\n" + report(
        text="(Get-RebrandFinishLines $r) -join '|'"
    )

    (state,) = json_lines(
        run_snippet(tmp_path, body, *MODULES, env={"RESULT": json.dumps(result)})
    )

    assert "keeps showing the old icon" in state["text"]
