# ruff: noqa: E501
"""Runs the rename parts of app.js in Node against stubs, when Node exists: the
"Rename" menu entry for every session, the editor opened with the shown title,
Enter/Save sends the typed title, an empty field sends a reset, a refusal keeps
the editor open with a reason, and the user title wins in the shown title. A real
window is the human handoff (manual/session-rename-handoff.md)."""

import json
import re
import shutil
import subprocess

import pytest

from jarvis.ui.status_console import UI_DIR

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")

APP_JS = (UI_DIR / "app.js").read_text(encoding="utf-8")
STRINGS_JS = (UI_DIR / "strings.js").read_text(encoding="utf-8")

EXTRACTED = (
    "_journalSessionStartStamp",
    "_journalSessionTitle",
    "_journalSessionMenuEntries",
    "openSessionRenameOverlay",
    "closeSessionRenameOverlay",
    "syncSessionRenameCounter",
    "submitSessionRename",
    "_sessionRenameErrorMessage",
    "_showSessionRenameError",
    "_sessionRenamePlaceholder",
)

HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const calls = [];
const els = {};
function el(id) {
  if (!els[id]) {
    els[id] = {
      id, hidden: true, disabled: false, textContent: "", value: "", maxLength: 0,
      focused: false, selected: false,
      focus() { this.focused = true; },
      select() { this.selected = true; },
      setAttribute() {},
      removeAttribute() {},
    };
  }
  return els[id];
}
const strings = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const context = {
  document: { getElementById: el, activeElement: null },
  uiString: (key) => strings[key] || key,
  _icon: () => ({}),
  _setBackgroundInert: (on) => calls.push("inert:" + on),
  _journalUrl: (path) => path + "?token=t",
  _journalActiveSessionId: null,
  _journalForkInFlightSessionId: null,
  isActionRefused: () => false,
  _isHiddenActive: () => context.hiddenActive,
  hiddenActive: false,
  continueJournalSession: () => {},
  deleteJournalSession: () => {},
  openSessionInfoOverlay: () => {},
  _copyToClipboardWithJournalStatus: () => {},
  refreshJournalSessions: async () => calls.push("refreshJournalSessions"),
  _isJournalSearchActive: () => context.searchActive,
  _scheduleJournalSearch: () => calls.push("scheduleJournalSearch"),
  searchActive: false,
  fetchCalls: [],
  fetchResponse: { status: "ok" },
  fetch: async (url, options) => {
    context.fetchCalls.push({ url, method: options.method, body: options.body, headers: options.headers });
    if (context.fetchResponse instanceof Error) throw context.fetchResponse;
    return { json: async () => context.fetchResponse };
  },
  console,
  els, calls,
};
vm.createContext(context);
const source = fs.readFileSync(process.argv[2], "utf8");
const probe = fs.readFileSync(process.argv[3], "utf8");
vm.runInContext(source + "\n;" + probe, context);
"""

STATE = """
let _journalSessions = [
  { id: "s-live", title: "live text", title_kind: "", has_user_title: false },
  { id: "s-old", title: "old text", title_kind: "", has_user_title: false },
  { id: "s-mine", title: "My own", title_kind: "", has_user_title: true },
  { id: "s-proxy", title: "Personal proxy session", title_kind: "proxy_session", has_user_title: false },
  { id: "s-proxy-mine", title: "Trip", title_kind: "proxy_session", has_user_title: true },
  { id: "s-long", title: ("long first line " + "x".repeat(100) + "\\nsecond   line"), title_kind: "", has_user_title: false },
];
let _sessionRenameReturnFocus = null;
let _sessionRenameSessionId = null;
let _sessionRenameInFlight = false;
let _sessionRenameInitialTitle = "";
const SESSION_TITLE_MAX_CHARS = 80;
"""


def _function_source(name: str) -> str:
    match = re.search(rf"^(async )?function {name}\(", APP_JS, re.M)
    assert match, name
    end = APP_JS.index("\n}\n", match.start())
    return APP_JS[match.start() : end + 2]


def _strings() -> dict:
    en_block = STRINGS_JS.split("ru:", 1)[0]
    return dict(re.findall(r'^\s{4}(\w+): "((?:[^"\\]|\\.)*)",$', en_block, re.M))


def _run(tmp_path, probe: str) -> dict:
    (tmp_path / "harness.js").write_text(HARNESS, encoding="utf-8")
    (tmp_path / "source.js").write_text(
        STATE + "\n".join(_function_source(name) for name in EXTRACTED),
        encoding="utf-8",
    )
    (tmp_path / "probe.js").write_text(probe, encoding="utf-8")
    (tmp_path / "strings.json").write_text(json.dumps(_strings()), encoding="utf-8")
    result = subprocess.run(
        [
            "node",
            str(tmp_path / "harness.js"),
            str(tmp_path / "source.js"),
            str(tmp_path / "probe.js"),
            str(tmp_path / "strings.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_user_title_is_shown_verbatim_even_over_a_placeholder_kind(tmp_path):
    probe = r"""
console.log(JSON.stringify({
  plain: _journalSessionTitle(_journalSessions[1]),
  mine: _journalSessionTitle(_journalSessions[2]),
  proxyAutomatic: _journalSessionTitle(_journalSessions[3]),
  proxyMine: _journalSessionTitle(_journalSessions[4]),
}));
"""

    assert _run(tmp_path, probe) == {
        "plain": "old text",
        "mine": "My own",
        "proxyAutomatic": "Personal proxy session",
        "proxyMine": "Trip",
    }


@pytest.mark.parametrize("session_id", ["s-live", "s-old", "s-mine", "s-proxy"])
def test_every_session_menu_has_a_rename_entry(tmp_path, session_id):
    probe = (
        'globalThis._journalActiveSessionId = "s-live";'
        + rf"""
const entries = _journalSessionMenuEntries({{ dataset: {{ sessionId: {json.dumps(session_id)} }} }});
console.log(JSON.stringify(entries.filter(Boolean).map((entry) => entry.label)));
"""
    )

    labels = _run(tmp_path, probe)

    assert "Rename" in labels


def test_the_live_session_menu_still_has_no_delete_or_continue(tmp_path):
    probe = r"""
globalThis._journalActiveSessionId = "s-live";
const entries = _journalSessionMenuEntries({ dataset: { sessionId: "s-live" } });
console.log(JSON.stringify(entries.filter(Boolean).map((entry) => entry.label)));
"""

    labels = _run(tmp_path, probe)

    assert "Rename" in labels
    assert "Delete session" not in labels
    assert "Continue conversation" not in labels


def test_the_rename_entry_opens_the_editor_with_the_shown_title_selected(tmp_path):
    probe = r"""
const entries = _journalSessionMenuEntries({ dataset: { sessionId: "s-mine" } });
entries.filter(Boolean).find((entry) => entry.label === "Rename").run();
console.log(JSON.stringify({
  hidden: els.sessionRenameOverlay.hidden,
  value: els.sessionRenameInput.value,
  max: els.sessionRenameInput.maxLength,
  focused: els.sessionRenameInput.focused,
  selected: els.sessionRenameInput.selected,
  counter: els.sessionRenameCounter.textContent,
  error: els.sessionRenameError.textContent,
}));
"""

    assert _run(tmp_path, probe) == {
        "hidden": False,
        "value": "My own",
        "max": 80,
        "focused": True,
        "selected": True,
        "counter": "6 / 80",
        "error": "",
    }


def test_a_session_without_a_user_title_opens_empty_with_its_name_as_placeholder(
    tmp_path,
):
    probe = r"""
openSessionRenameOverlay("s-old");
console.log(JSON.stringify({
  value: els.sessionRenameInput.value,
  placeholder: els.sessionRenameInput.placeholder,
  counter: els.sessionRenameCounter.textContent,
}));
"""

    assert _run(tmp_path, probe) == {
        "value": "",
        "placeholder": "old text",
        "counter": "0 / 80",
    }


def test_the_placeholder_of_a_proxy_session_is_its_dated_title(tmp_path):
    probe = r"""
openSessionRenameOverlay("s-proxy");
console.log(JSON.stringify({
  value: els.sessionRenameInput.value, placeholder: els.sessionRenameInput.placeholder }));
"""

    result = _run(tmp_path, probe)

    assert result["value"] == ""
    assert result["placeholder"].startswith("Personal proxy session")


def test_the_placeholder_of_a_long_multiline_name_is_one_line_within_the_limit(
    tmp_path,
):
    probe = r"""
openSessionRenameOverlay("s-long");
console.log(JSON.stringify({
  value: els.sessionRenameInput.value, placeholder: els.sessionRenameInput.placeholder }));
"""

    result = _run(tmp_path, probe)

    assert result["value"] == ""
    assert "\n" not in result["placeholder"]
    assert len(result["placeholder"]) <= 80
    assert result["placeholder"].startswith("long first line xxx")


def test_a_user_title_opens_prefilled_with_no_placeholder(tmp_path):
    probe = r"""
openSessionRenameOverlay("s-mine");
console.log(JSON.stringify({
  value: els.sessionRenameInput.value, placeholder: els.sessionRenameInput.placeholder }));
"""

    assert _run(tmp_path, probe) == {"value": "My own", "placeholder": ""}


def test_saving_an_empty_field_on_a_session_without_a_user_title_sends_nothing(
    tmp_path,
):
    probe = r"""
(async () => {
  openSessionRenameOverlay("s-old");
  await submitSessionRename({ preventDefault() {} });
  console.log(JSON.stringify({
    sent: fetchCalls.length, hidden: els.sessionRenameOverlay.hidden }));
})();
"""

    assert _run(tmp_path, probe) == {"sent": 0, "hidden": True}


def test_saving_an_unchanged_user_title_sends_nothing(tmp_path):
    probe = r"""
(async () => {
  openSessionRenameOverlay("s-mine");
  els.sessionRenameInput.value = "  My own ";
  await submitSessionRename({ preventDefault() {} });
  console.log(JSON.stringify({
    sent: fetchCalls.length, hidden: els.sessionRenameOverlay.hidden }));
})();
"""

    assert _run(tmp_path, probe) == {"sent": 0, "hidden": True}


def test_the_rename_entry_is_disabled_while_hidden(tmp_path):
    probe = r"""
globalThis.hiddenActive = true;
const entries = _journalSessionMenuEntries({ dataset: { sessionId: "s-old" } });
const rename = entries.filter(Boolean).find((entry) => entry.label === "Rename");
console.log(JSON.stringify({ disabled: rename.disabled }));
"""

    assert _run(tmp_path, probe) == {"disabled": True}


def test_the_rename_entry_is_enabled_otherwise(tmp_path):
    probe = r"""
const entries = _journalSessionMenuEntries({ dataset: { sessionId: "s-old" } });
const rename = entries.filter(Boolean).find((entry) => entry.label === "Rename");
console.log(JSON.stringify({ disabled: rename.disabled }));
"""

    assert _run(tmp_path, probe)["disabled"] is False


def test_a_hidden_answer_shows_the_hidden_message_and_keeps_the_editor(tmp_path):
    probe = r"""
(async () => {
  fetchResponse = { status: "hidden" };
  openSessionRenameOverlay("s-old");
  els.sessionRenameInput.value = "x";
  await submitSessionRename({ preventDefault() {} });
  console.log(JSON.stringify({
    hidden: els.sessionRenameOverlay.hidden, error: els.sessionRenameError.textContent }));
})();
"""

    assert _run(tmp_path, probe) == {
        "hidden": False,
        "error": "Journal is hidden; rename is not available.",
    }


def test_the_counter_follows_the_typed_text(tmp_path):
    probe = r"""
openSessionRenameOverlay("s-old");
els.sessionRenameInput.value = "abcde";
syncSessionRenameCounter();
console.log(JSON.stringify({ counter: els.sessionRenameCounter.textContent }));
"""

    assert _run(tmp_path, probe) == {"counter": "5 / 80"}


def test_save_puts_the_typed_title_and_closes_and_refreshes(tmp_path):
    probe = r"""
(async () => {
  openSessionRenameOverlay("s-old");
  els.sessionRenameInput.value = "Pump notes";
  const prevented = [];
  await submitSessionRename({ preventDefault: () => prevented.push(true) });
  console.log(JSON.stringify({
    fetch: context.fetchCalls,
    prevented: prevented.length,
    hidden: els.sessionRenameOverlay.hidden,
    calls,
  }));
})();
""".replace("context.", "")

    result = _run(tmp_path, probe)

    assert result["fetch"] == [
        {
            "url": "/api/journal/sessions/s-old/title?token=t",
            "method": "PUT",
            "body": json.dumps({"title": "Pump notes"}, separators=(",", ":")),
            "headers": {"Content-Type": "application/json"},
        }
    ]
    assert result["prevented"] == 1
    assert result["hidden"] is True
    assert "refreshJournalSessions" in result["calls"]
    assert "scheduleJournalSearch" not in result["calls"]


def test_save_while_a_search_is_shown_reruns_the_search(tmp_path):
    probe = r"""
(async () => {
  searchActive = true;
  openSessionRenameOverlay("s-old");
  els.sessionRenameInput.value = "x";
  await submitSessionRename({ preventDefault() {} });
  console.log(JSON.stringify({ calls }));
})();
"""

    assert "scheduleJournalSearch" in _run(tmp_path, probe)["calls"]


def test_an_emptied_field_sends_an_empty_title_to_reset(tmp_path):
    probe = r"""
(async () => {
  openSessionRenameOverlay("s-mine");
  els.sessionRenameInput.value = "";
  await submitSessionRename({ preventDefault() {} });
  console.log(JSON.stringify({ body: fetchCalls[0].body }));
})();
"""

    assert json.loads(_run(tmp_path, probe)["body"]) == {"title": ""}


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("title_too_long", "Title is longer than 80 characters."),
        ("title_invalid", "Title must be one line of plain text."),
        ("not_found", "Session no longer exists."),
        ("journal_unavailable", "Journal is not available."),
        ("something_else", "Session was not renamed."),
    ],
)
def test_a_refusal_keeps_the_editor_open_and_shows_its_reason(
    tmp_path, reason, message
):
    probe = rf"""
(async () => {{
  fetchResponse = {{ status: "rejected", reason: {json.dumps(reason)} }};
  openSessionRenameOverlay("s-old");
  els.sessionRenameInput.value = "x";
  await submitSessionRename({{ preventDefault() {{}} }});
  console.log(JSON.stringify({{
    hidden: els.sessionRenameOverlay.hidden,
    error: els.sessionRenameError.textContent,
    saveEnabled: els.sessionRenameSave.disabled === false,
    refreshed: calls.includes("refreshJournalSessions"),
  }}));
}})();
"""

    assert _run(tmp_path, probe) == {
        "hidden": False,
        "error": message,
        "saveEnabled": True,
        "refreshed": False,
    }


def test_a_network_failure_keeps_the_editor_open_with_a_generic_message(tmp_path):
    probe = r"""
(async () => {
  fetchResponse = new Error("offline");
  console.error = () => {};
  openSessionRenameOverlay("s-old");
  els.sessionRenameInput.value = "x";
  await submitSessionRename({ preventDefault() {} });
  console.log(JSON.stringify({
    hidden: els.sessionRenameOverlay.hidden,
    error: els.sessionRenameError.textContent,
    saveEnabled: els.sessionRenameSave.disabled === false,
  }));
})();
"""

    assert _run(tmp_path, probe) == {
        "hidden": False,
        "error": "Session was not renamed.",
        "saveEnabled": True,
    }


def test_a_second_submit_while_one_is_in_flight_sends_nothing(tmp_path):
    probe = r"""
(async () => {
  openSessionRenameOverlay("s-old");
  els.sessionRenameInput.value = "x";
  const first = submitSessionRename({ preventDefault() {} });
  const second = submitSessionRename({ preventDefault() {} });
  await Promise.all([first, second]);
  console.log(JSON.stringify({ sent: fetchCalls.length }));
})();
"""

    assert _run(tmp_path, probe) == {"sent": 1}


def test_closing_the_editor_restores_the_page_and_forgets_the_session(tmp_path):
    probe = r"""
openSessionRenameOverlay("s-old");
closeSessionRenameOverlay();
console.log(JSON.stringify({
  hidden: els.sessionRenameOverlay.hidden, session: _sessionRenameSessionId, calls,
}));
"""

    result = _run(tmp_path, probe)

    assert result["hidden"] is True
    assert result["session"] is None
    assert result["calls"] == ["inert:true", "inert:false"]
