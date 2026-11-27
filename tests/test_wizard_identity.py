"""The Identity page's state and request rules, driven as event sequences."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from wizard_ps_support import WIZARD_DIR, json_lines, report, run_snippet

MODULES = ("wizard_worker.ps1", "wizard_identity.ps1")
windows = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell wizard")
PACKAGED = {"kind": "packaged", "path": "C:\\src\\jarvis.png"}
SAVED = "Set-IdentityText $s 'name' 'Home'\n"


def brand(
    name: str = "Jarvis",
    monogram: str = "J",
    accent: str = "#3FE0D0",
    icon: str | None = None,
    origin: str = "default",
    is_default: bool = True,
) -> dict:
    return {
        "name": name,
        "monogram": monogram,
        "accent": accent,
        "icon": icon,
        "is_default": is_default,
        "origin": origin,
    }


def ok(preview: dict | None = None, **fields) -> dict:
    values = brand(**fields)
    art = {"code_point": ord(values["monogram"]), "disc": values["accent"]}
    return {
        "ok": True,
        "brand": values,
        "icon_preview": preview or {"kind": "monogram", "art": art},
    }


def rejected(field: str | None, message: str) -> dict:
    return {"ok": False, "field": field, "message": message}


MONOGRAM_MESSAGE = (
    "[brand].monogram must be exactly one Latin or Cyrillic letter or digit, got 'AB'"
)
CUSTOM = {"name": "Work", "monogram": "W", "accent": "#E0A03F", "is_default": False}
ANSWERS = {
    "clean": ok(PACKAGED),
    "work": ok(origin="inherited", **CUSTOM),
    "work_png": ok(
        {"kind": "image", "path": "C:\\home\\work.png"},
        icon="brand-source/work.png",
        origin="inherited",
        **CUSTOM,
    ),
    "home": ok(
        name="Home",
        monogram="W",
        accent="#E0A03F",
        origin="requested",
        is_default=False,
    ),
    "default": ok(PACKAGED),
    "bad_monogram": rejected("monogram", MONOGRAM_MESSAGE),
    "bad_name": rejected("name", "[brand].name must be at most 32 characters, got 33"),
    "bad_accent": rejected(
        "accent", "[brand].accent must be a #RRGGBB colour, got 'red'"
    ),
    "bad_icon": rejected(
        "icon", '[brand].icon "C:\\x.png": is not a PNG file (bad signature)'
    ),
    "unsupported": rejected(None, "Cannot rewrite [brand] in C:\\src\\config.toml"),
}


def drive(tmp_path: Path, body: str) -> list:
    """Runs PowerShell `body` (answers in $A) and returns its JSON output lines."""
    prelude = "$A = $env:ANSWERS | ConvertFrom-Json\n"
    result = run_snippet(
        tmp_path, prelude + body, *MODULES, env={"ANSWERS": json.dumps(ANSWERS)}
    )
    return json_lines(result)


def answered(answer: str, mode: str = "clean") -> str:
    """PowerShell that opens the page in `mode` and delivers the named answer."""
    return f"""
$s = New-IdentityState '{mode}'
Request-IdentityStart $s
$null = Start-IdentityCheck $s ([datetime]::Now)
Complete-IdentityCheckProcess $s
[void](Receive-IdentityAnswer $s $s.RequestId $A.{answer})
"""


def reply(answer: str) -> str:
    """PowerShell that runs the pending check and delivers the named answer."""
    return f"""
$null = Start-IdentityCheck $s ([datetime]::Now)
Complete-IdentityCheckProcess $s
[void](Receive-IdentityAnswer $s $s.RequestId $A.{answer})
"""


OPEN_CLEAN = answered("clean")
OPEN_COPY = answered("work", "copy")


@windows
def test_a_fresh_state_sends_nothing_and_the_summary_says_default(
    tmp_path: Path,
) -> None:
    body = "$c = New-IdentityState 'clean'; $k = New-IdentityState 'copy'\n" + report(
        r="Get-BrandRequest $c",
        j="ConvertTo-BrandRequestJson (Get-BrandRequest $c)",
        c="Get-IdentitySummary $c",
        k="Get-IdentitySummary $k",
    )

    (state,) = drive(tmp_path, body)

    assert state == {
        "r": None,
        "j": "",
        "c": "Identity: default",
        "k": "Identity: same as the source",
    }


@windows
def test_opening_the_page_reads_the_start_and_fills_name_and_accent(
    tmp_path: Path,
) -> None:
    body = """
$s = New-IdentityState 'copy'
Request-IdentityStart $s
$loading = Get-IdentityView $s
$action = Get-IdentityCheckAction $s
$started = Start-IdentityCheck $s ([datetime]::Now)
$waiting = Get-IdentityCheckAction $s
Complete-IdentityCheckProcess $s
[void](Receive-IdentityAnswer $s $started.RequestId $A.work)
$view = Get-IdentityView $s
""" + report(
        loading="$loading",
        action="$action",
        json="$started.BrandJson",
        waiting="$waiting",
        after="Get-IdentityCheckAction $s",
        name="$view.NameText",
        accent="$view.AccentText",
        mono="$view.MonogramText",
        hint="$view.MonogramHint",
        ready="$view.Ready",
        request="Get-BrandRequest $s",
        restore="$view.CanRestoreDefault",
    )

    (state,) = drive(tmp_path, body)

    assert state["loading"]["FieldsEnabled"] is False
    assert state["loading"]["Ready"] is False
    assert state["loading"]["Status"] == "Reading the current identity..."
    assert (state["action"], state["json"], state["waiting"], state["after"]) == (
        "start",
        "",
        "wait",
        "idle",
    )
    assert (state["name"], state["accent"], state["mono"]) == ("Work", "#E0A03F", "")
    assert state["hint"] == "Empty keeps the current letter: W"
    assert state["ready"] is True
    assert state["request"] is None, "an untouched Copy must stay a faithful inherit"
    assert state["restore"] is True


@windows
def test_clean_starts_from_the_default_and_offers_no_restore(tmp_path: Path) -> None:
    body = (
        OPEN_CLEAN
        + "$v = Get-IdentityView $s\n"
        + report(
            name="$v.NameText",
            accent="$v.AccentText",
            restore="$v.CanRestoreDefault",
            kind="$v.Preview.Kind",
        )
    )

    (state,) = drive(tmp_path, body)

    assert state == {
        "name": "Jarvis",
        "accent": "#3FE0D0",
        "restore": False,
        "kind": "packaged",
    }


@windows
def test_only_real_edits_become_request_keys(tmp_path: Path) -> None:
    body = (
        OPEN_COPY
        + """
$log = [ordered]@{}
Set-IdentityText $s 'name' 'Home'
$log.renamed = Get-BrandRequest $s
Set-IdentityText $s 'name' 'Work'
$log.typed_back = Get-BrandRequest $s
$log.answer_restored = ($s.CheckStatus -eq 'ok')
Set-IdentityText $s 'accent' '#e0a03f'
$log.same_accent_other_case = Get-BrandRequest $s
Set-IdentityText $s 'accent' '#102030'
$log.accent = Get-BrandRequest $s
Set-IdentityText $s 'accent' '#E0A03F'
Set-IdentityText $s 'monogram' 'h'
$log.monogram = Get-BrandRequest $s
Set-IdentityText $s 'monogram' ''
$log.monogram_cleared = Get-BrandRequest $s
Set-IdentityText $s 'name' ''
$log.empty_name = Get-BrandRequest $s
$log | ConvertTo-Json -Compress
"""
    )

    (log,) = drive(tmp_path, body)

    assert log["renamed"] == {"name": "Home"}
    assert log["typed_back"] is None and log["answer_restored"] is True
    assert log["same_accent_other_case"] is None
    assert log["accent"] == {"accent": "#102030"}
    assert log["monogram"] == {"monogram": "h"}
    assert log["monogram_cleared"] is None
    assert log["empty_name"] == {"name": ""}, "an empty name is Python's to refuse"


@windows
def test_an_edit_that_returns_to_the_start_needs_no_check(tmp_path: Path) -> None:
    body = (
        OPEN_COPY
        + SAVED
        + "Set-IdentityText $s 'name' 'Work'\n"
        + report(action="Get-IdentityCheckAction $s", status="$s.CheckStatus")
    )

    (state,) = drive(tmp_path, body)

    assert state == {"action": "idle", "status": "ok"}


@windows
def test_the_two_reset_affordances_are_the_two_switches(tmp_path: Path) -> None:
    body = (
        answered("work_png", "copy")
        + r"""
$log = [ordered]@{}
Remove-IdentityIcon $s
$log.remove_png = Get-BrandRequest $s
Set-IdentityIcon $s 'C:\pics\new logo.png'
$log.chosen = Get-BrandRequest $s
Remove-IdentityIcon $s
$log.removed_after_choosing = Get-BrandRequest $s
Set-IdentityText $s 'name' 'Home'
Use-DefaultIdentity $s
$log.default = Get-BrandRequest $s
Set-IdentityText $s 'name' 'Ignored'
Set-IdentityIcon $s 'C:\pics\ignored.png'
$log.default_is_terminal = Get-BrandRequest $s
$view = Get-IdentityView $s
$log.read_only = $view.FieldsReadOnly
$log.cannot_choose = -not $view.CanChoosePng
Reset-IdentityEdits $s
$log.discarded = Get-BrandRequest $s
$log.discarded_status = $s.CheckStatus
$log | ConvertTo-Json -Compress
"""
    )

    (log,) = drive(tmp_path, body)

    assert log["remove_png"] == {"no_icon": True}
    assert log["chosen"] == {"icon": "C:\\pics\\new logo.png"}
    assert log["removed_after_choosing"] == {"no_icon": True}
    assert log["default"] == {"default_brand": True}
    assert log["default_is_terminal"] == {"default_brand": True}
    assert log["read_only"] is True and log["cannot_choose"] is True
    assert log["discarded"] is None and log["discarded_status"] == "ok"


@windows
def test_removing_a_chosen_png_in_clean_mode_sends_no_switch(tmp_path: Path) -> None:
    body = (
        OPEN_CLEAN
        + r"""
Set-IdentityIcon $s 'C:\pics\a.png'
$chosen = Get-IdentityView $s
Remove-IdentityIcon $s
"""
        + report(request="Get-BrandRequest $s", can_remove="$chosen.CanRemovePng")
    )

    (state,) = drive(tmp_path, body)

    assert state == {"request": None, "can_remove": True}


@windows
def test_only_the_latest_request_is_ever_answered(tmp_path: Path) -> None:
    body = (
        OPEN_CLEAN
        + """
$log = [ordered]@{}
Set-IdentityText $s 'name' 'W'
$first = Start-IdentityCheck $s ([datetime]::Now)
Set-IdentityText $s 'name' 'Wo'
Set-IdentityText $s 'name' 'Work'
$log.while_running = Get-IdentityCheckAction $s
Complete-IdentityCheckProcess $s
$log.stale_applied = Receive-IdentityAnswer $s $first.RequestId $A.home
$log.status_after_stale = $s.CheckStatus
$log.next = Get-IdentityCheckAction $s
$second = Start-IdentityCheck $s ([datetime]::Now)
$log.second_json = $second.BrandJson
Complete-IdentityCheckProcess $s
$log.applied = Receive-IdentityAnswer $s $second.RequestId $A.home
$log.status = $s.CheckStatus
$log.idle = Get-IdentityCheckAction $s
$log | ConvertTo-Json -Compress
"""
    )

    (log,) = drive(tmp_path, body)

    assert log["while_running"] == "wait"
    assert log["stale_applied"] is False
    assert log["status_after_stale"] == "pending"
    assert log["next"] == "start"
    assert json.loads(log["second_json"]) == {"name": "Work"}
    assert log["applied"] is True and log["status"] == "ok"
    assert log["idle"] == "idle"


@windows
def test_a_check_that_hangs_is_timed_out_after_twenty_seconds(tmp_path: Path) -> None:
    body = "$t = [datetime]'2026-01-01T10:00:00'\n" + report(
        early="Test-IdentityCheckTimedOut $t $t.AddSeconds(19)",
        late="Test-IdentityCheckTimedOut $t $t.AddSeconds(20)",
    )

    (state,) = drive(tmp_path, body)

    assert state == {"early": False, "late": True}


@windows
@pytest.mark.parametrize(
    ("answer", "field"),
    [
        ("bad_monogram", "monogram"),
        ("bad_name", "name"),
        ("bad_accent", "accent"),
        ("bad_icon", "icon"),
        ("unsupported", "general"),
    ],
)
def test_the_planners_message_appears_next_to_the_field_it_names(
    tmp_path: Path, answer: str, field: str
) -> None:
    body = (
        OPEN_CLEAN
        + "Set-IdentityText $s 'name' 'x'\n"
        + reply(answer)
        + "$v = Get-IdentityView $s\n"
        + report(
            messages="$v.Messages",
            ready="$v.Ready",
            kind="$v.Preview.Kind",
            caption="$v.Preview.Caption",
        )
    )

    (state,) = drive(tmp_path, body)

    assert state["messages"][field] == ANSWERS[answer]["message"]
    assert [k for k, v in state["messages"].items() if v] == [field]
    assert state["ready"] is False, "Review stays off while a rejection is shown"
    assert state["kind"] == "none"
    assert state["caption"] == "No preview while the identity is not valid"


@windows
def test_an_invalid_source_identity_can_be_replaced_by_the_default(
    tmp_path: Path,
) -> None:
    body = (
        answered("bad_name", "copy")
        + "$broken = Get-IdentityView $s\nUse-DefaultIdentity $s\n"
        + reply("default")
        + "$fixed = Get-IdentityView $s\n"
        + report(
            messages="$broken.Messages",
            ready="$broken.Ready",
            restore="$broken.CanRestoreDefault",
            fields="$broken.FieldsEnabled",
            fixed_ready="$fixed.Ready",
            name="$fixed.NameText",
            request="Get-BrandRequest $s",
        )
    )

    (state,) = drive(tmp_path, body)

    assert state["messages"]["name"].startswith("[brand].name must be at most 32")
    assert state["messages"]["general"].startswith(
        "The identity of the source is not valid"
    )
    assert state["ready"] is False and state["restore"] is True
    assert state["fields"] is True
    assert state["fixed_ready"] is True and state["name"] == "Jarvis"
    assert state["request"] == {"default_brand": True}


@windows
def test_a_failed_check_leaves_the_page_usable(tmp_path: Path) -> None:
    body = """
$s = New-IdentityState 'clean'
Request-IdentityStart $s
$null = Start-IdentityCheck $s ([datetime]::Now)
Complete-IdentityCheckProcess $s
$stale = Receive-IdentityFailure $s ($s.RequestId - 1) 'old'
[void](Receive-IdentityFailure $s $s.RequestId 'Python 3.11 was not found.')
$start = Get-IdentityView $s
Set-IdentityText $s 'name' 'Work'
$null = Start-IdentityCheck $s ([datetime]::Now)
Complete-IdentityCheckProcess $s
[void](Receive-IdentityFailure $s $s.RequestId 'The check did not finish.')
$edit = Get-IdentityView $s
""" + report(
        stale="$stale",
        start_general="$start.Messages.general",
        start_ready="$start.Ready",
        fields="$start.FieldsEnabled",
        caption="$start.Preview.Caption",
        edit_general="$edit.Messages.general",
        edit_ready="$edit.Ready",
        request="Get-BrandRequest $s",
        name_text="$start.NameText",
    )

    (state,) = drive(tmp_path, body)

    assert state["stale"] is False
    assert state["start_general"] == (
        "Could not read the current identity now: Python 3.11 was not found. "
        "It is checked again at Review."
    )
    assert state["start_ready"] is True and state["fields"] is True
    assert state["caption"] == "Preview unavailable"
    assert state["edit_general"] == (
        "Could not check the identity now: The check did not finish. "
        "It is checked again at Review."
    )
    assert state["edit_ready"] is True
    assert state["request"] == {"name": "Work"}
    assert state["name_text"] == ""


@windows
@pytest.mark.parametrize(
    ("reason", "shown"),
    [
        ("Python 3.11 was not found.", "Python 3.11 was not found."),
        (
            "ModuleNotFoundError: No module named 'x'",
            "ModuleNotFoundError: No module named 'x'.",
        ),
        ("", "No reason was reported."),
    ],
)
def test_a_failure_reason_always_reads_as_a_sentence(
    tmp_path: Path, reason: str, shown: str
) -> None:
    body = (
        "$s = New-IdentityState 'clean'\nRequest-IdentityStart $s\n"
        "[void](Receive-IdentityFailure $s $s.RequestId $env:REASON)\n"
        + report(general="(Get-IdentityView $s).Messages.general")
    )
    result = run_snippet(tmp_path, body, *MODULES, env={"REASON": reason})

    (state,) = json_lines(result)

    assert state["general"] == (
        f"Could not read the current identity now: {shown} "
        "It is checked again at Review."
    )


@windows
def test_the_preview_trails_typing_dimmed_and_never_shows_a_rejected_identity(
    tmp_path: Path,
) -> None:
    body = (
        OPEN_CLEAN
        + """
$log = [ordered]@{}
Set-IdentityText $s 'name' 'Home'
$p = (Get-IdentityView $s).Preview
$log.pending = [ordered]@{ kind = $p.Kind; dimmed = $p.Dimmed }
"""
        + reply("home")
        + """
$p = (Get-IdentityView $s).Preview
$log.ok = [ordered]@{
    kind = $p.Kind; dimmed = $p.Dimmed; caption = $p.Caption; art = $p.Art.code_point
}
$log | ConvertTo-Json -Compress -Depth 4
"""
    )

    (log,) = drive(tmp_path, body)

    assert log["pending"] == {"kind": "packaged", "dimmed": True}
    assert log["ok"] == {
        "kind": "monogram",
        "dimmed": False,
        "caption": "Generated monogram W on accent #E0A03F",
        "art": ord("W"),
    }


@windows
def test_a_mode_change_discards_edits_and_says_so(tmp_path: Path) -> None:
    body = (
        OPEN_COPY
        + """
$unchanged = Switch-IdentityMode $s 'clean'
"""
        + SAVED
        + """
$edited = Switch-IdentityMode $s 'clean'
"""
        + report(
            unchanged="$unchanged.Discarded",
            edited="$edited.Discarded",
            mode="$edited.State.Mode",
            start="$edited.State.StartStatus",
            request="Get-BrandRequest $edited.State",
        )
    )

    (state,) = drive(tmp_path, body)

    assert state == {
        "unchanged": False,
        "edited": True,
        "mode": "clean",
        "start": "unread",
        "request": None,
    }


@windows
def test_the_summary_names_what_changed(tmp_path: Path) -> None:
    body = (
        OPEN_COPY
        + SAVED
        + """
Set-IdentityText $s 'monogram' 'H'
$log = [ordered]@{}
$log.edited = Get-IdentitySummary $s
Remove-IdentityIcon $s
$log.png = Get-IdentitySummary $s
Use-DefaultIdentity $s
$log.default = Get-IdentitySummary $s
$log | ConvertTo-Json -Compress
"""
    )

    (log,) = drive(tmp_path, body)

    assert log["edited"] == "Identity: changed (name, letter)"
    assert log["png"] == "Identity: changed (name, letter)"
    assert log["default"] == "Identity: the default Jarvis identity"


@windows
def test_the_request_json_survives_the_worker_mapping_with_hostile_text(
    tmp_path: Path,
) -> None:
    name = 'Say "hi" & 5% <b> \u0420 t\\'
    body = (
        "$A = $env:ANSWERS | ConvertFrom-Json\n"
        + OPEN_COPY
        + r"""
Set-IdentityText $s 'name' $env:HOSTILE
Set-IdentityText $s 'monogram' 'S'
Set-IdentityIcon $s 'C:\pics\a b.png'
$json = ConvertTo-BrandRequestJson (Get-BrandRequest $s)
$map = ConvertTo-DeployBrandParameters $json
"""
        + report(
            name="$map.Name",
            mono="$map.Monogram",
            icon="$map.Icon",
            keys="@($map.Keys | Sort-Object)",
        )
    )
    result = run_snippet(
        tmp_path,
        body,
        *MODULES,
        env={"ANSWERS": json.dumps(ANSWERS), "HOSTILE": name},
    )

    (state,) = json_lines(result)

    assert state == {
        "name": name,
        "mono": "S",
        "icon": "C:\\pics\\a b.png",
        "keys": ["Icon", "Monogram", "Name"],
    }


@windows
def test_a_message_is_made_safe_to_show(tmp_path: Path) -> None:
    bidi = "got '\u202eevil\u202c'\nnext\u0007"
    body = "$emoji = 'a' + [char]::ConvertFromUtf32(0x1F600) + 'b'\n" + report(
        bidi="Format-IdentityMessage $env:BIDI",
        long="Format-IdentityMessage ('x' * 100000)",
        emoji="Format-IdentityMessage $emoji",
        empty="Format-IdentityMessage ''",
        plain="Format-IdentityMessage 'ordinary text'",
    )
    result = run_snippet(tmp_path, body, *MODULES, env={"BIDI": bidi})

    (state,) = json_lines(result)

    assert state["bidi"] == "got '\ufffdevil\ufffd'\ufffdnext\ufffd"
    assert state["long"] == "x" * 300 + "..."
    assert state["emoji"] == "a\U0001f600b"
    assert state["empty"] == "" and state["plain"] == "ordinary text"


@windows
def test_the_review_lines_describe_only_a_brand_that_is_not_the_default(
    tmp_path: Path,
) -> None:
    body = (
        "$work = $A.work.brand\n$png = $A.work_png.brand\n"
        "$requested = $A.home.brand\n"
        + report(
            default="@(Get-ReviewBrandLines $A.default.brand)",
            inherited="@(Get-ReviewBrandLines $work)",
            icon="@(Get-ReviewBrandLines $png)",
            requested="@(Get-ReviewBrandLines $requested 'C:/p/x.png')",
        )
    )

    (state,) = drive(tmp_path, body)

    assert state["default"] == []
    assert state["inherited"] == [
        "Identity: Work (inherited from the source)",
        "Monogram: W on #E0A03F",
    ]
    assert state["icon"] == [
        "Identity: Work (inherited from the source)",
        "Icon image: brand-source/work.png",
    ]
    assert state["requested"] == ["Identity: Home (changed)", "Monogram: W on #E0A03F"]


def test_the_identity_module_decides_no_brand_rule_itself() -> None:
    text = (WIZARD_DIR / "wizard_identity.ps1").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )

    assert not re.search(r"-(c|i)?(not)?match|\[regex\]|-(c|i)?(not)?like", code)
    assert "{6}" not in code
