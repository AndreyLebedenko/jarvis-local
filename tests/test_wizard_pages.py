"""The wizard's page table and transitions, without a window."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from wizard_ps_support import json_lines, run_snippet

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell wizard")

FLAGS = (
    "ChoiceVisible",
    "IdentityVisible",
    "ReviewVisible",
    "OutputVisible",
    "ProgressVisible",
    "FinishVisible",
    "BackEnabled",
    "NextEnabled",
    "CloseEnabled",
)


def state_of(tmp_path: Path, call: str) -> dict:
    body = f"{call} | ConvertTo-Json -Compress\n"
    return json_lines(run_snippet(tmp_path, body, "wizard_pages.ps1"))[0]


def visible(*names: str) -> dict[str, bool]:
    return {flag: flag.removesuffix("Visible") in names for flag in FLAGS[:6]}


def expected(
    title: str,
    shown: tuple[str, ...],
    next_content: str | None,
    back: bool,
    close: bool,
) -> dict:
    return {
        "Title": title,
        **visible(*shown),
        "BackEnabled": back,
        "NextEnabled": next_content is not None,
        "NextContent": next_content or "Continue",
        "CloseEnabled": close,
    }


# The six pages that existed before the identity page: this table was written
# from the controller's behaviour first and must not change.
EXISTING_PAGES = [
    ("choice", "", expected("Deploy Jarvis", ("Choice",), "Review", False, True)),
    (
        "review",
        "",
        expected("Review deployment", ("Review",), "Deploy", True, True),
    ),
    (
        "review",
        "-Resume $true",
        expected("Review deployment", ("Review",), "Resume installation", True, True),
    ),
    (
        "busy",
        "-Preview $true",
        expected("Checking deployment", ("Output", "Progress"), None, False, False),
    ),
    (
        "busy",
        "-Preview $false",
        expected("Deploying Jarvis", ("Output", "Progress"), None, False, False),
    ),
    (
        "retry",
        "",
        expected(
            "Installation needs attention",
            ("Output",),
            "Resume installation",
            True,
            True,
        ),
    ),
    (
        "error",
        "",
        expected("Deployment could not continue", ("Output",), None, True, True),
    ),
    (
        "finish",
        "",
        expected("Jarvis is ready", ("Output", "Finish"), None, False, True),
    ),
]


@pytest.mark.parametrize(("page", "options", "wanted"), EXISTING_PAGES)
def test_the_pages_that_existed_before_the_identity_page_are_unchanged(
    tmp_path: Path, page: str, options: str, wanted: dict
) -> None:
    assert state_of(tmp_path, f"Get-WizardPageState '{page}' {options}") == wanted


def test_the_identity_page_hides_everything_else_and_waits_for_a_valid_request(
    tmp_path: Path,
) -> None:
    ready = state_of(tmp_path, "Get-WizardPageState 'identity' -IdentityReady $true")
    waiting = state_of(tmp_path, "Get-WizardPageState 'identity' -IdentityReady $false")

    assert ready == expected("Customize identity", ("Identity",), "Review", True, True)
    assert waiting["NextEnabled"] is False
    assert {k: v for k, v in waiting.items() if k != "NextEnabled"} == {
        k: v for k, v in ready.items() if k != "NextEnabled"
    }


def test_other_pages_ignore_whether_the_identity_is_ready(tmp_path: Path) -> None:
    ready = state_of(tmp_path, "Get-WizardPageState 'choice' -IdentityReady $true")
    waiting = state_of(tmp_path, "Get-WizardPageState 'choice' -IdentityReady $false")

    assert ready == waiting


@pytest.mark.parametrize(
    ("page", "came_from_identity", "target"),
    [
        ("review", "$true", "identity"),
        ("review", "$false", "choice"),
        ("identity", "$false", "choice"),
        ("identity", "$true", "choice"),
        ("retry", "$true", "choice"),
        ("error", "$true", "choice"),
        ("choice", "$false", ""),
        ("busy", "$false", ""),
        ("finish", "$false", ""),
    ],
)
def test_back_goes_where_the_owner_came_from(
    tmp_path: Path, page: str, came_from_identity: str, target: str
) -> None:
    body = (
        f"[Console]::WriteLine((Get-WizardBackTarget '{page}' {came_from_identity}))\n"
    )
    result = run_snippet(tmp_path, body, "wizard_pages.ps1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == target


@pytest.mark.parametrize(
    ("request_empty", "check", "phase", "gate"),
    [
        ("$true", "ok", "", "go"),
        ("$true", "pending", "", "go"),
        ("$true", "invalid", "", "go"),
        ("$true", "idle", "ready", "go"),
        ("$false", "ok", "", "go"),
        ("$false", "unavailable", "", "go"),
        ("$false", "pending", "", "identity"),
        ("$false", "invalid", "", "identity"),
        ("$false", "loading", "", "identity"),
        ("$false", "ok", "ready", "resume-conflict"),
        ("$false", "pending", "ready", "resume-conflict"),
    ],
)
def test_review_goes_on_stops_at_the_identity_or_refuses_a_resume(
    tmp_path: Path, request_empty: str, check: str, phase: str, gate: str
) -> None:
    body = (
        f"[Console]::WriteLine((Get-WizardReviewGate {request_empty} '{check}' "
        f"'{phase}'))\n"
    )
    result = run_snippet(tmp_path, body, "wizard_pages.ps1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == gate


def test_the_resume_refusal_tells_what_to_do(tmp_path: Path) -> None:
    result = run_snippet(
        tmp_path,
        "[Console]::WriteLine((Get-ResumeConflictMessage))\n",
        "wizard_pages.ps1",
    )

    assert result.stdout.strip() == (
        "This folder holds a prepared deployment; it resumes with the identity it "
        "was prepared with. Discard the identity changes or choose another folder."
    )
