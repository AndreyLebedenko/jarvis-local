# ruff: noqa: E501
"""Runs the dock parts of app.js in Node against stubs, when Node exists: when
the Journal dock takes a request in the personal proxy mode, what a typed request
sends, and the empty state after "New context". A real window is the human
handoff (manual/personal-proxy-input-dock-handoff.md)."""

import json
import re
import shutil
import subprocess

import pytest

from jarvis.ui.status_console import UI_DIR

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")

APP_JS = (UI_DIR / "app.js").read_text(encoding="utf-8")

EXTRACTED = (
    "_isProxyRunMode",
    "_journalInputTargetsSelectedSession",
    "_syncJournalInputControls",
    "submitJournalInput",
    "_journalInputErrorMessage",
    "startNewJournalContext",
    "_showJournalNewSessionEmpty",
    "_journalShowsNewSessionState",
    "_applyJournalUsage",
    "refreshJournalSessions",
    "selectJournalSession",
    "_shouldSelectJournalInputSession",
    "_journalEventBodyText",
    "_journalSentHidesSystemPrompt",
    "_journalSentIsForced",
    "_isJournalActive",
    "applyJournalEvent",
    "setActiveView",
    "_maybeRefetchJournalFeed",
)

HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const calls = [];
const els = {};
function el(id) {
  if (!els[id]) {
    els[id] = {
      id, disabled: null, hidden: false, textContent: "", value: "", children: [],
      classes: {},
      classList: { toggle(name, on) { els[id].classes[name] = on; } },
      replaceChildren() { els[id].children = []; calls.push(id + ".replaceChildren"); },
      appendChild(c) { els[id].children.push(c); return c; },
      querySelectorAll: () => ({ forEach: () => {} }),
      setAttribute() {},
    };
  }
  return els[id];
}
const mode = { value: "personal_proxy" };
const view = { value: "journal" };
const context = {
  document: {
    getElementById: el,
    documentElement: {
      getAttribute: (name) => (name === "data-view" ? view.value : mode.value),
      setAttribute: (name, value) => { if (name === "data-view") view.value = value; },
    },
    querySelectorAll: () => ({ forEach: () => {} }),
  },
  RUN_MODE: { PERSONAL_PROXY: "personal_proxy" },
  PROXY_HEARD_SOURCE: "proxy_heard",
  uiString: (key) => key,
  proxyNoticeText: () => "",
  isActionRefused: () => false,
  _isHiddenActive: () => false,
  _journalUrl: (path) => path + "?token=t",
  _journalPendingAttachmentFiles: () => [],
  _clearCompletedJournalAttachments: () => {},
  _clearJournalAttachments: () => {},
  _journalPersistIndices: () => [],
  _applyJournalAttachmentResults: () => {},
  _setJournalInputStatus: (key) => { context.lastStatus = key; },
  _updateJournalNewContextButton: () => {},
  _confirmStartNewJournalContext: () => true,
  _confirmDiscardJournalMemoryChanges: () => true,
  clearProxyChatBlocks: () => calls.push("clearProxyChatBlocks"),
  isProxyDryRun: () => context.dryRun,
  dryRun: false,
  lastStatus: "",
  fetchCalls: [],
  fetchResponse: { status: "accepted" },
  fetch: async (url, options) => {
    context.fetchCalls.push({ url, body: options.body });
    return { json: async () => context.fetchResponse };
  },
  console,
  _isJournalSearchActive: () => false,
  _deactivateJournalSearch: () => {},
  _clearJournalSearchControls: () => {},
  _journalContentGeneration: 0,
  _journalFeedFetchesInFlight: 0,
  _fetchJournalJson: async () => null,
  _formatJournalBytes: () => "",
  _journalSessionElement: (session) => ({ session }),
  initRovingList: () => {},
  initContextMenuTrigger: () => {},
  _journalSessionMenuEntries: () => [],
  refreshRovingList: () => {},
  _scheduleJournalSearch: () => {},
  _stopJournalPlayback: () => {},
  _clearJournalContextHighlight: () => {},
  ACTIVE_VIEWS: ["status", "journal", "settings"],
  syncRadioGroup: () => {},
  refreshSettingsOptions: () => {},
  _renderJournalFeed: () => {},
  _reloadJournalAnnotationsIfOpen: () => {},
  _reloadJournalConsolidationIfOpen: () => {},
  _appendJournalTurn: () => {},
  setTimeout,
  calls, els, mode, view,
};
vm.createContext(context);
const source = fs.readFileSync(process.argv[2], "utf8");
const probe = fs.readFileSync(process.argv[3], "utf8");
vm.runInContext(source + "\n;" + probe, context);
"""

STATE = """
let _journalSelectedSessionId = null;
let _journalActiveSessionId = null;
let _journalInputInFlight = false;
let _journalSelectPendingInputSession = false;
let _journalNewSessionPending = false;
let _journalNewContextInFlight = false;
let _journalSessions = [];
let _journalUsageBySession = new Map();
let _journalFeedRefetchSessionId = null;
"""


def _function_source(name: str) -> str:
    match = re.search(rf"^(async )?function {name}\(", APP_JS, re.M)
    assert match, name
    end = APP_JS.index("\n}\n", match.start())
    return APP_JS[match.start() : end + 2]


def _run(tmp_path, probe: str) -> dict:
    (tmp_path / "harness.js").write_text(HARNESS, encoding="utf-8")
    (tmp_path / "source.js").write_text(
        STATE + "\n".join(_function_source(name) for name in EXTRACTED),
        encoding="utf-8",
    )
    (tmp_path / "probe.js").write_text(probe, encoding="utf-8")
    result = subprocess.run(
        [
            "node",
            str(tmp_path / "harness.js"),
            str(tmp_path / "source.js"),
            str(tmp_path / "probe.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


DOCK_STATE_PROBE = r"""
function dockState(run, active, selected) {
  mode.value = run;
  _journalActiveSessionId = active;
  _journalSelectedSessionId = selected;
  _syncJournalInputControls();
  return {
    enabled: els.journalTextInput.disabled === false && els.journalSendButton.disabled === false,
    inactiveNote: els.journalInputDock.classes["inactive-session"] === true,
  };
}
"""

ENABLED = {"enabled": True, "inactiveNote": False}
INACTIVE = {"enabled": False, "inactiveNote": True}


@pytest.mark.parametrize(
    ("run_mode", "active", "selected", "expected"),
    [
        ("personal_proxy", "live", "live", ENABLED),
        ("personal_proxy", None, None, ENABLED),
        ("personal_proxy", None, "older", ENABLED),
        ("personal_proxy", "live", "older", INACTIVE),
        ("personal_proxy", "live", None, INACTIVE),
        ("normal", "live", "live", ENABLED),
        ("normal", None, None, INACTIVE),
        ("normal", None, "older", INACTIVE),
        ("normal", "live", "older", INACTIVE),
    ],
)
def test_the_dock_is_enabled_by_the_live_session_or_by_having_none_in_the_proxy(
    tmp_path, run_mode, active, selected, expected
):
    probe = (
        DOCK_STATE_PROBE
        + f"console.log(JSON.stringify(dockState({json.dumps(run_mode)}, {json.dumps(active)}, {json.dumps(selected)})));"
    )

    assert _run(tmp_path, probe) == expected


def test_the_dock_stays_disabled_while_hidden_even_without_a_live_session(tmp_path):
    probe = (
        DOCK_STATE_PROBE
        + r"""
globalThis._isHiddenActive = () => true;
console.log(JSON.stringify(dockState("personal_proxy", null, null)));
"""
    )

    assert _run(tmp_path, probe)["enabled"] is False


def test_attachments_stay_off_in_the_proxy_dock_even_with_no_live_session(tmp_path):
    probe = (
        DOCK_STATE_PROBE
        + r"""
dockState("personal_proxy", null, null);
console.log(JSON.stringify({
  attach: els.journalAttachButton.disabled, file: els.journalFileInput.disabled}));
"""
    )

    assert _run(tmp_path, probe) == {"attach": True, "file": True}


def test_a_typed_request_with_no_live_session_is_posted_to_the_input_route(tmp_path):
    probe = r"""
mode.value = "personal_proxy";
els.journalTextInput = { value: "ask something" };
(async () => {
  await submitJournalInput();
  console.log(JSON.stringify({
    posted: context.fetchCalls,
    status: context.lastStatus,
    pendingSelect: _journalSelectPendingInputSession,
    inputCleared: els.journalTextInput.value,
  }));
})();
""".replace("context.", "")

    result = _run(tmp_path, probe)

    assert result["posted"] == [
        {
            "url": "/api/journal/input?token=t",
            "body": json.dumps({"text": "ask something"}, separators=(",", ":")),
        }
    ]
    assert result["status"] == "journal_input_sent"
    assert result["pendingSelect"] is True
    assert result["inputCleared"] == ""


def test_the_normal_mode_still_demands_a_new_context_before_posting(tmp_path):
    probe = r"""
mode.value = "normal";
els.journalTextInput = { value: "hello" };
(async () => {
  await submitJournalInput();
  console.log(JSON.stringify({posted: fetchCalls.length, status: lastStatus}));
})();
"""

    assert _run(tmp_path, probe) == {
        "posted": 0,
        "status": "journal_new_context_required",
    }


def test_a_request_sent_in_a_dry_run_says_the_result_is_in_the_status_view(tmp_path):
    probe = r"""
mode.value = "personal_proxy";
dryRun = true;
els.journalTextInput = { value: "ask" };
(async () => {
  await submitJournalInput();
  console.log(JSON.stringify({
    status: lastStatus, pendingSelect: _journalSelectPendingInputSession}));
})();
"""

    assert _run(tmp_path, probe) == {
        "status": "journal_input_sent_dry_run",
        "pendingSelect": False,
    }


def test_a_refused_request_keeps_its_reason_and_the_unavailable_detail(tmp_path):
    probe = r"""
console.log(JSON.stringify({
  detail: _journalInputErrorMessage({reason: "unavailable", detail: "Ollama is not running."}),
  bare: _journalInputErrorMessage({reason: "unavailable"}),
  busy: _journalInputErrorMessage({reason: "busy"}),
}));
"""

    assert _run(tmp_path, probe) == {
        "detail": "Ollama is not running.",
        "bare": "journal_input_failed",
        "busy": "journal_input_busy",
    }


NEW_CONTEXT_PROBE = r"""
mode.value = "personal_proxy";
_journalActiveSessionId = "live";
_journalSelectedSessionId = "live";
fetchResponse = {status: "ok", session_id: null};
els.journalFeedEmpty = {hidden: true, textContent: "", replaceChildren() {}};
(async () => {
  await startNewJournalContext();
  console.log(JSON.stringify({
    selected: _journalSelectedSessionId,
    active: _journalActiveSessionId,
    pending: _journalNewSessionPending,
    emptyShown: els.journalFeedEmpty.hidden === false,
    emptyText: els.journalFeedEmpty.textContent,
    feedWiped: calls.includes("journalFeed.replaceChildren"),
    ribbonCleared: calls.includes("clearProxyChatBlocks"),
    dockEnabled: els.journalTextInput.disabled === false,
    status: lastStatus,
  }));
})();
"""


def test_after_new_context_in_the_proxy_the_feed_is_empty_and_nothing_is_selected(
    tmp_path,
):
    result = _run(tmp_path, NEW_CONTEXT_PROBE)

    assert result == {
        "selected": None,
        "active": None,
        "pending": True,
        "emptyShown": True,
        "emptyText": "journal_proxy_new_session_empty",
        "feedWiped": True,
        "ribbonCleared": True,
        "dockEnabled": True,
        "status": "journal_new_context_ready_proxy",
    }


SESSIONS = [
    {"id": "20261023-100000-aaaa", "start_timestamp": "2026-10-23T10:00:00+01:00"},
    {"id": "20261022-100000-bbbb", "start_timestamp": "2026-10-22T10:00:00+01:00"},
]

REFRESH_PROBE = r"""
mode.value = RUN_MODE_VALUE;
_journalNewSessionPending = PENDING;
_journalSelectedSessionId = null;
els.journalSessionList = {replaceChildren() {}, appendChild() {}};
els.journalSessionsEmpty = {hidden: true};
els.journalUsageTotal = {textContent: ""};
els.journalFeedEmpty = {hidden: true, textContent: ""};
_fetchJournalJson = async (path) => path.includes("sessions")
  ? {sessions: SESSIONS}
  : {total_bytes: 0, active_session_id: ACTIVE, sessions: []};
const selected = [];
globalThis.selectJournalSession = (id) => selected.push(id);
(async () => {
  await refreshJournalSessions();
  console.log(JSON.stringify({
    selected,
    emptyShown: els.journalFeedEmpty.hidden === false,
    emptyText: els.journalFeedEmpty.textContent,
  }));
})();
""".replace("SESSIONS", json.dumps(SESSIONS))

NEWEST = "20261023-100000-aaaa"
NEW_SESSION_EMPTY = {
    "selected": [],
    "emptyShown": True,
    "emptyText": "journal_proxy_new_session_empty",
}


def _refresh(tmp_path, run_mode, pending, active):
    probe = (
        REFRESH_PROBE.replace("RUN_MODE_VALUE", json.dumps(run_mode))
        .replace("PENDING", pending)
        .replace("ACTIVE", json.dumps(active))
    )
    return _run(tmp_path, probe)


def test_the_session_list_does_not_pick_an_older_session_while_a_new_one_is_pending(
    tmp_path,
):
    assert _refresh(tmp_path, "personal_proxy", "true", None) == NEW_SESSION_EMPTY


def test_at_start_in_the_proxy_with_no_live_session_the_new_session_state_shows(
    tmp_path,
):
    assert _refresh(tmp_path, "personal_proxy", "false", None) == NEW_SESSION_EMPTY


def test_the_proxy_with_a_live_session_opens_the_newest_session(tmp_path):
    result = _refresh(tmp_path, "personal_proxy", "false", NEWEST)

    assert result["selected"] == [NEWEST]


def test_the_normal_mode_still_opens_the_newest_session_without_a_live_one(tmp_path):
    result = _refresh(tmp_path, "normal", "false", None)

    assert result["selected"] == [NEWEST]


def test_a_live_session_that_appeared_while_pending_is_selected_not_the_empty_state(
    tmp_path,
):
    result = _refresh(tmp_path, "personal_proxy", "true", NEWEST)

    assert result["selected"] == [NEWEST]


def test_the_dock_says_a_request_starts_a_new_session_only_without_a_live_one(
    tmp_path,
):
    probe = (
        DOCK_STATE_PROBE
        + r"""
const out = {};
for (const [name, run, active, selected] of [
  ["none", "personal_proxy", null, null],
  ["noneOlderOpen", "personal_proxy", null, "older"],
  ["live", "personal_proxy", "live", "live"],
  ["olderWhileLive", "personal_proxy", "live", "older"],
  ["normal", "normal", null, null],
]) {
  dockState(run, active, selected);
  out[name] = els.journalInputDock.classes["starts-new-session"] === true;
}
console.log(JSON.stringify(out));
"""
    )

    assert _run(tmp_path, probe) == {
        "none": True,
        "noneOlderOpen": True,
        "live": False,
        "olderWhileLive": False,
        "normal": False,
    }


def test_a_request_spoken_in_another_view_is_selected_when_the_journal_returns(
    tmp_path,
):
    probe = r"""
mode.value = "personal_proxy";
view.value = "journal";
let serverActive = null;
let sessions = [{id: "OLD", start_timestamp: "2026-10-22T10:00:00+01:00"}];
_fetchJournalJson = async (path) => path.includes("usage")
  ? {total_bytes: 0, active_session_id: serverActive, sessions: []}
  : path.includes("sessions/")
    ? {events: []}
    : {sessions};
for (const id of ["journalSessionList", "journalSessionsEmpty", "journalUsageTotal",
                  "journalFeedEmpty"]) els[id] = {
  hidden: false, textContent: "", replaceChildren() {}, appendChild() {},
  querySelectorAll: () => ({forEach: () => {}}),
};
const tick = () => new Promise((resolve) => setTimeout(resolve, 20));
(async () => {
  fetchResponse = {status: "ok", session_id: null};
  await startNewJournalContext();
  const afterNewContext = {pending: _journalNewSessionPending, selected: _journalSelectedSessionId};
  setActiveView("status");
  serverActive = "NEW";
  sessions = [{id: "NEW", start_timestamp: "2026-10-23T10:00:00+01:00"}, ...sessions];
  applyJournalEvent({session_id: "NEW", role: "user", source: "proxy_heard"});
  setActiveView("journal");
  await tick();
  console.log(JSON.stringify({
    afterNewContext,
    selected: _journalSelectedSessionId,
    active: _journalActiveSessionId,
    pending: _journalNewSessionPending,
    dockEnabled: els.journalTextInput.disabled === false,
    inactiveNote: els.journalInputDock.classes["inactive-session"] === true,
  }));
})();
"""

    assert _run(tmp_path, probe) == {
        "afterNewContext": {"pending": True, "selected": None},
        "selected": "NEW",
        "active": "NEW",
        "pending": False,
        "dockEnabled": True,
        "inactiveNote": False,
    }


def test_the_first_proxy_request_after_new_context_selects_its_session_voice_or_typed(
    tmp_path,
):
    probe = r"""
_journalNewSessionPending = true;
const voice = _shouldSelectJournalInputSession({role: "user", source: "proxy_heard"});
const assistant = _shouldSelectJournalInputSession({role: "assistant", source: "proxy_answer"});
const sent = _shouldSelectJournalInputSession({role: "system", source: "proxy_sent"});
_journalNewSessionPending = false;
const idle = _shouldSelectJournalInputSession({role: "user", source: "proxy_heard"});
console.log(JSON.stringify({voice, assistant, sent, idle}));
"""

    assert _run(tmp_path, probe) == {
        "voice": True,
        "assistant": False,
        "sent": False,
        "idle": False,
    }


def test_selecting_a_session_ends_the_new_session_state(tmp_path):
    probe = r"""
_journalNewSessionPending = true;
els.journalSessionList = {querySelectorAll: () => ({forEach: () => {}})};
selectJournalSession("older").catch(() => {});
console.log(JSON.stringify({pending: _journalNewSessionPending}));
"""

    assert _run(tmp_path, probe) == {"pending": False}


def test_a_stored_default_system_prompt_is_hidden_from_the_feed_text_but_kept_apart(
    tmp_path,
):
    probe = r"""
const stored = "system: RULES\n\nuser: hi";
const withDefault = {source: "proxy_sent", text: stored,
  proxy_sent: {system_is_default: true, system_text: "RULES", request_text: "user: hi"}};
const changed = {source: "proxy_sent", text: stored, proxy_sent: {system_is_default: false}};
const old = {source: "proxy_sent", text: stored};
console.log(JSON.stringify({
  hidden: _journalSentHidesSystemPrompt(withDefault),
  body: _journalEventBodyText(withDefault),
  changedBody: _journalEventBodyText(changed),
  oldBody: _journalEventBodyText(old),
}));
"""

    result = _run(tmp_path, probe)

    assert result["hidden"] is True
    assert result["body"] == "user: hi"
    assert result["changedBody"] == "system: RULES\n\nuser: hi"
    assert result["oldBody"] == "system: RULES\n\nuser: hi"


def test_the_feed_knows_a_forced_sent_record_by_its_stored_marker_only(tmp_path):
    probe = r"""
const forced = {source: "proxy_sent", metadata: {message_count: 2, forced: true}};
const plain = {source: "proxy_sent", metadata: {message_count: 2}};
const noMetadata = {source: "proxy_sent"};
const falseFlag = {source: "proxy_sent", metadata: {forced: false}};
const wrongSource = {source: "proxy_heard", metadata: {forced: true}};
const stringFlag = {source: "proxy_sent", metadata: {forced: "yes"}};
console.log(JSON.stringify({
  forced: _journalSentIsForced(forced),
  plain: _journalSentIsForced(plain),
  noMetadata: _journalSentIsForced(noMetadata),
  falseFlag: _journalSentIsForced(falseFlag),
  wrongSource: _journalSentIsForced(wrongSource),
  stringFlag: _journalSentIsForced(stringFlag),
}));
"""

    assert _run(tmp_path, probe) == {
        "forced": True,
        "plain": False,
        "noMetadata": False,
        "falseFlag": False,
        "wrongSource": False,
        "stringFlag": False,
    }
