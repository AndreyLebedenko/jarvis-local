// The chat of the personal proxy (--personal-proxy): what was heard, what was
// sent, the answer sentence by sentence, notices, and the dry-run state.
//
// Every block arrives as a transient `proxy_block` state delta. Nothing here
// is kept: no browser storage, no cookie, and the DOM is wiped on Hidden.
// Text is only ever put in with textContent, never as markup.

const PROXY_CHAT_MAX_BLOCKS = 200;

const PROXY_BLOCK_TITLE_KEYS = {
  heard: "proxy_block_heard",
  sent: "proxy_block_sent",
  answer: "proxy_block_answer",
  notice: "proxy_block_notice",
  dry_run: "proxy_block_dry_run",
};

const PROXY_DECISION_KEYS = {
  ask_confirmation: "proxy_decision_ask_confirmation",
  send_without_question: "proxy_decision_send_without_question",
};

function _proxyElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = text;
  return element;
}

function _proxyRow(label, value) {
  const row = _proxyElement("div", "proxy-row");
  row.appendChild(_proxyElement("span", "proxy-row-label", label));
  row.appendChild(_proxyElement("span", "proxy-row-value", value));
  return row;
}

function _proxyMessages(messages) {
  const wrap = _proxyElement("div", "proxy-messages");
  (messages || []).forEach((message) => {
    wrap.appendChild(_proxyRow(message.role, message.content));
  });
  return wrap;
}

// A system prompt equal to the default (decided by the server) is folded to a
// short label; a changed one is shown in full like any other message.
function _proxySentMessages(payload) {
  const messages = payload.messages || [];
  if (payload.system_is_default !== true || messages.length === 0) {
    return _proxyMessages(messages);
  }
  const wrap = _proxyElement("div", "proxy-messages");
  wrap.appendChild(proxyDefaultSystemElement(messages[0].content));
  messages.slice(1).forEach((message) => {
    wrap.appendChild(_proxyRow(message.role, message.content));
  });
  return wrap;
}

function proxyDefaultSystemElement(systemText) {
  const details = _proxyElement("details", "proxy-system-default");
  details.appendChild(_proxyElement(
    "summary", "proxy-system-default-label", uiString("proxy_sent_default_system")));
  details.appendChild(_proxyElement("div", "proxy-text", systemText));
  return details;
}

function proxyForcedMarkerElement() {
  return _proxyElement("div", "proxy-forced-marker", uiString("proxy_forced_marker"));
}

function _proxyDoubtsText(doubts) {
  return (doubts || [])
    .map((doubt) => doubt.fragment || doubt.kind)
    .join(" | ");
}

function _proxyBlockBody(payload) {
  const body = _proxyElement("div", "proxy-block-body");
  if (payload.type === "heard") {
    body.appendChild(_proxyElement("div", "proxy-text", payload.text));
    if ((payload.doubts || []).length > 0) {
      body.appendChild(_proxyRow(uiString("proxy_doubts_label"), _proxyDoubtsText(payload.doubts)));
    }
    body.appendChild(_proxyElement(
      "div", "proxy-note", uiString(PROXY_DECISION_KEYS[payload.decision])));
  } else if (payload.type === "sent") {
    if (payload.forced === true) body.appendChild(proxyForcedMarkerElement());
    body.appendChild(_proxySentMessages(payload));
  } else if (payload.type === "notice") {
    body.appendChild(_proxyElement("div", "proxy-text", payload.text));
  } else if (payload.type === "dry_run") {
    _proxyFillDryRun(body, payload);
  }
  return body;
}

function _proxyFillDryRun(body, payload) {
  if (payload.forced === true) body.appendChild(proxyForcedMarkerElement());
  body.appendChild(_proxyRow(uiString("proxy_dry_whisper"), payload.whisper_text || ""));
  body.appendChild(_proxyRow(uiString("proxy_dry_checked"), payload.checked_text));
  body.appendChild(_proxyRow(uiString("proxy_doubts_label"), _proxyDoubtsText(payload.doubts)));
  body.appendChild(_proxyRow(
    uiString("proxy_dry_would_ask"),
    uiString(payload.would_ask ? "proxy_dry_yes" : "proxy_dry_no")));
  body.appendChild(_proxyRow(uiString("proxy_dry_sanitized"), payload.sanitized_text));
  const mapping = Object.entries(payload.mapping || {})
    .map(([key, value]) => key + " = " + value)
    .join("\n");
  body.appendChild(_proxyRow(uiString("proxy_dry_mapping"), mapping));
  const verdict = payload.reason ? payload.verdict + " - " + payload.reason : payload.verdict;
  body.appendChild(_proxyRow(uiString("proxy_dry_verdict"), verdict));
  const gate = (payload.gate_findings || []).length === 0
    ? uiString("proxy_dry_gate_clear")
    : payload.gate_findings.map((finding) => finding.category).join(", ");
  body.appendChild(_proxyRow(uiString("proxy_dry_gate"), gate));
  body.appendChild(_proxyElement("div", "proxy-note", uiString("proxy_dry_messages")));
  body.appendChild(_proxyMessages(payload.messages));
}

function _proxyAnswerSentence(payload) {
  const rough = payload.method === "substituted" || payload.unresolved === true;
  const sentence = _proxyElement("span", "proxy-sentence", payload.text);
  if (rough) {
    sentence.classList.add("rough");
    sentence.title = uiString(
      payload.unresolved === true ? "proxy_answer_unresolved" : "proxy_answer_rough");
  }
  return sentence;
}

function _proxyAppendAnswer(list, payload) {
  const last = list.lastElementChild;
  if (last && last.dataset.type === "answer") {
    const body = last.querySelector(".proxy-block-body");
    body.appendChild(document.createTextNode(" "));
    body.appendChild(_proxyAnswerSentence(payload));
    return last;
  }
  const block = _proxyElement("div", "proxy-block");
  block.dataset.type = "answer";
  block.appendChild(_proxyElement("div", "proxy-block-title", uiString(PROXY_BLOCK_TITLE_KEYS.answer)));
  const body = _proxyElement("div", "proxy-block-body");
  body.appendChild(_proxyAnswerSentence(payload));
  block.appendChild(body);
  list.appendChild(block);
  return block;
}

function applyProxyBlock(payload) {
  // The transport already drops blocks while Hidden; this is the second guard.
  if (_isHiddenActive()) return;
  const list = document.getElementById("proxyChatList");
  if (!list) return;
  const titleKey = PROXY_BLOCK_TITLE_KEYS[payload.type];
  if (titleKey === undefined) {
    throw new Error("Unknown proxy block type: " + payload.type);
  }
  const empty = document.getElementById("proxyChatEmpty");
  if (empty) empty.hidden = true;
  const pinned = list.scrollHeight - list.scrollTop - list.clientHeight <= 40;
  let block;
  if (payload.type === "answer") {
    block = _proxyAppendAnswer(list, payload);
  } else {
    block = _proxyElement("div", "proxy-block");
    block.dataset.type = payload.type;
    if (payload.kind) block.dataset.kind = payload.kind;
    block.appendChild(_proxyElement("div", "proxy-block-title", uiString(titleKey)));
    block.appendChild(_proxyBlockBody(payload));
    list.appendChild(block);
  }
  while (list.children.length > PROXY_CHAT_MAX_BLOCKS) {
    list.removeChild(list.firstElementChild);
  }
  if (pinned) list.scrollTop = list.scrollHeight;
  return block;
}

// The dry-run indicator and the content-free reason the last request was
// stopped (kind and positions, never a value). Both ride in the snapshot, so a
// reconnecting client sees them; unlike the blocks they hold nothing personal.
let _proxyDryRun = false;

function isProxyDryRun() {
  return _proxyDryRun;
}

function applyProxyStatus(payload) {
  const status = payload || { dry_run: false, last_block: null };
  _proxyDryRun = Boolean(status.dry_run);
  const badge = document.getElementById("proxyDryRun");
  if (badge) badge.hidden = !status.dry_run;
  const reason = document.getElementById("proxyLastBlock");
  if (!reason) return;
  const last = status.last_block;
  reason.hidden = !last;
  reason.textContent = last
    ? uiString("proxy_last_block_label") + " " + proxyNoticeText(last.kind, last.detail)
    : "";
}

function clearProxyChatBlocks() {
  const list = document.getElementById("proxyChatList");
  if (list) list.replaceChildren();
  const empty = document.getElementById("proxyChatEmpty");
  if (empty) empty.hidden = false;
}

function _onProxyVisibilityChanged(mode) {
  if (mode === "hidden") clearProxyChatBlocks();
}
