# ruff: noqa: E501
"""Runs proxy_chat.js against a minimal DOM stub in Node, when Node exists.

A real browser is the human handoff; this proves two safety properties by
running the code: text is only ever set as text, and Hidden wipes the chat."""

import json
import shutil
import subprocess

import pytest

from jarvis.ui.status_console import UI_DIR

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")

HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
class El {
  constructor(tag) {
    this.tag = tag; this.className = ""; this.dataset = {}; this.children = [];
    this._text = ""; this.title = ""; this.hidden = false; this.value = "";
    this.scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 0;
    this.classList = { add: (c) => { this.className += " " + c; } };
  }
  set innerHTML(v) { throw new Error("innerHTML was used"); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children.splice(this.children.indexOf(c), 1); }
  replaceChildren() { this.children = []; }
  get firstElementChild() { return this.children.find((c) => c instanceof El) || null; }
  get lastElementChild() {
    const els = this.children.filter((c) => c instanceof El);
    return els.length ? els[els.length - 1] : null;
  }
  querySelector(sel) {
    const cls = sel.slice(1);
    for (const c of this.children) {
      if (!(c instanceof El)) continue;
      if (c.className.split(" ").includes(cls)) return c;
      const inner = c.querySelector(sel);
      if (inner) return inner;
    }
    return null;
  }
}
const ids = {};
for (const id of ["proxyChatList", "proxyChatEmpty"]) {
  ids[id] = new El("div");
}
const state = { hidden: false };
const context = {
  document: {
    createElement: (t) => new El(t),
    createTextNode: (t) => { const e = new El("#text"); e._text = t; return e; },
    getElementById: (id) => ids[id] || null,
  },
  uiString: (key) => key,
  _isHiddenActive: () => state.hidden,
  _journalUrl: () => null,
  console,
  state, ids,
};
vm.createContext(context);
const source = fs.readFileSync(process.argv[2], "utf8");
const probe = fs.readFileSync(process.argv[3], "utf8");
vm.runInContext(source + "\n;" + probe, context);
"""


def _run(tmp_path, probe: str) -> dict:
    harness = tmp_path / "harness.js"
    probe_file = tmp_path / "probe.js"
    harness.write_text(HARNESS, encoding="utf-8")
    probe_file.write_text(probe, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), str(UI_DIR / "proxy_chat.js"), str(probe_file)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_hostile_text_is_set_as_text_never_as_markup(tmp_path):
    probe = r"""
const hostile = '<img src=x onerror="alert(1)"><script>boom()</script>';
applyProxyBlock({type: "heard", text: hostile, doubts: [{kind: "fragment", fragment: hostile}], decision: "ask_confirmation"});
applyProxyBlock({type: "answer", text: hostile, method: "passthrough", unresolved: false});
applyProxyBlock({type: "notice", kind: "x", text: hostile});
applyProxyBlock({type: "sent", messages: [{role: hostile, content: hostile}]});
console.log(JSON.stringify({
  blocks: ids.proxyChatList.children.length,
  hasHostile: ids.proxyChatList.textContent.includes(hostile),
}));
"""

    result = _run(tmp_path, probe)

    assert result == {"blocks": 4, "hasHostile": True}


def test_consecutive_answer_sentences_join_one_block_and_rough_ones_are_marked(
    tmp_path,
):
    probe = r"""
applyProxyBlock({type: "answer", text: "One.", method: "passthrough", unresolved: false});
applyProxyBlock({type: "answer", text: "Two.", method: "substituted", unresolved: false});
console.log(JSON.stringify({
  blocks: ids.proxyChatList.children.length,
  rough: ids.proxyChatList.textContent.includes("Two."),
}));
"""

    assert _run(tmp_path, probe) == {"blocks": 1, "rough": True}


def test_hidden_clears_the_chat_and_a_block_while_hidden_is_dropped(tmp_path):
    probe = r"""
applyProxyBlock({type: "notice", kind: "x", text: "personal"});
const before = ids.proxyChatList.children.length;
_onProxyVisibilityChanged("hidden");
const after = ids.proxyChatList.children.length;
state.hidden = true;
applyProxyBlock({type: "notice", kind: "x", text: "late"});
console.log(JSON.stringify({
  before, after,
  late: ids.proxyChatList.children.length,
  emptyShown: ids.proxyChatEmpty.hidden === false,
}));
"""

    result = _run(tmp_path, probe)

    assert result == {
        "before": 1,
        "after": 0,
        "late": 0,
        "emptyShown": True,
    }


def test_the_chat_is_capped_so_old_personal_text_does_not_pile_up(tmp_path):
    probe = r"""
for (let i = 0; i < PROXY_CHAT_MAX_BLOCKS + 25; i++) {
  applyProxyBlock({type: "notice", kind: "x", text: "n" + i});
}
console.log(JSON.stringify({blocks: ids.proxyChatList.children.length}));
"""

    assert _run(tmp_path, probe) == {"blocks": 200}


SENT_PROBE_HELPERS = r"""
function find(el, predicate, found = []) {
  if (predicate(el)) found.push(el);
  el.children.forEach((child) => child.children && find(child, predicate, found));
  return found;
}
function textWithout(el, tag) {
  if (el.tag === tag) return "";
  return el._text + el.children.map((child) => textWithout(child, tag)).join("");
}
const block = ids.proxyChatList.lastElementChild;
const folded = find(block, (el) => el.tag === "details");
"""


def test_a_default_system_prompt_is_folded_into_a_labelled_expandable_element(
    tmp_path,
):
    probe = (
        r"""
applyProxyBlock({type: "sent", system_is_default: true, messages: [
  {role: "system", content: "STANDARD RULES"}, {role: "user", content: "Hello <PERSON_1>"}]});
"""
        + SENT_PROBE_HELPERS
        + r"""
console.log(JSON.stringify({
  folded: folded.length,
  label: folded[0].children[0].textContent,
  insideText: folded[0].textContent,
  visibleOutside: textWithout(block, "details"),
}));
"""
    )

    result = _run(tmp_path, probe)

    assert result["folded"] == 1
    assert result["label"] == "proxy_sent_default_system"
    assert "STANDARD RULES" in result["insideText"]
    assert "Hello <PERSON_1>" in result["visibleOutside"]
    assert "STANDARD RULES" not in result["visibleOutside"]


def test_a_changed_system_prompt_is_shown_in_full_without_folding(tmp_path):
    probe = (
        r"""
applyProxyBlock({type: "sent", system_is_default: false, messages: [
  {role: "system", content: "CHANGED RULES"}, {role: "user", content: "Hello"}]});
"""
        + SENT_PROBE_HELPERS
        + r"""
console.log(JSON.stringify({folded: folded.length, text: block.textContent}));
"""
    )

    result = _run(tmp_path, probe)

    assert result["folded"] == 0
    assert "CHANGED RULES" in result["text"]
    assert "Hello" in result["text"]


def test_a_sent_block_without_the_default_flag_is_shown_in_full(tmp_path):
    probe = (
        r"""
applyProxyBlock({type: "sent", messages: [{role: "system", content: "RULES"}]});
"""
        + SENT_PROBE_HELPERS
        + r"""
console.log(JSON.stringify({folded: folded.length, text: block.textContent}));
"""
    )

    result = _run(tmp_path, probe)

    assert result["folded"] == 0
    assert "RULES" in result["text"]


def test_the_default_prompt_is_set_as_text_never_as_markup_when_expanded(tmp_path):
    probe = (
        r"""
const hostile = '<img src=x onerror="alert(1)">';
applyProxyBlock({type: "sent", system_is_default: true, messages: [
  {role: "system", content: hostile}, {role: "user", content: "x"}]});
"""
        + SENT_PROBE_HELPERS
        + r"""
console.log(JSON.stringify({hostile: folded[0].textContent.includes(hostile)}));
"""
    )

    assert _run(tmp_path, probe) == {"hostile": True}


def test_a_forced_sent_block_shows_the_forced_marker_before_the_messages(tmp_path):
    probe = r"""
applyProxyBlock({type: "sent", system_is_default: false, forced: true, messages: [
  {role: "system", content: "RULES"}, {role: "user", content: "Hello Marina"}]});
const block = ids.proxyChatList.lastElementChild;
const body = block.querySelector(".proxy-block-body");
const marker = block.querySelector(".proxy-forced-marker");
console.log(JSON.stringify({
  markerText: marker ? marker.textContent : null,
  markerFirst: body.children[0] === marker,
  text: block.textContent,
}));
"""

    result = _run(tmp_path, probe)

    assert result["markerText"] == "proxy_forced_marker"
    assert result["markerFirst"] is True
    assert "Hello Marina" in result["text"]


def test_a_sent_block_that_is_not_forced_has_no_marker(tmp_path):
    probe = r"""
applyProxyBlock({type: "sent", system_is_default: false, forced: false, messages: [
  {role: "user", content: "Hello"}]});
applyProxyBlock({type: "sent", system_is_default: false, messages: [
  {role: "user", content: "Older payload without the field"}]});
const found = ids.proxyChatList.children.map(
  (block) => block.querySelector(".proxy-forced-marker") !== null);
console.log(JSON.stringify({found}));
"""

    assert _run(tmp_path, probe) == {"found": [False, False]}


def test_a_forced_dry_run_block_shows_the_forced_marker_and_a_plain_one_does_not(
    tmp_path,
):
    probe = r"""
const base = {type: "dry_run", whisper_text: null, checked_text: "t", doubts: [],
  would_ask: false, sanitized_text: "t", mapping: {}, verdict: "send", reason: "",
  gate_findings: [], messages: [{role: "user", content: "t"}]};
applyProxyBlock({...base, forced: true});
applyProxyBlock({...base, forced: false});
const found = ids.proxyChatList.children.map(
  (block) => block.querySelector(".proxy-forced-marker") !== null);
console.log(JSON.stringify({found}));
"""

    assert _run(tmp_path, probe) == {"found": [True, False]}


def test_the_forced_marker_is_plain_text_never_markup(tmp_path):
    probe = r"""
const marker = proxyForcedMarkerElement();
console.log(JSON.stringify({text: marker.textContent, tag: marker.tag}));
"""

    assert _run(tmp_path, probe) == {"text": "proxy_forced_marker", "tag": "div"}
