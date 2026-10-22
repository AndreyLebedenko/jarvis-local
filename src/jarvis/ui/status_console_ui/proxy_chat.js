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
    body.appendChild(_proxyMessages(payload.messages));
  } else if (payload.type === "notice") {
    body.appendChild(_proxyElement("div", "proxy-text", payload.text));
  } else if (payload.type === "dry_run") {
    _proxyFillDryRun(body, payload);
  }
  return body;
}

function _proxyFillDryRun(body, payload) {
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

function clearProxyChat() {
  const list = document.getElementById("proxyChatList");
  if (list) list.replaceChildren();
  const empty = document.getElementById("proxyChatEmpty");
  if (empty) empty.hidden = false;
  const input = document.getElementById("proxyChatText");
  if (input) input.value = "";
  _setProxyChatStatus("");
}

function _setProxyChatStatus(text) {
  const status = document.getElementById("proxyChatStatus");
  if (status) status.textContent = text;
}

let _proxyChatInFlight = false;

function _proxyErrorMessage(payload) {
  if (payload.reason === "busy") return uiString("proxy_chat_busy");
  if (payload.reason === "empty") return uiString("proxy_chat_empty_text");
  if (payload.reason === "unavailable" && payload.detail) return payload.detail;
  if (payload.reason === "over_limit") {
    return uiString("proxy_chat_over_limit").replace("{max}", String(payload.max_chars));
  }
  return uiString("proxy_chat_failed");
}

// Typed text goes to the same route as the Journal dock: the engine sends it
// to the proxy in this run mode, where it is a request like a spoken one.
async function submitProxyText() {
  if (_proxyChatInFlight || _isHiddenActive()) return;
  const input = document.getElementById("proxyChatText");
  const text = input.value;
  if (!text.trim()) {
    _setProxyChatStatus(uiString("proxy_chat_empty_text"));
    return;
  }
  const url = _journalUrl("/api/journal/input");
  if (url === null) {
    _setProxyChatStatus(uiString("transport_no_token"));
    return;
  }
  _proxyChatInFlight = true;
  document.getElementById("proxyChatSend").disabled = true;
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const payload = await response.json();
    if (payload.status === "accepted") {
      if (input.value === text) input.value = "";
      _setProxyChatStatus("");
    } else {
      _setProxyChatStatus(_proxyErrorMessage(payload));
    }
  } catch (error) {
    console.error("Proxy input failed:", error);
    _setProxyChatStatus(uiString("proxy_chat_failed"));
  } finally {
    _proxyChatInFlight = false;
    document.getElementById("proxyChatSend").disabled = false;
  }
}

function onProxyChatKeyDown(event) {
  if (event.key !== "Enter" || event.shiftKey) return;
  event.preventDefault();
  submitProxyText();
}

function _onProxyVisibilityChanged(mode) {
  if (mode === "hidden") clearProxyChat();
}
