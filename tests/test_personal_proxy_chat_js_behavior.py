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
for (const id of ["proxyChatList", "proxyChatEmpty", "proxyChatText", "proxyChatStatus"]) {
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
ids.proxyChatText.value = "typed";
_onProxyVisibilityChanged("hidden");
const after = ids.proxyChatList.children.length;
state.hidden = true;
applyProxyBlock({type: "notice", kind: "x", text: "late"});
console.log(JSON.stringify({
  before, after,
  late: ids.proxyChatList.children.length,
  input: ids.proxyChatText.value,
  emptyShown: ids.proxyChatEmpty.hidden === false,
}));
"""

    result = _run(tmp_path, probe)

    assert result == {
        "before": 1,
        "after": 0,
        "late": 0,
        "input": "",
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


def test_an_unavailable_submission_shows_its_own_reason_not_the_queue_message(
    tmp_path,
):
    probe = r"""
console.log(JSON.stringify({
  withDetail: _proxyErrorMessage({reason: "unavailable", detail: "Ollama is not running."}),
  withoutDetail: _proxyErrorMessage({reason: "unavailable"}),
  busy: _proxyErrorMessage({reason: "busy"}),
}));
"""

    result = _run(tmp_path, probe)

    assert result == {
        "withDetail": "Ollama is not running.",
        "withoutDetail": "proxy_chat_failed",
        "busy": "proxy_chat_busy",
    }


def test_clearing_the_blocks_keeps_the_typed_text_and_the_status_line(tmp_path):
    probe = r"""
applyProxyBlock({type: "notice", kind: "x", text: "personal"});
ids.proxyChatText.value = "typed";
ids.proxyChatStatus.textContent = "status";
clearProxyChatBlocks();
console.log(JSON.stringify({
  blocks: ids.proxyChatList.children.length,
  emptyShown: ids.proxyChatEmpty.hidden === false,
  input: ids.proxyChatText.value,
  status: ids.proxyChatStatus.textContent,
}));
"""

    assert _run(tmp_path, probe) == {
        "blocks": 0,
        "emptyShown": True,
        "input": "typed",
        "status": "status",
    }
