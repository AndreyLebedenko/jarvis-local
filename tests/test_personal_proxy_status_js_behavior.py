# ruff: noqa: E501
"""Runs proxy_text.js, the real string catalog and the status part of
proxy_chat.js in Node, when Node exists: the dry-run indicator, the last block
reason, and the wording of a content-free notice in both languages."""

import json
import shutil
import subprocess

import pytest

from jarvis.ui.status_console import UI_DIR

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")

HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const ids = {
  proxyDryRun: { hidden: true, textContent: "" },
  proxyLastBlock: { hidden: true, textContent: "" },
};
const context = {
  document: { getElementById: (id) => ids[id] || null },
  console,
  ids,
};
vm.createContext(context);
const sources = process.argv.slice(2, -1).map((f) => fs.readFileSync(f, "utf8"));
const probe = fs.readFileSync(process.argv[process.argv.length - 1], "utf8");
vm.runInContext(sources.join("\n") + "\n;" + probe, context);
"""

PHONE_BLOCK = {
    "kind": "gate_blocked",
    "detail": [
        {"category": "phone", "message_index": 1, "start": 4, "end": 9, "stage": None}
    ],
}


def _run(tmp_path, probe: str) -> dict:
    harness = tmp_path / "harness.js"
    probe_file = tmp_path / "probe.js"
    harness.write_text(HARNESS, encoding="utf-8")
    probe_file.write_text(probe, encoding="utf-8")
    sources = [UI_DIR / name for name in ("strings.js", "proxy_text.js")]
    sources.append(UI_DIR / "proxy_chat.js")
    result = subprocess.run(
        ["node", str(harness), *map(str, sources), str(probe_file)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_dry_run_indicator_follows_the_status(tmp_path):
    probe = r"""
applyProxyStatus({dry_run: true, last_block: null});
const on = ids.proxyDryRun.hidden;
applyProxyStatus({dry_run: false, last_block: null});
console.log(JSON.stringify({on, off: ids.proxyDryRun.hidden}));
"""

    assert _run(tmp_path, probe) == {"on": False, "off": True}


def test_the_last_block_reason_names_the_category_and_position_and_clears(tmp_path):
    probe = (
        "applyProxyStatus({dry_run: false, last_block: "
        + json.dumps(PHONE_BLOCK)
        + r"""});
const shown = {hidden: ids.proxyLastBlock.hidden, text: ids.proxyLastBlock.textContent};
applyProxyStatus({dry_run: false, last_block: null});
console.log(JSON.stringify({shown, cleared: ids.proxyLastBlock.hidden,
  clearedText: ids.proxyLastBlock.textContent}));
"""
    )

    result = _run(tmp_path, probe)

    assert result["shown"] == {
        "hidden": False,
        "text": (
            "Last stop: Blocked by the outbound check, nothing sent "
            "(phone number, message 1, characters 4-9)"
        ),
    }
    assert result["cleared"] is True
    assert result["clearedText"] == ""


def test_a_missing_status_means_no_dry_run_and_no_reason(tmp_path):
    probe = r"""
applyProxyStatus(undefined);
console.log(JSON.stringify({dry: ids.proxyDryRun.hidden, reason: ids.proxyLastBlock.hidden}));
"""

    assert _run(tmp_path, probe) == {"dry": True, "reason": True}


def test_a_notice_is_worded_in_russian_too(tmp_path):
    probe = '_uiLanguage = "ru"; console.log(JSON.stringify({text: proxyNoticeText("refused", null)}));'

    assert _run(tmp_path, probe) == {"text": "Запрос отклонён, ничего не отправлено"}


def test_every_notice_kind_and_gate_category_has_a_string_in_both_languages(
    tmp_path,
):
    from jarvis.personal_proxy.findings import GateCategory
    from jarvis.personal_proxy.service_blocks import NoticeKind

    keys = [f"proxy_notice_{kind.value}" for kind in NoticeKind] + [
        f"proxy_gate_category_{category.value}" for category in GateCategory
    ]
    probe = (
        "const keys = "
        + json.dumps(keys)
        + r""";
const missing = [];
for (const language of ["en", "ru"]) {
  _uiLanguage = language;
  for (const key of keys) {
    try { uiString(key); } catch (e) { missing.push(language + ":" + key); }
  }
}
console.log(JSON.stringify({missing}));
"""
    )

    assert _run(tmp_path, probe) == {"missing": []}


def test_enum_details_are_worded_in_the_ui_language_never_as_a_slug(tmp_path):
    probe = r"""
const out = {};
for (const language of ["en", "ru"]) {
  _uiLanguage = language;
  out[language] = [
    proxyNoticeText("not_sent", "timed_out"),
    proxyNoticeText("sanitize_failed", "no_json"),
  ];
}
console.log(JSON.stringify(out));
"""

    result = _run(tmp_path, probe)

    assert result["ru"] == [
        "Не отправлено (нет подтверждения) (нет ответа вовремя)",
        "Запрос не удалось подготовить, ничего не отправлено "
        "(нет структурированного результата)",
    ]
    assert "timed_out" not in " ".join(result["en"] + result["ru"])
    assert "no_json" not in " ".join(result["en"] + result["ru"])


def test_every_enum_that_can_ride_in_a_notice_has_a_string_in_both_languages(
    tmp_path,
):
    from jarvis.personal_proxy.confirmation_outcome import ExchangeOutcome
    from jarvis.personal_proxy.external_error import ExternalErrorKind
    from jarvis.personal_proxy.sanitize_result import SanitizeFailureClass

    values = {
        member.value
        for enum in (ExchangeOutcome, SanitizeFailureClass, ExternalErrorKind)
        for member in enum
    }
    probe = (
        "const values = "
        + json.dumps(sorted(values))
        + r""";
const missing = [];
for (const language of ["en", "ru"]) {
  _uiLanguage = language;
  for (const value of values) {
    if (optionalUiString("proxy_detail_" + value) === null) {
      missing.push(language + ":" + value);
    }
  }
}
console.log(JSON.stringify({missing}));
"""
    )

    assert _run(tmp_path, probe) == {"missing": []}


def test_a_stored_record_of_an_unknown_kind_or_category_reads_neutrally(tmp_path):
    probe = r"""
const finding = {category: "from_the_future", message_index: 0, start: 1, end: 2};
console.log(JSON.stringify({
  kind: proxyNoticeText("from_the_future", null),
  category: proxyNoticeText("gate_blocked", [finding]),
  detail: proxyNoticeText("not_sent", "from_the_future"),
}));
"""

    result = _run(tmp_path, probe)

    assert result["kind"] == "Notice of an unknown kind"
    assert "unknown category, message 0, characters 1-2" in result["category"]
    assert result["detail"] == "Not sent (not confirmed)"


def test_the_dry_run_state_is_remembered_for_the_dock_status_line(tmp_path):
    probe = r"""
const initial = isProxyDryRun();
applyProxyStatus({dry_run: true, last_block: null});
const on = isProxyDryRun();
applyProxyStatus({dry_run: false, last_block: null});
const off = isProxyDryRun();
applyProxyStatus(undefined);
console.log(JSON.stringify({initial, on, off, missing: isProxyDryRun()}));
"""

    assert _run(tmp_path, probe) == {
        "initial": False,
        "on": True,
        "off": False,
        "missing": False,
    }


def test_the_proxy_mode_disables_the_attach_button_on_the_client(tmp_path):
    app = (UI_DIR / "app.js").read_text(encoding="utf-8")
    sync = (
        "function _syncJournalInputControls("
        + app.split("function _syncJournalInputControls(")[1].split("\n}\n")[0]
        + "\n}"
    )
    targets = (
        "function _journalInputTargetsSelectedSession("
        + app.split("function _journalInputTargetsSelectedSession(")[1].split("\n}\n")[
            0
        ]
        + "\n}"
    )
    run_mode = (
        "function _isProxyRunMode("
        + app.split("function _isProxyRunMode(")[1].split("\n}\n")[0]
        + "\n}"
    )
    probe = (
        sync
        + targets
        + run_mode
        + r"""
globalThis.RUN_MODE = { PERSONAL_PROXY: "personal_proxy" };
globalThis._journalActiveSessionId = "s";
globalThis._journalSelectedSessionId = "s";
globalThis._journalInputInFlight = false;
globalThis._isHiddenActive = () => false;
globalThis.isActionRefused = () => false;
const result = {};
for (const mode of ["personal_proxy", "normal"]) {
  const els = {};
  for (const id of ["journalTextInput", "journalSendButton", "journalAttachButton",
                    "journalFileInput"]) els[id] = { disabled: null };
  els.journalInputDock = { classList: { toggle: () => {} } };
  globalThis.document = {
    getElementById: (id) => els[id] || null,
    documentElement: { getAttribute: () => mode },
  };
  _syncJournalInputControls();
  result[mode] = {
    attach: els.journalAttachButton.disabled,
    file: els.journalFileInput.disabled,
    text: els.journalTextInput.disabled,
    send: els.journalSendButton.disabled,
  };
}
console.log(JSON.stringify(result));
"""
    )

    result = _run(tmp_path, probe)

    assert result["personal_proxy"] == {
        "attach": True,
        "file": True,
        "text": False,
        "send": False,
    }
    assert result["normal"]["attach"] is False
