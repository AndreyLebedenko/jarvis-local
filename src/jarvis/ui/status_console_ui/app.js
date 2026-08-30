// Status Console shell rendering and UI transport client.
//
// Every apply*/appendSystemEvent function takes a plain JSON object shaped
// like ui_contract.py's dataclasses (converted to snake_case dicts by
// status_console.py's *_payload() helpers) and updates the DOM. Engine state
// arrives through the local protocol-v1 WebSocket snapshot/delta stream.
//
// setReasoningLevel()/requestModuleReset()/requestContextReset()/
// setVisibilityMode()/setResponseMode() send protocol-v1 control messages.
// They deliberately do not optimistically update the DOM themselves: the
// reasoning-level toggle/chips/visibility toggle/response-mode button group
// only ever change via applyThinkingMode()/appendSystemEvent()/
// applyVisibilityMode()/applyResponseMode(), driven by the real engine event
// coming back through the WebSocket (story-v1.3.1: a ReasoningLevelChanged
// projection; story-v1.9.0: a ResponseModeChanged projection), so the UI can
// never show a state the engine has not actually confirmed.
//
// RUNTIME_STATES/MODULE_IDS/HEALTH_STATUSES/EVENT_LEVELS/VISIBILITY_MODES/
// REASONING_LEVELS/RESPONSE_MODES live in contract.js (loaded before this
// file) - shared with touchstrip.js, see that file's header comment
// (task-ui-06).

// task-ui-05 (human decision): Hidden only changes what this UI shows - it
// never touches audio_in.py/tts.py/Orchestrator. The one concrete UI-level
// behavior it drives here: the vision/screen chip's detail text (which
// could carry a captured region size/timestamp once a real capture-health
// signal exists) is replaced with a generic placeholder while Hidden is
// active, regardless of what was last pushed - "screen previews hidden by
// default, sensitive snippets not shown" from tasks/task-ui-privacy-and-
// touchstrip-requirements.md. The real detail is remembered so switching
// back to Open restores it without needing another push from Python.
const _moduleHealth = new Map();
let _modelLabel = "";
let _mcpEnabled = false;
let _ttsEnabled = true;

// Caps DOM growth for a long-running process feeding a live-appending log
// (task-ui-03's Scope: "recent events", not an unbounded transcript).
const MAX_LOG_ENTRIES = 200;

const _showTransportStatus = typeof createTransportStatusHandler === "function"
  ? createTransportStatusHandler()
  : () => {};

function _sendControl(command, argumentsObject = {}) {
  if (typeof sendUiControl !== "function" || !sendUiControl(command, argumentsObject)) {
    _showTransportStatus(false, uiString("transport_no_connection"));
  }
}

function _clearSystemEvents() {
  const list = document.getElementById("logList");
  list.replaceChildren();
}

function _applyStateSnapshot(state) {
  applyUiLanguage(state.ui_language || {});
  applyRuntimeState(state.runtime);
  _moduleHealth.clear();
  Object.values(state.modules || {}).forEach(applyModuleHealth);
  renderModules();
  applyLastModelRequest(state.last_model_request || { timestamp: null, items: [] });
  applyDataLocality(state.data_locality);
  applyDataSource(state.data_source || { source: "local_only" });
  applyDebugMode(state.debug || { enabled: false });
  applyMcpState(state.mcp || { status: "off", enabled: false, tools: [] });
  applyTtsState(state.tts || { enabled: true });
  applySoloSessionState(state.solo_session || { enabled: false });
  applyModelLabel(state.model);
  _clearSystemEvents();
  (state.system_events || []).forEach(appendSystemEvent);
  applyThinkingMode(state.thinking);
  applyResponseMode(state.response_mode);
  applyVisibilityMode(state.visibility);
  applyModelOptions(state.model_options, false);
  applyMicrophoneOptions(state.microphone_options, false);
  applyPendingRestart(state.pending_restart);
  if (state.config_values) applyConfigValues(state.config_values);
}

function _applyStateDelta(payload) {
  dispatchStateDelta(payload, {
    runtime: applyRuntimeState,
    modules: (value) => Object.values(value).forEach(applyModuleHealth),
    last_model_request: applyLastModelRequest,
    data_locality: applyDataLocality,
    data_source: applyDataSource,
    debug: applyDebugMode,
    mcp: applyMcpState,
    tts: applyTtsState,
    solo_session: applySoloSessionState,
    model: applyModelLabel,
    system_event: appendSystemEvent,
    thinking: applyThinkingMode,
    response_mode: applyResponseMode,
    visibility: applyVisibilityMode,
    model_options: applyModelOptions,
    microphone_options: applyMicrophoneOptions,
    pending_restart: applyPendingRestart,
    ui_language: applyUiLanguage,
    config_values: applyConfigValues,
    journal_event: applyJournalEvent,
    replay_progress: applyReplayProgress,
  });
}

function applyRuntimeState(payload) {
  if (!RUNTIME_STATES.includes(payload.state)) {
    throw new Error("Unknown runtime state: " + payload.state);
  }
  document.documentElement.setAttribute("data-state", payload.state);
  document.getElementById("orbState").textContent = payload.label;
  document.getElementById("orbSub").textContent = payload.substatus || "";
  document
    .getElementById("ring")
    .setAttribute("data-anim", payload.state === "warming" ? "warm" : "normal");
}

function applyModuleHealth(payload) {
  if (!MODULE_IDS.includes(payload.module)) {
    throw new Error("Unknown module id: " + payload.module);
  }
  if (!HEALTH_STATUSES.includes(payload.status)) {
    throw new Error("Unknown health status: " + payload.status);
  }
  _moduleHealth.set(payload.module, payload);
  renderModules();
}

function _moduleDetail(module, detail) {
  if (module !== "vision") return detail || "";
  const isHidden = document.documentElement.getAttribute("data-visibility") === "hidden";
  return isHidden ? uiString("vision_preview_hidden") : detail || "";
}

function renderModules() {
  const panel = document.getElementById("modulesPanel");
  if (!panel) return;
  panel.replaceChildren();
  for (const module of MODULE_IDS) {
    const payload = _moduleHealth.get(module) || {
      module,
      status: "unavailable",
      detail: "",
    };
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.id = "chip-" + module;
    chip.setAttribute("data-status", payload.status);

    const dot = document.createElement("span");
    dot.className = "chip-dot";
    dot.setAttribute("data-status", payload.status);

    const body = document.createElement("div");
    body.className = "chip-body";
    const label = document.createElement("div");
    label.className = "chip-label";
    label.textContent = uiString(module === "backend" ? "chip_model" : "chip_" + module);
    const meta = document.createElement("div");
    meta.className = "chip-meta";
    const detail = module === "backend" && _modelLabel ? _modelLabel : payload.detail;
    meta.textContent = _moduleDetail(module, detail);
    body.append(label, meta);

    chip.append(dot, body);
    if (module === "tts") {
      const toggle = document.createElement("button");
      toggle.className = "chip-toggle";
      toggle.id = "btnTtsToggle";
      toggle.textContent = uiString(_ttsEnabled ? "tts_mute" : "tts_unmute");
      toggle.title = uiString(_ttsEnabled ? "tts_mute" : "tts_unmute");
      toggle.addEventListener("click", setTtsEnabled);
      chip.append(toggle);
    }

    const reset = document.createElement("button");
    reset.className = "chip-reset";
    reset.title = uiString("chip_reset_" + module);
    reset.textContent = "↻";
    reset.addEventListener("click", () => requestModuleReset(module));
    chip.append(reset);
    panel.appendChild(chip);
  }
}

// Both the microphone path (audio) and the upload path (attachment_audio)
// carry the same single-per-turn ModelRequestStarted.audio_duration_seconds
// value (see transport.py's _AUDIO_DURATION_INPUTS) - either kind renders it.
const _AUDIO_DURATION_KINDS = new Set(["audio", "attachment_audio"]);

// story-v1.6.4-task-2: one renderer for a modality, shared by the chip
// strip under the orb and the events panel's request entry. They describe
// the same fact and must never drift into two wordings.
function _requestItemText(item) {
  const detail = _AUDIO_DURATION_KINDS.has(item.kind) && item.duration_seconds !== undefined
    ? ": " + item.duration_seconds.toFixed(1) + " " + uiString("unit_seconds")
    : "";
  return uiString("last_request_" + item.kind) + detail;
}

// story-v1.9.0 task 3: mode 3's derivative sub-pass publishes its own
// ModelRequestStarted (reasoning off, over the shown text) so it is
// honestly logged as a real inference call - this tag is what keeps it
// from reading as a second turn in the chip strip / events panel.
function _passKindSuffix(payload) {
  return payload.pass_kind === "derivative"
    ? " (" + uiString("model_request_pass_derivative") + ")"
    : "";
}

function applyLastModelRequest(payload) {
  const list = document.getElementById("lastRequestList");
  list.replaceChildren();
  const suffix = _passKindSuffix(payload);
  for (const item of payload.items || []) {
    const row = document.createElement("li");
    row.textContent =
      formatLogTime(payload.timestamp) + " - " + _requestItemText(item) + suffix;
    list.appendChild(row);
  }
}

function applyDataLocality(payload) {
  const badge = document.getElementById("localityBadge");
  badge.setAttribute("data-locality", payload.locality);
  badge.querySelector(".locality-label").textContent =
    uiString(payload.locality === "local" ? "locality_local" : "locality_external");
}

// Fixed for the whole process run - set once from state.debug at connect
// time, never pushed as a delta in practice - but still routed through the
// same snapshot/delta path as every other header indicator, so a
// reconnecting client (or a second one) sees it without depending on
// having been present for the original announcement.
function applyDebugMode(payload) {
  const banner = document.getElementById("debugBanner");
  if (!banner) return;
  banner.classList.toggle("show", Boolean(payload && payload.enabled));
}

function applyDataSource(payload) {
  if (!DATA_SOURCES.includes(payload.source)) {
    throw new Error("Unknown data source: " + payload.source);
  }
  const badge = document.getElementById("dataSourceBadge");
  if (!badge) return;
  badge.setAttribute("data-source", payload.source);
  badge.querySelector(".data-source-label").textContent =
    uiString("data_source_" + payload.source);
}

function applyMcpState(payload) {
  if (!MCP_STATUSES.includes(payload.status)) {
    throw new Error("Unknown MCP status: " + payload.status);
  }
  _mcpEnabled = payload.enabled === true;
  const card = document.getElementById("mcpCard");
  if (!card) return;
  card.setAttribute("data-status", payload.status);
  document.getElementById("mcpStatus").textContent = uiString("mcp_" + payload.status);
  const button = document.getElementById("btnMcpToggle");
  button.textContent = uiString(_mcpEnabled ? "mcp_disable" : "mcp_enable");
  button.disabled = payload.status === "connecting" || payload.status === "disconnecting";

  renderToolList("mcpTools", "mcpToolsEmpty", payload.tools || []);
  renderToolList("localTools", "localToolsEmpty", payload.local_tools || []);
}

// task-ui-ux-5: the approved icon set (outline style, 24px viewBox,
// currentColor - see .icon in style.css). One source of truth here rather
// than duplicating path data into index.html/demo.html; static buttons
// that need one (New context, the Memory/Annotations/Consolidation
// toolbar) get it attached once at load by _attachStaticIcons() below.
const ICON_PATHS = {
  new: '<path d="M12 5v14M5 12h14"/>',
  continue: '<path d="M6 4v7a4 4 0 0 0 4 4h8"/><path d="M14 11l4 4-4 4"/>',
  delete: '<path d="M5 7h14"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>' +
    '<path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/><path d="M10 11v6M14 11v6"/>',
  memory: '<path d="M6 4h11a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/>' +
    '<path d="M8 8h2M11 8h6M11 12h6M11 16h4"/>',
  annotations: '<path d="M12 3h6a1 1 0 0 1 1 1v6l-9 9-7-7 9-9z"/>' +
    '<circle cx="16" cy="8" r="1.3" fill="currentColor" stroke="none"/>',
  consolidation: '<path d="M12 4l8 4-8 4-8-4 8-4z"/><path d="M4 12l8 4 8-4"/><path d="M4 16l8 4 8-4"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="1.5"/><path d="M5 15V6a1 1 0 0 1 1-1h9"/>',
  play: '<path d="M8 5v14l11-7z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
  pause:
    '<rect x="7" y="5" width="3.5" height="14" rx="1"/>' +
    '<rect x="13.5" y="5" width="3.5" height="14" rx="1"/>',
};

// aria-hidden because every call site pairs the icon with a text label or
// sets its own aria-label on the button - the icon carries no meaning a
// screen reader user would otherwise miss (test_the_tool_row_tooltip_
// never_becomes_the_accessible_name's rule extends to icons the same way
// it already applies to the tooltip: decoration is not the accessible
// name).
function _icon(name) {
  // A throwaway HTML wrapper, not createElementNS: the HTML parser enters
  // SVG insertion mode on its own the moment it sees an <svg> start tag
  // (same rule that lets `<svg>...</svg>` sit directly in index.html), so
  // the returned node is a real, correctly-namespaced SVG element without
  // this file ever writing out the XML namespace URI - which is also
  // exactly what tripped the "no network-loaded assets" check style.css
  // hit under task-ui-ux-4 (see that file's select rule): the URI string
  // is never fetched, but the literal text alone is enough to match.
  const wrapper = document.createElement("span");
  wrapper.innerHTML = `<svg viewBox="0 0 24 24" class="icon" aria-hidden="true">${ICON_PATHS[name]}</svg>`;
  return wrapper.firstElementChild;
}

// Static markup (index.html) ships icon-less on purpose, so ICON_PATHS
// above stays the only place an icon's shape is written down. Runs on
// every surface that loads app.js; demo.html has no Journal markup, so
// its lookups simply miss and skip, same pattern as the radio-group init
// below.
function _attachStaticIcons() {
  for (const [id, icon] of [
    ["journalNewContextButton", "new"],
    ["journalMemoryToggle", "memory"],
    ["journalAnnotationToggle", "annotations"],
    ["journalConsolidationToggle", "consolidation"],
  ]) {
    const button = document.getElementById(id);
    if (button) button.prepend(_icon(icon));
  }
}

// The visible label names a capability, because this list is a list of
// permissions - a user hunting for the camera switch should not have to
// read snake_case. Only tools we ship get a curated label: inventing a
// friendly name for a third-party MCP tool that reaches the network
// would be worse than showing an ugly true one, so those keep their real
// name. A missing label falls back to that name, never to a guess.
function toolLabel(tool) {
  return optionalUiString("tool_label_" + tool.name) || tool.name;
}

// A row says only what the checkbox cannot. On/off is the checkbox's own
// job, so naming it in text was both duplication and the original defect:
// an available tool the user had switched off got labelled with the same
// word as a dead provider. Only unavailability is written out now, since
// nothing else on the row explains why the box refuses to move.
function renderToolList(listId, emptyId, tools) {
  const list = document.getElementById(listId);
  if (!list) return;
  list.replaceChildren();
  for (const tool of tools) {
    const row = document.createElement("li");
    row.tabIndex = -1; // roving tabindex, set by initRovingList() below
    row.setAttribute("data-available", String(tool.available));
    row.setAttribute("data-provider-kind", tool.provider_kind || "mcp");
    const name = toolLabel(tool);
    // Mouse-only by construction: the native title attribute needs no
    // tooltip component. The description stays out of aria-label, or a
    // screen reader would read a whole model instruction aloud.
    row.title = tool.description
      ? `${tool.name}\n${tool.description}`
      : tool.name;
    row.dataset.toolName = tool.name;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = tool.enabled === true;
    checkbox.disabled = tool.available !== true;
    checkbox.setAttribute("aria-label", `${name} (${tool.name})`);
    checkbox.addEventListener("change", () => {
      _sendControl("set_tool_enabled", { name: tool.name, enabled: checkbox.checked });
    });
    // task-ui-ux-4 fix 3: one consistent rule across every row - the human
    // label leads, the identifier trails as a secondary/dimmed suffix. Only
    // shown when it differs from the label, so an unlabelled third-party
    // MCP tool (name falls back to tool.name itself) does not repeat its
    // own name next to itself.
    const label = document.createElement("span");
    label.className = "tool-row-label";
    const primary = document.createElement("span");
    primary.className = "tool-row-name";
    primary.textContent = name;
    label.appendChild(primary);
    if (name !== tool.name) {
      const identifier = document.createElement("span");
      identifier.className = "tool-row-id";
      identifier.textContent = tool.name;
      label.appendChild(identifier);
    }
    const metaParts = [];
    // The provider names which server answers; for a builtin tool the
    // card heading already said "local", so repeating it is noise.
    if (tool.provider_kind !== "builtin") {
      metaParts.push(tool.provider);
    }
    if (tool.available !== true) {
      metaParts.push(uiString("mcp_tool_unavailable"));
    }
    if (metaParts.length) {
      const meta = document.createElement("span");
      meta.className = "tool-row-meta";
      meta.textContent = metaParts.join(" - ");
      label.appendChild(meta);
    }
    const menuButton = document.createElement("button");
    menuButton.type = "button";
    menuButton.className = "context-menu-button";
    menuButton.textContent = "...";
    menuButton.title = uiString("context_menu_open");
    menuButton.setAttribute("aria-label", uiString("context_menu_open"));
    menuButton.addEventListener("click", (event) => {
      event.stopPropagation();
      openItemContextMenu(row, menuButton, _toolRowMenuEntries);
    });
    row.append(checkbox, label, menuButton);
    list.appendChild(row);
  }
  document.getElementById(emptyId).hidden = list.children.length !== 0;
  // Arrow-key roving across rows; Space/Enter on the row itself (not the
  // checkbox, which already handles its own Space natively) toggles it.
  initRovingList(list, "li", {
    onToggle: _toggleToolRowCheckbox,
    onActivate: _toggleToolRowCheckbox,
    getLabel: (row) => row.querySelector("span")?.textContent || "",
  });
  initContextMenuTrigger(list, "li", _toolRowMenuEntries);
}

function _toggleToolRowCheckbox(row) {
  const checkbox = row.querySelector('input[type="checkbox"]');
  if (!checkbox || checkbox.disabled) return;
  checkbox.checked = !checkbox.checked;
  checkbox.dispatchEvent(new Event("change", { bubbles: true }));
}

// Enable/Disable reuses set_tool_enabled (via the row's own checkbox, so
// its change listener is the only place that ever sends the command);
// Copy name is a local clipboard action, like Journal's copy actions -
// neither is a new engine capability, only a new way to reach one that
// already exists.
function _toolRowMenuEntries(row) {
  const checkbox = row.querySelector('input[type="checkbox"]');
  const label = row.querySelector("span");
  if (!checkbox) return [];
  return [
    !checkbox.disabled && {
      label: uiString(checkbox.checked ? "mcp_disable" : "mcp_enable"),
      run: () => _toggleToolRowCheckbox(row),
    },
    {
      label: uiString("tool_row_copy_name"),
      icon: _icon("copy"),
      run: () => _copyToClipboardWithLabelFlash(row.dataset.toolName, label),
    },
  ];
}

function setMcpEnabled() {
  _sendControl("set_mcp_enabled", { enabled: !_mcpEnabled });
}

// Deliberately does not optimistically flip _ttsEnabled/re-render itself -
// same rule as every other control here (see this file's header comment):
// the toggle button only ever changes via applyTtsState(), driven by the
// real TtsSpeechEnabledChanged projection coming back through the socket.
function applyTtsState(payload) {
  _ttsEnabled = payload.enabled === true;
  renderModules();
}

function setTtsEnabled() {
  _sendControl("set_tts_enabled", { enabled: !_ttsEnabled });
}

// Same non-optimistic rule as applyTtsState() above: the checkbox only
// ever moves via the real solo_session state delta coming back, never on
// the click itself.
let _soloSessionEnabled = false;

function applySoloSessionState(payload) {
  _soloSessionEnabled = payload.enabled === true;
  const checkbox = document.getElementById("journalSoloToggle");
  if (checkbox) checkbox.checked = _soloSessionEnabled;
}

function setSoloSessionEnabled() {
  const checkbox = document.getElementById("journalSoloToggle");
  const requested = checkbox ? checkbox.checked : !_soloSessionEnabled;
  // Revert the native checkbox state immediately - it only actually
  // moves once applySoloSessionState() is driven by the real delta.
  if (checkbox) checkbox.checked = _soloSessionEnabled;
  _sendControl("set_solo_session_enabled", { enabled: requested });
}

function applyModelLabel(payload) {
  _modelLabel = payload.label;
  renderModules();
}

function formatLogTime(timestampSeconds) {
  const date = new Date(timestampSeconds * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

// story-v1.6.4-task-2: the panel carries two kinds of entry. A plain
// system event prints payload.message, a free-form English string the
// engine composed. A model-request entry arrives typed instead, because
// pre-rendering it engine-side would either lose the translation or force
// the engine to know the interface language - so it is localized here,
// from the same last_request_* keys the chip strip under the orb uses.
function appendSystemEvent(payload) {
  if (!EVENT_LEVELS.includes(payload.level)) {
    throw new Error("Unknown event level: " + payload.level);
  }
  if (payload.entry === "model_request") {
    _appendModelRequestEntry(payload);
    return;
  }
  _appendLogRow(payload, payload.source, payload.message);
}

function _appendModelRequestEntry(payload) {
  // The derivative sub-pass (story-v1.9.0 task 3) carries no modality
  // items of its own - it is a form transform over already-shown text,
  // not a new user input - so its row falls back to the pass tag alone
  // rather than rendering blank.
  const itemsText = (payload.items || []).map(_requestItemText).join(", ");
  const text = itemsText
    ? itemsText + _passKindSuffix(payload)
    : uiString("model_request_pass_derivative");
  _appendLogRow(payload, uiString("log_source_model_request"), text, "model_request");
}

function _appendLogRow(payload, sourceText, messageText, entryKind) {
  const list = document.getElementById("logList");
  const empty = document.getElementById("logEmpty");
  if (empty) empty.remove();

  const row = document.createElement("div");
  row.className = "log-entry";
  row.dataset.level = payload.level;
  if (entryKind) row.dataset.entry = entryKind;

  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = formatLogTime(payload.timestamp);

  const src = document.createElement("span");
  src.className = "log-src";
  src.textContent = sourceText;

  const msg = document.createElement("span");
  msg.className = "log-msg";
  msg.textContent = messageText;

  row.append(time, src, msg);
  list.prepend(row);

  while (list.children.length > MAX_LOG_ENTRIES) {
    list.removeChild(list.lastChild);
  }
}

function applyThinkingMode(payload) {
  if (!REASONING_LEVELS.includes(payload.level)) {
    throw new Error("Unknown reasoning level: " + payload.level);
  }
  document
    .querySelectorAll("#reasoningLevelToggle button")
    .forEach((button) => button.classList.toggle("sel", button.dataset.level === payload.level));
  syncRadioGroup(document.getElementById("reasoningLevelToggle"));
  document.getElementById("thinkTag").textContent = "level: " + payload.level;
  document.getElementById("thinkStatus").textContent = uiString("think_status_" + payload.level);
}

function setReasoningLevel(levelValue) {
  _sendControl("set_reasoning_level", { level: levelValue });
}

// Task 3b: the live mode toggle is the Status-tab button group, same
// non-optimistic rule as applyThinkingMode(): selection comes only from
// the confirmed ResponseModeChanged projection, never from the click
// itself. The Settings drop-down is a separate restart-to-apply batch
// field - applyResponseMode() must never touch it.

function applyResponseMode(payload) {
  if (!RESPONSE_MODES.includes(payload.mode)) {
    throw new Error("Unknown response mode: " + payload.mode);
  }
  document
    .querySelectorAll("#responseModeToggle button")
    .forEach((button) => button.classList.toggle("sel", button.dataset.mode === payload.mode));
  syncRadioGroup(document.getElementById("responseModeToggle"));
}

function setResponseMode(modeValue) {
  if (!RESPONSE_MODES.includes(modeValue)) {
    throw new Error("Unknown response mode: " + modeValue);
  }
  _sendControl("set_response_mode", { mode: modeValue });
}

function requestModuleReset(moduleId) {
  if (!MODULE_IDS.includes(moduleId)) {
    throw new Error("Unknown module id: " + moduleId);
  }
  _sendControl("reset_module", { module_id: moduleId });
}

// task-ui-ux-1: keyboard shortcuts overlay. Remembers whatever had focus
// before opening and restores it on close. `aria-modal="true"` on its own
// is only a screen-reader hint - it does not stop real Tab from reaching
// background controls - so opening also marks every OTHER direct child of
// <body> `inert`: a real, spec-compliant focus trap (inert elements are
// removed from the focus order and cannot be focused at all, by Tab or by
// script) with no hand-rolled Tab-cycling code. Both the open and close
// paths guard against re-entry, or a second "?" while already open would
// re-capture the Close button itself (now the active element) as the
// return-focus target instead of what was focused before opening.
let _shortcutsOverlayReturnFocus = null;

function _setBackgroundInert(makeInert, exceptElement) {
  for (const child of document.body.children) {
    if (child === exceptElement) continue;
    if (makeInert) child.setAttribute("inert", "");
    else child.removeAttribute("inert");
  }
}

function openShortcutsOverlay() {
  const overlay = document.getElementById("shortcutsOverlay");
  if (!overlay || !overlay.hidden) return;
  _shortcutsOverlayReturnFocus = document.activeElement;
  _setBackgroundInert(true, overlay);
  overlay.hidden = false;
  overlay.querySelector(".shortcuts-head button")?.focus();
}

function closeShortcutsOverlay() {
  const overlay = document.getElementById("shortcutsOverlay");
  if (!overlay || overlay.hidden) return;
  overlay.hidden = true;
  _setBackgroundInert(false, overlay);
  _shortcutsOverlayReturnFocus?.focus?.();
  _shortcutsOverlayReturnFocus = null;
}

// task-ui-ux-6: session "Show info" modal. Same overlay contract as the
// shortcuts overlay above (inert focus trap, focus capture/restore); it only
// displays session metadata the session list already holds, plus the folder
// path the sessions payload now carries. Read-only: no engine call, no state.
let _sessionInfoReturnFocus = null;

function openSessionInfoOverlay(sessionId) {
  const overlay = document.getElementById("sessionInfoOverlay");
  const session = _journalSessions.find((item) => item.id === sessionId);
  if (!overlay || !overlay.hidden || !session) return;
  document.getElementById("sessionInfoName").textContent = session.title;
  document.getElementById("sessionInfoCreated").textContent =
    _formatJournalDate(session.start_timestamp) +
    " " +
    _formatJournalTime(session.start_timestamp);
  document.getElementById("sessionInfoSize").textContent = _formatJournalBytes(
    _journalUsageBySession.get(session.id) || 0);
  document.getElementById("sessionInfoFolder").textContent =
    session.folder_path || "";
  _sessionInfoReturnFocus = document.activeElement;
  _setBackgroundInert(true, overlay);
  overlay.hidden = false;
  overlay.querySelector(".session-info-head button")?.focus();
}

function closeSessionInfoOverlay() {
  const overlay = document.getElementById("sessionInfoOverlay");
  if (!overlay || overlay.hidden) return;
  overlay.hidden = true;
  _setBackgroundInert(false, overlay);
  _sessionInfoReturnFocus?.focus?.();
  _sessionInfoReturnFocus = null;
}

function copySessionInfoFolder() {
  const path = document.getElementById("sessionInfoFolder")?.textContent || "";
  if (path) _copyToClipboardWithJournalStatus(path);
}

// task-ui-ux-1: skip-link target. .main/.journal/.settings are mutually
// exclusive siblings switched by data-view (see setActiveView()), not one
// shared landmark, so the skip link resolves whichever is currently active
// rather than a fixed href.
function skipToContent() {
  const view = document.documentElement.getAttribute("data-view");
  const selector = { status: ".main", journal: ".journal", settings: ".settings" }[view] || ".main";
  document.querySelector(selector)?.focus();
}

// story-v1.2.4-task-1: guarded Shutdown control. show/hide only toggles
// local UI state; only confirmShutdown() calls back into the engine. There
// is no applyShutdown() callback to wait for: once request_shutdown()
// actually tears down the running engine, there is nothing left running to
// push a confirmation back.
function showShutdownConfirm() {
  document.getElementById("shutdownConfirmRow").classList.add("show");
}

function hideShutdownConfirm() {
  document.getElementById("shutdownConfirmRow").classList.remove("show");
}

function confirmShutdown() {
  hideShutdownConfirm();
  // Disabled immediately, not after some confirmation from the engine:
  // there is no "shutdown complete" push to wait for (see the comment
  // above), and the window is known to stay open but inert once teardown
  // finishes (PROJECT.md's Architecture v1.2.4 section) - a confused
  // repeat click while waiting is a real, observed failure mode (verified
  // live, 2026-07-07: a second click after the engine had already shut
  // down crashed pywebview's JS-API dispatch thread before status_
  // console.py's StatusConsoleApi grew a closed-loop guard). Disabling
  // the button is a purely cosmetic extra layer on top of that real fix,
  // not a substitute for it.
  document.getElementById("btnShutdown").disabled = true;
  _sendControl("request_shutdown");
}

function applyVisibilityMode(payload) {
  if (!VISIBILITY_MODES.includes(payload.mode)) {
    throw new Error("Unknown visibility mode: " + payload.mode);
  }
  // Deliberately does not touch #localityBadge/applyDataLocality - data
  // locality and visibility mode are independent axes (task-ui-05 AC:
  // "Hidden does not imply cloud/offline status").
  document.documentElement.setAttribute("data-visibility", payload.mode);
  document
    .querySelectorAll("#visibilityToggle button")
    .forEach((button) => button.classList.toggle("sel", button.dataset.mode === payload.mode));
  syncRadioGroup(document.getElementById("visibilityToggle"));
  renderModules();
  _onJournalVisibilityChanged(payload.mode);
}

function setVisibilityMode(modeValue) {
  _sendControl("set_visibility_mode", { mode: modeValue });
}

// story-v1.2.4-task-3: configuration form (model + microphone,
// restart-to-apply). refreshSettingsOptions() re-fetches both selectors'
// options every time the Settings tab is entered, so returning to Settings
// shows fresh enumeration rather than a stale snapshot from last time. Each
// fetch degrades to just the current configured value on failure
// (status_console.py's request_model_options()/request_microphone_options(),
// never invented or guessed here). Like every other control on this page,
// selecting an option does not apply anything by itself - only
// applyConfigSelection() (the "Apply" button) writes config.ui.toml, and
// even that is restart-to-apply, not live. There is no live confirmation
// event to wait for, since nothing changes in the running process at all
// until the next start; applyPendingRestart() is shown immediately after a
// successful save.
// Regression guard (2026-07-07, real live-session bug): both <select>s
// start empty (no <option>s) until request_model_options()/
// request_microphone_options() resolve - a click on "Apply" before
// then read modelSelect.value as "" and saved an empty model into
// config.ui.toml, breaking the next restart. btnConfigApply now starts
// disabled (see index.html) and only re-enables once both selectors have
// actually received real options at least once since the panel was last
// opened - re-armed to disabled on every open, not just the first,
// since a fast reopen-then-click could otherwise race a fresh refetch
// the same way.
let _modelOptionsLoaded = false;
let _microphoneOptionsLoaded = false;

function _updateApplyButtonEnabled() {
  const inputsValid = _configInputsValid();
  document.getElementById("btnConfigApply").disabled =
    !(_modelOptionsLoaded && _microphoneOptionsLoaded && inputsValid);
}

function refreshSettingsOptions() {
  _modelOptionsLoaded = false;
  _microphoneOptionsLoaded = false;
  _updateApplyButtonEnabled();
  _sendControl("request_model_options");
  _sendControl("request_microphone_options");
}

function _renderOptions(select, options, current) {
  select.innerHTML = "";
  for (const option of options) {
    const el = document.createElement("option");
    el.value = option;
    el.textContent = option === "" ? uiString("default_microphone_option") : option;
    if (option === current) el.selected = true;
    select.appendChild(el);
  }
}

function applyModelOptions(payload, markLoaded = true) {
  _renderOptions(document.getElementById("modelSelect"), payload.options, payload.current);
  if (markLoaded) _modelOptionsLoaded = true;
  _updateApplyButtonEnabled();
}

// A microphone option is a {device, host_api} pair, not a string: one
// physical microphone is listed once per host API under an identical
// name, so the name alone cannot say which copy the user picked (see
// audio/devices.py). The <option> value is the index into this list,
// because neither half is unique on its own and a delimiter joining them
// could occur inside a device name.
let _microphoneOptions = [];

// label is the device name made readable (Windows hands PortAudio a raw
// resource string, newline included, for Bluetooth headsets - see
// audio/devices.py). It is absent from a configured value, which carries
// identity only, so the raw name is the fallback.
function _microphoneOptionLabel(option) {
  if (option.device === "") return uiString("default_microphone_option");
  const name = option.label || option.device;
  if (!option.host_api) return name;
  return `${name} - ${option.host_api}`;
}

function applyMicrophoneOptions(payload, markLoaded = true) {
  const select = document.getElementById("micSelect");
  _microphoneOptions = payload.options;
  select.innerHTML = "";
  payload.options.forEach((option, index) => {
    const el = document.createElement("option");
    el.value = String(index);
    el.textContent = _microphoneOptionLabel(option);
    if (
      option.device === payload.current.device &&
      option.host_api === payload.current.host_api
    ) {
      el.selected = true;
    }
    select.appendChild(el);
  });
  if (markLoaded) _microphoneOptionsLoaded = true;
  _updateApplyButtonEnabled();
}

function _selectedMicrophoneOption() {
  // Falls back to the system default rather than to a guessed device:
  // the Apply button is disabled until options load, and if that guard
  // is ever bypassed, "" is the one value that cannot open the wrong
  // microphone.
  const index = Number.parseInt(document.getElementById("micSelect").value, 10);
  return _microphoneOptions[index] || { device: "", host_api: "" };
}

function applyPendingRestart(payload) {
  document.getElementById("pendingRestart").classList.toggle("show", payload.pending);
}

// story-v1.3.0-task-2: configuration iteration 2. The snapshot's
// config_values section carries current values, option lists, and
// validation ranges - this file renders and range-checks from that data
// instead of hardcoding a second copy of the Python contract
// (config_selection.py stays the authority; the engine re-validates on
// save either way).
let _configValues = null;

function applyConfigValues(payload) {
  _configValues = payload;
  const langSelect = document.getElementById("uiLangSelect");
  langSelect.innerHTML = "";
  for (const lang of payload.ui_language_options) {
    const el = document.createElement("option");
    el.value = lang;
    el.textContent = lang;
    if (lang === payload.ui_language) el.selected = true;
    langSelect.appendChild(el);
  }
  const modeSelect = document.getElementById("responseModeSelect");
  modeSelect.innerHTML = "";
  for (const mode of payload.response_mode_options) {
    const el = document.createElement("option");
    el.value = mode;
    el.textContent = uiString("response_mode_" + mode + "_option");
    if (mode === payload.response_mode) el.selected = true;
    modeSelect.appendChild(el);
  }
  document.getElementById("vadThreshold").value = payload.vad.threshold;
  document.getElementById("vadMaxChunk").value = payload.vad.max_chunk_seconds;
  document.getElementById("vadEndPause").value = payload.vad.request_end_pause_seconds;
  document.getElementById("vadCooldown").value = payload.vad.resume_cooldown_seconds;
  document.getElementById("ttsEnabled").checked = payload.tts.enabled;
  document.getElementById("ttsCustomRoutes").disabled = !payload.tts.enabled;
  const custom = payload.tts.languages.every((lang) => lang in payload.tts.routes);
  document.getElementById("ttsCustomRoutes").checked = custom;
  _renderTtsRouteRows();
  onConfigInputChanged();
}

function onTtsEnabledChanged() {
  // Gates the per-language voice block beneath the master switch (task-
  // ui-ux-3): while off, the block is disabled but its values are kept and
  // still collected/saved - only editing is blocked, not the selection.
  document.getElementById("ttsCustomRoutes").disabled =
    !document.getElementById("ttsEnabled").checked;
  _renderTtsRouteRows();
  onConfigInputChanged();
}

function _renderTtsRouteRows() {
  const container = document.getElementById("ttsRouteRows");
  container.innerHTML = "";
  if (_configValues === null) return;
  const enabled =
    document.getElementById("ttsEnabled").checked &&
    document.getElementById("ttsCustomRoutes").checked;
  for (const lang of _configValues.tts.languages) {
    const route = _configValues.tts.routes[lang] || null;
    const row = document.createElement("div");
    row.className = "config-tts-route";
    const header = document.createElement("div");
    header.className = "config-tts-route-header";
    const label = document.createElement("label");
    label.textContent = uiString("config_tts_route_label").replace("{lang}", lang);
    const engineSelect = document.createElement("select");
    engineSelect.id = "ttsEngine-" + lang;
    engineSelect.disabled = !enabled;
    for (const engine of _configValues.tts.engines) {
      const el = document.createElement("option");
      el.value = engine;
      el.textContent = engine;
      if (route !== null && engine === route.engine) el.selected = true;
      engineSelect.appendChild(el);
    }
    const fieldsContainer = document.createElement("div");
    fieldsContainer.className = "config-tts-fields";
    engineSelect.onchange = () => {
      _renderTtsFields(lang, engineSelect.value, fieldsContainer, null, enabled);
      onConfigInputChanged();
    };
    header.append(label, engineSelect);
    row.append(header, fieldsContainer);
    container.appendChild(row);
    _renderTtsFields(lang, engineSelect.value, fieldsContainer, route, enabled);
  }
}

function _renderTtsFields(lang, engine, container, route, enabled) {
  container.innerHTML = "";
  for (const spec of _configValues.tts.schemas[engine]) {
    const field = document.createElement("div");
    field.className = "config-field config-tts-field";
    const label = document.createElement("label");
    label.htmlFor = `tts-${lang}-${spec.name}`;
    label.textContent = uiString("config_tts_field_" + spec.name);
    const input = _createTtsInput(lang, engine, spec, route);
    input.disabled = !enabled;
    field.append(label, input);
    container.appendChild(field);
  }
}

function _createTtsInput(lang, engine, spec, route) {
  const input = document.createElement(spec.kind === "boolean" ? "select" : "input");
  input.id = `tts-${lang}-${spec.name}`;
  input.dataset.ttsField = spec.name;
  input.dataset.ttsEngine = engine;
  const value = route !== null && route.engine === engine
    ? route[spec.name]
    : spec.default;
  if (spec.kind === "boolean") {
    if (spec.nullable) input.append(new Option(uiString("config_tts_default_value"), ""));
    input.append(new Option(uiString("config_tts_false_value"), "false"));
    input.append(new Option(uiString("config_tts_true_value"), "true"));
    input.value = value === null ? "" : String(value);
    input.onchange = onConfigInputChanged;
    return input;
  }
  input.type = spec.kind === "string" ? "text" : "number";
  if (spec.kind === "integer") input.step = "1";
  if (spec.kind === "number") input.step = "any";
  input.value = value === null ? "" : value;
  input.oninput = onConfigInputChanged;
  return input;
}

function onTtsRoutingModeChanged() {
  _renderTtsRouteRows();
  onConfigInputChanged();
}

function _numberInRange(input, range) {
  const value = Number(input.value);
  const valid = input.value !== "" && Number.isFinite(value)
    && value >= range[0] && value <= range[1];
  input.classList.toggle("invalid", !valid);
  return valid;
}

function _thresholdValid(input, range) {
  const value = Number(input.value);
  const valid = input.value !== "" && Number.isFinite(value)
    && value > range[0] && value < range[1];
  input.classList.toggle("invalid", !valid);
  return valid;
}

function _configInputsValid() {
  if (_configValues === null) return false;
  const ranges = _configValues.vad_ranges;
  let valid = _thresholdValid(
    document.getElementById("vadThreshold"), ranges.threshold);
  valid = _numberInRange(
    document.getElementById("vadMaxChunk"), ranges.max_chunk_seconds) && valid;
  valid = _numberInRange(
    document.getElementById("vadEndPause"), ranges.request_end_pause_seconds) && valid;
  valid = _numberInRange(
    document.getElementById("vadCooldown"), ranges.resume_cooldown_seconds) && valid;
  if (document.getElementById("ttsCustomRoutes").checked) {
    for (const lang of _configValues.tts.languages) {
      const engine = document.getElementById("ttsEngine-" + lang).value;
      for (const spec of _configValues.tts.schemas[engine]) {
        const input = document.getElementById(`tts-${lang}-${spec.name}`);
        const fieldValid = _ttsFieldValid(input, spec);
        input.classList.toggle("invalid", !fieldValid);
        valid = fieldValid && valid;
      }
    }
  }
  return valid;
}

function _ttsFieldValid(input, spec) {
  if (input.value === "") return spec.nullable;
  if (spec.kind === "string") return !spec.non_empty || input.value.trim() !== "";
  if (spec.kind === "boolean") return input.value === "true" || input.value === "false";
  const value = Number(input.value);
  if (!Number.isFinite(value)) return false;
  if (spec.kind === "integer" && !Number.isInteger(value)) return false;
  if (spec.minimum === null) return true;
  return spec.exclusive_minimum ? value > spec.minimum : value >= spec.minimum;
}

function onConfigInputChanged() {
  _updateApplyButtonEnabled();
}

function _collectTtsRoutes() {
  if (!document.getElementById("ttsCustomRoutes").checked) return null;
  const routes = {};
  for (const lang of _configValues.tts.languages) {
    const engine = document.getElementById("ttsEngine-" + lang).value;
    const route = { engine };
    for (const spec of _configValues.tts.schemas[engine]) {
      const input = document.getElementById(`tts-${lang}-${spec.name}`);
      route[spec.name] = _readTtsField(input, spec);
    }
    routes[lang] = route;
  }
  return routes;
}

function _readTtsField(input, spec) {
  if (input.value === "" && spec.nullable) return null;
  if (spec.kind === "boolean") return input.value === "true";
  if (spec.kind === "integer") return Number.parseInt(input.value, 10);
  if (spec.kind === "number") return Number(input.value);
  return input.value;
}

function applyConfigSelection() {
  const model = document.getElementById("modelSelect").value;
  const microphone = _selectedMicrophoneOption();
  _sendControl("save_config_selection", {
    model,
    microphone: microphone.device,
    microphone_host_api: microphone.host_api,
    ui_language: document.getElementById("uiLangSelect").value,
    response_mode: document.getElementById("responseModeSelect").value,
    vad: {
      threshold: Number(document.getElementById("vadThreshold").value),
      max_chunk_seconds: Math.round(Number(document.getElementById("vadMaxChunk").value)),
      request_end_pause_seconds: Number(document.getElementById("vadEndPause").value),
      resume_cooldown_seconds: Number(document.getElementById("vadCooldown").value),
    },
    tts_routes: _collectTtsRoutes(),
    tts_enabled: document.getElementById("ttsEnabled").checked,
  });
}

// task-journal-05/06: Journal view. Session list + feed over the
// task-journal-04 HTTP endpoints, plus (task-journal-06) live appends via
// the journal_event state delta and audio playback on the tiles. Content
// fetches reuse the same
// token the WS transport reads from the URL, so the journal is gated by
// exactly the auth the rest of the console already has.
//
// Hidden mode is defense in depth, deliberately on both sides: the CSS
// swaps the whole view for a generic placeholder the moment
// data-visibility="hidden" lands (same pattern as the vision chip detail),
// _onJournalVisibilityChanged() drops already-fetched content from the DOM,
// AND the transport itself refuses journal content while Hidden
// (task-journal-04) - so even a UI bug here cannot surface dialog history.
let _journalSelectedSessionId = null;
// Bumped whenever already-rendered journal content stops being valid
// (Hidden activates). Every fetch captures the generation before its await
// and drops its response if it changed - a stale sessions/feed response
// must never repopulate the DOM that _clearJournalContent() just wiped,
// or the "app.js drops fetched content while Hidden" layer would only be
// true until the next response arrived.
let _journalContentGeneration = 0;
// task-journal-06 (review P2): a live journal_event racing an in-flight
// feed fetch must not append and then be wiped by the older response's
// _renderJournalFeed(). While any feed fetch is in flight, live events for
// the displayed session record the session id in
// _journalFeedRefetchSessionId instead of appending; every fetch completion
// (rendered or stale - a stale one can be the last to land) runs
// _maybeRefetchJournalFeed(), which refetches once all fetches are done and
// the deferred session is still the one on screen.
let _journalFeedFetchesInFlight = 0;
let _journalFeedRefetchSessionId = null;
let _journalSessions = [];
let _journalSearchActive = false;
let _journalSearchGeneration = 0;
let _journalSearchTimer = null;
let _journalContextHighlightTimer = null;
let _journalUsageBySession = new Map();
let _journalActiveSessionId = null;
let _journalInputInFlight = false;
let _journalAttachmentEntries = [];
let _journalSelectPendingInputSession = false;
let _journalForkInFlightSessionId = null;
let _journalNewContextInFlight = false;
const _MEMORY_FILE_IDS = ["self", "memory"];
const _MEMORY_FILE_TITLE_KEYS = {
  self: "journal_memory_self_title",
  memory: "journal_memory_memory_title",
};
const _MEMORY_FILE_DESCRIPTION_KEYS = {
  self: "journal_memory_self_description",
  memory: "journal_memory_memory_description",
};
let _journalMemoryOpen = false;
let _journalMemoryFiles = new Map();
const ACTIVE_VIEWS = ["status", "journal", "settings"];

function _isJournalActive() {
  return document.documentElement.getAttribute("data-view") === "journal";
}

function _isHiddenActive() {
  return document.documentElement.getAttribute("data-visibility") === "hidden";
}

function setActiveView(view) {
  if (!ACTIVE_VIEWS.includes(view)) {
    throw new Error("Unknown active view: " + view);
  }
  if (
    document.documentElement.getAttribute("data-view") === "journal" &&
    view !== "journal" &&
    !_confirmDiscardJournalMemoryChanges()
  ) return;
  // Pure UI navigation - unlike the engine-confirmed controls above,
  // there is no engine state to wait for, so this applies immediately.
  document.documentElement.setAttribute("data-view", view);
  document
    .querySelectorAll("#viewToggle button")
    .forEach((button) => button.classList.toggle("sel", button.dataset.view === view));
  syncRadioGroup(document.getElementById("viewToggle"));
  if (view === "journal" && !_isHiddenActive()) {
    refreshJournalSessions(true);
  } else if (view === "settings") {
    refreshSettingsOptions();
  }
}

function _onJournalVisibilityChanged(mode) {
  // demo.html loads app.js without the journal markup (it is a pre-journal
  // QA harness); the hook must be a no-op there.
  if (!document.getElementById("journalView")) return;
  if (mode === "hidden") {
    _clearJournalContent();
  } else if (_isJournalActive()) {
    // Hidden clears the selection deliberately, so reopening selects the
    // newest available session instead of restoring a stale feed.
    refreshJournalSessions();
  }
  _syncJournalInputControls();
}

function _clearJournalContent() {
  _journalContentGeneration += 1;
  _deactivateJournalSearch();
  _clearJournalSearchControls();
  _stopJournalPlayback();
  _clearJournalContextHighlight();
  _journalFeedRefetchSessionId = null;
  _journalSelectedSessionId = null;
  _journalUsageBySession = new Map();
  _journalActiveSessionId = null;
  _journalSelectPendingInputSession = false;
  _journalForkInFlightSessionId = null;
  _journalNewContextInFlight = false;
  _clearJournalMemoryPanel();
  _clearJournalAnnotationPanel();
  _clearJournalConsolidationPanel();
  _clearJournalAttachments();
  _updateJournalNewContextButton();
  _setJournalInputStatus("");
  document.getElementById("journalSessionList").replaceChildren();
  document.getElementById("journalUsageTotal").textContent = "";
  document.getElementById("journalSessionsEmpty").hidden = false;
  _showJournalNoSelection();
}

function _showJournalNoSelection() {
  document.getElementById("journalFeed").replaceChildren();
  const empty = document.getElementById("journalFeedEmpty");
  empty.hidden = false;
  empty.textContent = uiString("journal_no_selection");
}

function _confirmDiscardJournalMemoryChanges() {
  if (!_journalMemoryHasUnsavedChanges()) return true;
  return window.confirm(uiString("journal_memory_discard_confirm"));
}

function _confirmStartNewJournalContext() {
  if (!_confirmDiscardJournalMemoryChanges()) return false;
  if (_journalActiveSessionId === null) return true;
  return window.confirm(uiString("journal_new_context_confirm"));
}

function _journalMemoryHasUnsavedChanges() {
  for (const state of _journalMemoryFiles.values()) {
    if (state.content !== state.savedContent) return true;
  }
  return false;
}

async function toggleJournalMemoryPanel() {
  if (_isHiddenActive()) {
    _setJournalInputStatus(uiString("journal_memory_hidden"));
    return;
  }
  if (_journalMemoryOpen && !_confirmDiscardJournalMemoryChanges()) return;
  _journalMemoryOpen = !_journalMemoryOpen;
  document.getElementById("journalMemoryPanel").hidden = !_journalMemoryOpen;
  // task-ui-ux-5: targets the inner .toggle-label span, not the button
  // itself - the button now also carries a prepended icon (_attachStaticIcons())
  // that a blind button.textContent write would silently delete.
  document.querySelector("#journalMemoryToggle .toggle-label").textContent = uiString(
    _journalMemoryOpen ? "journal_memory_close" : "journal_memory_open");
  if (_journalMemoryOpen) await loadJournalMemoryFiles();
}

function _clearJournalMemoryPanel() {
  _journalMemoryOpen = false;
  _journalMemoryFiles = new Map();
  const panel = document.getElementById("journalMemoryPanel");
  if (panel) panel.hidden = true;
  const toggleLabel = document.querySelector("#journalMemoryToggle .toggle-label");
  if (toggleLabel) toggleLabel.textContent = uiString("journal_memory_open");
  const files = document.getElementById("journalMemoryFiles");
  if (files) files.replaceChildren();
}

async function loadJournalMemoryFiles() {
  const loaded = new Map();
  for (const fileId of _MEMORY_FILE_IDS) {
    const payload = await _fetchJournalJson("/api/memory/files/" + fileId);
    if (!payload) {
      _setJournalInputStatus(uiString("journal_memory_load_failed"));
      return;
    }
    loaded.set(fileId, {
      fileId,
      content: payload.content || "",
      savedContent: payload.content || "",
      maxChars: payload.max_chars || 0,
      status: "",
      saving: false,
    });
  }
  _journalMemoryFiles = loaded;
  _renderJournalMemoryFiles();
}

function _renderJournalMemoryFiles() {
  const container = document.getElementById("journalMemoryFiles");
  container.replaceChildren();
  for (const fileId of _MEMORY_FILE_IDS) {
    container.appendChild(_journalMemoryFileElement(fileId));
  }
  initRovingList(container, ".journal-memory-file", {
    getLabel: (section) => section.querySelector("h3")?.textContent || "",
  });
}

function _journalMemoryFileElement(fileId) {
  const state = _journalMemoryFiles.get(fileId);
  const section = document.createElement("section");
  section.tabIndex = -1; // roving tabindex, set by initRovingList() above
  section.className = "journal-memory-file";
  section.dataset.fileId = fileId;

  const header = document.createElement("div");
  header.className = "journal-memory-file-header";
  const title = document.createElement("h3");
  title.textContent = uiString(_MEMORY_FILE_TITLE_KEYS[fileId]);
  const description = document.createElement("p");
  description.textContent = uiString(_MEMORY_FILE_DESCRIPTION_KEYS[fileId]);
  header.append(title, description);

  const textarea = document.createElement("textarea");
  textarea.value = state.content;
  textarea.rows = 7;
  textarea.addEventListener("input", () => onJournalMemoryInput(fileId, textarea.value));

  const footer = document.createElement("div");
  footer.className = "journal-memory-footer";
  const counter = document.createElement("span");
  counter.className = "journal-memory-counter";
  counter.textContent = _journalMemoryCounterText(state);
  const status = document.createElement("span");
  status.className = "journal-memory-status";
  status.textContent = state.status;
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = uiString("journal_memory_save");
  save.disabled = !_journalMemoryCanSave(state);
  save.addEventListener("click", () => saveJournalMemoryFile(fileId));
  footer.append(counter, status, save);

  section.classList.toggle("dirty", state.content !== state.savedContent);
  section.classList.toggle("over-limit", state.content.length > state.maxChars);
  section.append(header, textarea, footer);
  return section;
}

function onJournalMemoryInput(fileId, content) {
  const state = _journalMemoryFiles.get(fileId);
  if (!state) return;
  _journalMemoryFiles.set(fileId, { ...state, content, status: "" });
  _refreshJournalMemoryFileState(fileId);
}

function _refreshJournalMemoryFileState(fileId) {
  const state = _journalMemoryFiles.get(fileId);
  const section = document.querySelector(
    '#journalMemoryFiles .journal-memory-file[data-file-id="' + fileId + '"]');
  if (!state || !section) return;
  section.classList.toggle("dirty", state.content !== state.savedContent);
  section.classList.toggle("over-limit", state.content.length > state.maxChars);
  const counter = section.querySelector(".journal-memory-counter");
  if (counter) counter.textContent = _journalMemoryCounterText(state);
  const status = section.querySelector(".journal-memory-status");
  if (status) status.textContent = state.status;
  const save = section.querySelector(".journal-memory-footer button");
  if (save) save.disabled = !_journalMemoryCanSave(state);
}

function _journalMemoryCounterText(state) {
  return uiString("journal_memory_counter")
    .replace("{chars}", String(state.content.length))
    .replace("{max}", String(state.maxChars));
}

function _journalMemoryCanSave(state) {
  return (
    !state.saving &&
    state.content !== state.savedContent &&
    state.content.length <= state.maxChars
  );
}

async function saveJournalMemoryFile(fileId) {
  const state = _journalMemoryFiles.get(fileId);
  if (!state) return;
  if (state.content.length > state.maxChars) {
    _journalMemoryFiles.set(fileId, {
      ...state,
      status: uiString("journal_memory_over_limit"),
    });
    _refreshJournalMemoryFileState(fileId);
    return;
  }
  const url = _journalUrl("/api/memory/files/" + fileId);
  if (url === null) {
    _setJournalInputStatus(uiString("transport_no_token"));
    return;
  }
  const savedContent = state.content;
  _journalMemoryFiles.set(fileId, { ...state, saving: true, status: "" });
  _refreshJournalMemoryFileState(fileId);
  try {
    const response = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: savedContent }),
    });
    const payload = await response.json();
    const latest = _journalMemoryFiles.get(fileId) || state;
    if (payload.status === "ok") {
      const persistedContent = payload.content || "";
      _journalMemoryFiles.set(fileId, {
        ...latest,
        content: latest.content === savedContent ? persistedContent : latest.content,
        savedContent: persistedContent,
        maxChars: payload.max_chars || latest.maxChars,
        saving: false,
        status: uiString("journal_memory_saved"),
      });
    } else {
      _journalMemoryFiles.set(fileId, {
        ...latest,
        saving: false,
        status: _journalMemorySaveError(payload),
      });
    }
  } catch (error) {
    console.error("Journal memory save failed:", error);
    const latest = _journalMemoryFiles.get(fileId) || state;
    _journalMemoryFiles.set(fileId, {
      ...latest,
      saving: false,
      status: uiString("journal_memory_save_failed"),
    });
  }
  _refreshJournalMemoryFileState(fileId);
}

function _journalMemorySaveError(payload) {
  if (payload.status === "hidden") return uiString("journal_memory_hidden");
  if (payload.reason === "over_limit") return uiString("journal_memory_over_limit");
  return uiString("journal_memory_save_failed");
}

async function startNewJournalContext() {
  if (_journalNewContextInFlight) {
    _setJournalInputStatus(uiString("journal_input_busy"));
    return;
  }
  if (_isHiddenActive()) {
    _setJournalInputStatus(uiString("journal_new_context_hidden"));
    return;
  }
  if (!_confirmStartNewJournalContext()) return;
  const url = _journalUrl("/api/journal/context/new");
  if (url === null) {
    _setJournalInputStatus(uiString("transport_no_token"));
    return;
  }
  _journalNewContextInFlight = true;
  _updateJournalNewContextButton();
  try {
    const response = await fetch(url, { method: "POST" });
    const payload = await response.json();
    if (payload.status === "ok") {
      _journalSelectedSessionId = payload.session_id || null;
      _journalActiveSessionId = payload.session_id || null;
      _setJournalInputStatus(uiString("journal_new_context_ready"));
      await refreshJournalSessions();
      if (payload.session_id) selectJournalSession(payload.session_id);
      return;
    }
    _setJournalInputStatus(_journalNewContextErrorMessage(payload));
  } catch (error) {
    console.error("Journal new context failed:", error);
    _setJournalInputStatus(uiString("journal_new_context_failed"));
  } finally {
    _journalNewContextInFlight = false;
    _updateJournalNewContextButton();
  }
}

function _updateJournalNewContextButton() {
  const button = document.getElementById("journalNewContextButton");
  if (button) button.disabled = _journalNewContextInFlight;
}

function _journalNewContextErrorMessage(payload) {
  if (payload.status === "hidden") return uiString("journal_new_context_hidden");
  if (payload.reason === "busy") return uiString("journal_new_context_busy");
  return uiString("journal_new_context_failed");
}

function openJournalFilePicker() {
  if (_isHiddenActive()) {
    _setJournalInputStatus(uiString("journal_input_hidden"));
    return;
  }
  document.getElementById("journalFileInput").click();
}

function onJournalFileInputChanged(event) {
  _addJournalAttachmentFiles(event.target.files);
  event.target.value = "";
}

function onJournalAttachmentDragOver(event) {
  if (_isHiddenActive()) return;
  event.preventDefault();
  event.stopPropagation();
  document.getElementById("journalDropTarget").classList.add("drag-over");
}

function onJournalAttachmentDragLeave(event) {
  event.currentTarget.classList.remove("drag-over");
}

function onJournalAttachmentDrop(event) {
  if (_isHiddenActive()) return;
  event.preventDefault();
  event.stopPropagation();
  document.getElementById("journalDropTarget").classList.remove("drag-over");
  if (event.dataTransfer) _addJournalAttachmentFiles(event.dataTransfer.files);
}

function installJournalDocumentDropGuard() {
  document.addEventListener("dragover", _guardJournalDocumentDrop);
  document.addEventListener("drop", _guardJournalDocumentDrop);
}

function _guardJournalDocumentDrop(event) {
  if (!event.dataTransfer || !Array.from(event.dataTransfer.types || []).includes("Files")) {
    return;
  }
  event.preventDefault();
  const target = event.target;
  if (
    target &&
    target.closest &&
    target.closest("#journalDropTarget") &&
    !_isHiddenActive()
  ) return;
  event.stopPropagation();
}

function _addJournalAttachmentFiles(files) {
  if (_isHiddenActive()) {
    _clearJournalAttachments();
    _setJournalInputStatus(uiString("journal_input_hidden"));
    return;
  }
  _journalAttachmentEntries = _journalAttachmentEntries.filter((entry) => !entry.sent);
  for (const file of Array.from(files || [])) {
    _journalAttachmentEntries.push({ file, result: null, sent: false, persist: false });
  }
  _renderJournalAttachments();
  _setJournalInputStatus("");
}

function removeJournalAttachment(index) {
  _journalAttachmentEntries.splice(index, 1);
  _renderJournalAttachments();
}

function toggleJournalAttachmentPersist(index) {
  const entry = _journalAttachmentEntries[index];
  if (!entry || entry.sent) return;
  entry.persist = !entry.persist;
  _renderJournalAttachments();
}

// 0-based indices into the pending-file order (the same order the FormData
// appends "files"), for uploads the user marked to keep as session files.
function _journalPersistIndices() {
  const indices = [];
  let pendingIndex = 0;
  for (const entry of _journalAttachmentEntries) {
    if (entry.sent) continue;
    if (entry.persist) indices.push(pendingIndex);
    pendingIndex += 1;
  }
  return indices;
}

function _clearJournalAttachments() {
  _journalAttachmentEntries = [];
  const fileInput = document.getElementById("journalFileInput");
  if (fileInput) fileInput.value = "";
  _renderJournalAttachments();
}

function _journalPendingAttachmentFiles() {
  return _journalAttachmentEntries
    .filter((entry) => !entry.sent)
    .map((entry) => entry.file);
}

function _applyJournalAttachmentResults(payload) {
  const files = payload.files || [];
  if (files.length === 0) return;
  const keepPending = payload.reason === "busy";
  _journalAttachmentEntries = _journalAttachmentEntries.map((entry, index) => ({
    ...entry,
    result: files[index] || entry.result,
    sent: !keepPending && files[index] && files[index].status !== "rejected",
  }));
  _renderJournalAttachments();
}

function _clearCompletedJournalAttachments() {
  // Keep a row when the file was rejected OR its persistent save failed:
  // an accepted file whose persistence failed still has status "accepted"
  // (its transient content was delivered), so clearing on status alone would
  // silently hide the "Not saved" failure the user needs to see.
  _journalAttachmentEntries = _journalAttachmentEntries.filter(
    (entry) =>
      entry.result &&
      (entry.result.status === "rejected" || _entryPersistFailed(entry)));
  _renderJournalAttachments();
}

function _entryPersistFailed(entry) {
  const persistent = entry.result && entry.result.persistent;
  return Boolean(persistent && persistent.status === "rejected");
}

function _renderJournalAttachments() {
  const list = document.getElementById("journalAttachmentList");
  if (!list) return;
  list.replaceChildren();
  _journalAttachmentEntries.forEach((entry, index) => {
    list.appendChild(_journalAttachmentElement(entry, index));
  });
}

function _journalAttachmentElement(entry, index) {
  const result = entry.result;
  const row = document.createElement("div");
  row.className = "journal-attachment";
  if (result) row.dataset.status = result.status;

  const body = document.createElement("div");
  body.className = "journal-attachment-body";

  const name = document.createElement("div");
  name.className = "journal-attachment-name";
  name.textContent = result && result.filename ? result.filename : entry.file.name;

  const meta = document.createElement("div");
  meta.className = "journal-attachment-meta";
  const classLabel = _journalAttachmentClassLabel(
    result && result.class ? result.class : _journalAttachmentKind(entry.file));
  const status = result
    ? uiString("journal_attachment_status_" + result.status)
    : uiString("journal_attachment_pending");
  meta.textContent = classLabel + " - " + _formatJournalBytes(entry.file.size) + " - " + status;
  body.append(name, meta);

  const detailText = _journalAttachmentDetail(result);
  if (detailText) {
    const detail = document.createElement("div");
    detail.className = "journal-attachment-detail";
    detail.textContent = detailText;
    body.appendChild(detail);
  }

  const persistText = _journalAttachmentPersistDetail(result);
  if (persistText) {
    const persistDetail = document.createElement("div");
    persistDetail.className = "journal-attachment-detail journal-attachment-persist-detail";
    persistDetail.textContent = persistText;
    body.appendChild(persistDetail);
  }

  if (!entry.sent) {
    body.appendChild(_journalAttachmentPersistToggle(entry, index));
  }

  row.appendChild(body);
  // Removable while still pending, or once sent only if the persistent save
  // failed - so the user can dismiss that failure notice.
  if (!entry.sent || _entryPersistFailed(entry)) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "journal-attachment-remove";
    remove.title = uiString("journal_attachment_remove");
    remove.textContent = "x";
    remove.addEventListener("click", () => removeJournalAttachment(index));
    row.appendChild(remove);
  }
  return row;
}

function _journalAttachmentPersistToggle(entry, index) {
  const label = document.createElement("label");
  label.className = "journal-attachment-persist";
  label.title = uiString("journal_attachment_persist_hint");

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = Boolean(entry.persist);
  checkbox.addEventListener("change", () => toggleJournalAttachmentPersist(index));

  const text = document.createElement("span");
  text.textContent = uiString("journal_attachment_persist");

  label.append(checkbox, text);
  return label;
}

function _journalAttachmentPersistDetail(result) {
  const persistent = result && result.persistent;
  if (!persistent) return "";
  if (persistent.status === "saved") {
    return uiString("journal_attachment_persist_saved").replace(
      "{name}", persistent.storage_name || "");
  }
  return uiString("journal_attachment_persist_rejected").replace(
    "{reason}", persistent.reason || "");
}

function _journalAttachmentDetail(result) {
  if (!result) return "";
  const parts = [];
  if (result.reason) parts.push(result.reason);
  for (const warning of result.warnings || []) {
    parts.push(warning);
  }
  return parts.join(" ");
}

function _journalAttachmentKind(file) {
  const type = (file.type || "").toLowerCase();
  if (type.startsWith("audio/")) return "audio";
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("text/") || type === "application/json") return "text";
  return "unknown";
}

function _journalAttachmentClassLabel(value) {
  return uiString("journal_attachment_class_" + (value || "unknown"));
}

// Input targets the active (live) session, never the one merely being viewed.
// So the dock only accepts input while the selected session IS the active one;
// for any other session it is hidden behind an explanatory note (CSS), and its
// controls are disabled as defense in depth.
function _journalInputTargetsSelectedSession() {
  return (
    _journalActiveSessionId !== null &&
    _journalSelectedSessionId === _journalActiveSessionId);
}

function _syncJournalInputControls() {
  const inactiveSession = !_journalInputTargetsSelectedSession();
  const disabled = _journalInputInFlight || _isHiddenActive() || inactiveSession;
  const input = document.getElementById("journalTextInput");
  const send = document.getElementById("journalSendButton");
  const attach = document.getElementById("journalAttachButton");
  const fileInput = document.getElementById("journalFileInput");
  const dock = document.getElementById("journalInputDock");
  if (input) input.disabled = disabled;
  if (send) send.disabled = disabled;
  if (attach) attach.disabled = disabled;
  if (fileInput) fileInput.disabled = disabled;
  // Hidden mode has its own whole-view placeholder, so the inactive-session
  // note is suppressed there to avoid two competing messages.
  if (dock) {
    dock.classList.toggle("inactive-session", inactiveSession && !_isHiddenActive());
  }
}

async function submitJournalInput() {
  if (_journalInputInFlight) {
    _setJournalInputStatus(uiString("journal_input_busy"));
    return;
  }
  if (_isHiddenActive()) {
    _clearJournalAttachments();
    _setJournalInputStatus(uiString("journal_input_hidden"));
    return;
  }
  if (_journalActiveSessionId === null) {
    _setJournalInputStatus(uiString("journal_new_context_required"));
    return;
  }
  const input = document.getElementById("journalTextInput");
  const text = input.value;
  const pendingFiles = _journalPendingAttachmentFiles();
  const url = _journalUrl("/api/journal/input");
  if (url === null) {
    _setJournalInputStatus(uiString("transport_no_token"));
    return;
  }
  _journalInputInFlight = true;
  _journalSelectPendingInputSession = true;
  _syncJournalInputControls();
  try {
    let requestOptions;
    if (pendingFiles.length > 0) {
      const body = new FormData();
      body.append("text", text);
      for (const file of pendingFiles) {
        body.append("files", file, file.name);
      }
      const persistIndices = _journalPersistIndices();
      if (persistIndices.length > 0) {
        body.append("persist", JSON.stringify(persistIndices));
      }
      requestOptions = { method: "POST", body };
    } else {
      requestOptions = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      };
    }
    const response = await fetch(url, requestOptions);
    const payload = await response.json();
    if (payload.files) _applyJournalAttachmentResults(payload);
    if (payload.status === "accepted") {
      if (input.value === text) input.value = "";
      _clearCompletedJournalAttachments();
      _setJournalInputStatus(uiString("journal_input_sent"));
    } else if (payload.status === "hidden") {
      _clearJournalAttachments();
      _journalSelectPendingInputSession = false;
      _setJournalInputStatus(uiString("journal_input_hidden"));
    } else {
      _journalSelectPendingInputSession = false;
      _setJournalInputStatus(_journalInputErrorMessage(payload));
    }
  } catch (error) {
    console.error("Journal input failed:", error);
    _journalSelectPendingInputSession = false;
    _setJournalInputStatus(uiString("journal_input_failed"));
  } finally {
    _journalInputInFlight = false;
    _syncJournalInputControls();
  }
}

function _journalInputErrorMessage(payload) {
  if (payload.reason === "busy") return uiString("journal_input_busy");
  if (payload.reason === "empty") return uiString("journal_input_empty");
  if (payload.reason === "over_limit") {
    return uiString("journal_input_over_limit").replace(
      "{max}", String(payload.max_chars));
  }
  return uiString("journal_input_failed");
}

function _setJournalInputStatus(text) {
  const status = document.getElementById("journalInputStatus");
  if (status) status.textContent = text;
}

function onJournalInputKeyDown(event) {
  if (event.key !== "Enter" || event.shiftKey) return;
  event.preventDefault();
  submitJournalInput();
}

async function _fetchJournalJson(path) {
  const url = _journalUrl(path);
  if (url === null) return null;
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error("journal request failed: " + response.status);
    const payload = await response.json();
    // The transport answers {"status": "hidden"} while Hidden - treat it
    // exactly like having no content (the CSS placeholder is already up).
    return payload.status === "ok" ? payload : null;
  } catch (error) {
    console.error("Journal fetch failed:", error);
    return null;
  }
}

function _journalUrl(path) {
  const token = new URLSearchParams(window.location.search).get("token");
  if (!token) return null;
  const separator = path.includes("?") ? "&" : "?";
  return path + separator + "token=" + encodeURIComponent(token);
}

async function refreshJournalSessions(refetchSelectedFeed = false) {
  const generation = _journalContentGeneration;
  const [payload, usage] = await Promise.all([
    _fetchJournalJson("/api/journal/sessions"),
    _fetchJournalJson("/api/journal/usage"),
  ]);
  if (generation !== _journalContentGeneration || _isHiddenActive()) return;
  _applyJournalUsage(usage);
  const sessions = payload ? payload.sessions : [];
  // Newest first regardless of the endpoint's ordering.
  sessions.sort((a, b) => (a.start_timestamp < b.start_timestamp ? 1 : -1));
  _journalSessions = sessions;
  const list = document.getElementById("journalSessionList");
  list.replaceChildren();
  document.getElementById("journalSessionsEmpty").hidden = sessions.length !== 0;
  if (!sessions.some((session) => session.id === _journalSelectedSessionId)) {
    _journalSelectedSessionId = null;
  }
  for (const session of sessions) {
    list.appendChild(_journalSessionElement(session));
  }
  initRovingList(
    list,
    ".journal-session",
    {
      onActivate: (row) => selectJournalSession(row.dataset.sessionId),
      onToggle: (row) => selectJournalSession(row.dataset.sessionId),
      getLabel: (row) => row.querySelector(".journal-session-title")?.textContent || "",
    },
    (item) => item.classList.contains("sel")
  );
  initContextMenuTrigger(list, ".journal-session", _journalSessionMenuEntries);
  if (_journalSelectedSessionId === null && sessions.length !== 0) {
    selectJournalSession(sessions[0].id);
  } else if (refetchSelectedFeed && _journalSelectedSessionId !== null) {
    if (_isJournalSearchActive()) {
      _scheduleJournalSearch();
    } else {
      selectJournalSession(_journalSelectedSessionId);
    }
  }
}

function _applyJournalUsage(payload) {
  const usage = payload || { total_bytes: 0, active_session_id: null, sessions: [] };
  _journalActiveSessionId = usage.active_session_id || null;
  _syncJournalInputControls();
  _journalUsageBySession = new Map(
    (usage.sessions || []).map((session) => [session.id, session.bytes || 0]));
  document.getElementById("journalUsageTotal").textContent =
    uiString("journal_usage_total").replace("{size}", _formatJournalBytes(usage.total_bytes || 0));
}

function _journalSessionElement(session) {
  const row = document.createElement("div");
  row.tabIndex = -1; // roving tabindex, set by initRovingList() below
  row.setAttribute("role", "option");
  row.className = "journal-session";
  row.dataset.sessionId = session.id;
  const selected = session.id === _journalSelectedSessionId;
  row.classList.toggle("sel", selected);
  row.setAttribute("aria-selected", String(selected));

  // task-ui-ux-5: title leads (the session's identity); date/time/duration/
  // size collapse into one dimmed meta line beneath it, replacing the old
  // separate when/size rows - see the CSS comment on .journal-session-title.
  const title = document.createElement("div");
  title.className = "journal-session-title";
  title.textContent = session.title;

  const meta = document.createElement("div");
  meta.className = "journal-session-meta";
  const date = document.createElement("span");
  date.textContent = _formatJournalDate(session.start_timestamp);
  const time = document.createElement("span");
  time.textContent = _formatJournalTime(session.start_timestamp);
  const duration = document.createElement("span");
  duration.textContent = _formatJournalDuration(
    session.start_timestamp, session.end_timestamp);
  const size = document.createElement("span");
  size.textContent = _formatJournalBytes(_journalUsageBySession.get(session.id) || 0);
  meta.append(date, time, duration, size);

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "journal-session-delete";
  deleteButton.appendChild(_icon("delete"));
  deleteButton.title = uiString(
    session.id === _journalActiveSessionId
      ? "journal_session_active"
      : "journal_session_delete");
  deleteButton.setAttribute("aria-label", deleteButton.title);
  deleteButton.disabled = session.id === _journalActiveSessionId;
  deleteButton.addEventListener("click", (event) => {
    event.stopPropagation();
    deleteJournalSession(session.id);
  });

  const continueButton = document.createElement("button");
  continueButton.type = "button";
  continueButton.className = "journal-session-continue";
  continueButton.appendChild(_icon("continue"));
  continueButton.title = uiString("journal_session_continue");
  continueButton.setAttribute("aria-label", continueButton.title);
  continueButton.disabled =
    session.id === _journalActiveSessionId ||
    session.id === _journalForkInFlightSessionId;
  continueButton.addEventListener("click", (event) => {
    event.stopPropagation();
    continueJournalSession(session.id);
  });

  const menuButton = document.createElement("button");
  menuButton.type = "button";
  menuButton.className = "context-menu-button";
  menuButton.textContent = "...";
  menuButton.title = uiString("context_menu_open");
  menuButton.setAttribute("aria-label", uiString("context_menu_open"));
  menuButton.addEventListener("click", (event) => {
    event.stopPropagation();
    openItemContextMenu(row, menuButton, _journalSessionMenuEntries);
  });

  const actions = document.createElement("div");
  actions.className = "journal-session-actions";
  if (session.id !== _journalActiveSessionId) actions.appendChild(continueButton);
  actions.appendChild(deleteButton);
  actions.appendChild(menuButton);

  row.append(title, meta, actions);
  row.addEventListener("click", () => selectJournalSession(session.id));
  // Enter/Space/arrows/Home/End are handled by the roving-list keydown
  // listener installed on #journalSessionList (initRovingList() in
  // refreshJournalSessions()), not per-row - so a rebuilt list never leaks
  // per-row listeners the way the old per-row handler could.
  return row;
}

// Shared by the visible menu button above and the container-level
// right-click/Shift+F10 trigger initContextMenuTrigger() wires in
// refreshJournalSessions() - both resolve the same session from
// row.dataset.sessionId (the roving-list handlers already use this same
// lookup, see refreshJournalSessions()'s onActivate/onToggle), so there is
// one place session-menu actions are decided, not three.
function _journalSessionMenuEntries(row) {
  const sessionId = row.dataset.sessionId;
  const session = _journalSessions.find((item) => item.id === sessionId);
  if (!session) return [];
  const isActive = sessionId === _journalActiveSessionId;
  return [
    !isActive && {
      label: uiString("journal_session_continue"),
      run: () => continueJournalSession(sessionId),
      disabled: sessionId === _journalForkInFlightSessionId,
    },
    !isActive && {
      label: uiString("journal_session_delete"),
      run: () => deleteJournalSession(sessionId),
    },
    {
      label: uiString("journal_session_copy_title"),
      icon: _icon("copy"),
      run: () => _copyToClipboardWithJournalStatus(session.title),
    },
    {
      label: uiString("journal_session_info"),
      run: () => openSessionInfoOverlay(sessionId),
    },
  ];
}

async function continueJournalSession(sessionId) {
  if (_isHiddenActive()) {
    _setJournalInputStatus(uiString("journal_fork_hidden"));
    return;
  }
  if (_journalForkInFlightSessionId !== null) {
    _setJournalInputStatus(uiString("journal_input_busy"));
    return;
  }
  const url = _journalUrl(
    "/api/journal/sessions/" + encodeURIComponent(sessionId) + "/fork");
  if (url === null) {
    _setJournalInputStatus(uiString("transport_no_token"));
    return;
  }
  _journalForkInFlightSessionId = sessionId;
  refreshJournalSessions();
  try {
    const response = await fetch(url, { method: "POST" });
    const payload = await response.json();
    if (payload.status === "ok") {
      _setJournalInputStatus(uiString("journal_fork_started"));
      _journalSelectedSessionId = payload.session_id;
      await refreshJournalSessions();
      selectJournalSession(payload.session_id);
      return;
    }
    _setJournalInputStatus(_journalForkErrorMessage(payload));
  } catch (error) {
    console.error("Journal fork failed:", error);
    _setJournalInputStatus(uiString("journal_fork_failed"));
  } finally {
    _journalForkInFlightSessionId = null;
    refreshJournalSessions();
  }
}

function _journalForkErrorMessage(payload) {
  if (payload.status === "hidden") return uiString("journal_fork_hidden");
  if (payload.reason === "busy") return uiString("journal_fork_busy");
  if (payload.reason === "unknown_session") return uiString("journal_fork_unknown");
  if (payload.reason === "oversize_turn") {
    return uiString("journal_fork_oversize").replace(
      "{max}", String(payload.max_chars));
  }
  return uiString("journal_fork_failed");
}

async function deleteJournalSession(sessionId) {
  const session = _journalSessions.find((item) => item.id === sessionId);
  const title = session ? session.title : sessionId;
  const size = _formatJournalBytes(_journalUsageBySession.get(sessionId) || 0);
  const message = uiString("journal_delete_confirm")
    .replace("{title}", title)
    .replace("{size}", size);
  if (!window.confirm(message)) return;
  const url = _journalUrl("/api/journal/sessions/" + encodeURIComponent(sessionId));
  if (url === null) {
    _setJournalInputStatus(uiString("transport_no_token"));
    return;
  }
  try {
    const response = await fetch(url, { method: "DELETE" });
    const payload = await response.json();
    if (payload.status === "ok") {
      if (_journalSelectedSessionId === sessionId) {
        _journalSelectedSessionId = null;
        _showJournalNoSelection();
      }
      await refreshJournalSessions();
      if (_isJournalSearchActive()) _scheduleJournalSearch();
      return;
    }
    _setJournalInputStatus(_journalDeleteErrorMessage(payload.reason));
  } catch (error) {
    console.error("Journal delete failed:", error);
    _setJournalInputStatus(uiString("journal_delete_failed"));
  }
}

function _journalDeleteErrorMessage(reason) {
  if (reason === "active_session") return uiString("journal_delete_active");
  if (reason === "not_found") return uiString("journal_delete_not_found");
  return uiString("journal_delete_failed");
}

async function selectJournalSession(sessionId, contextEventPosition = null) {
  if (_isJournalSearchActive()) {
    _deactivateJournalSearch();
    _clearJournalSearchControls();
  }
  const generation = _journalContentGeneration;
  _journalSelectedSessionId = sessionId;
  _syncJournalInputControls();
  const sessionList = document.getElementById("journalSessionList");
  sessionList.querySelectorAll(".journal-session").forEach((row) => {
    const selected = row.dataset.sessionId === sessionId;
    row.classList.toggle("sel", selected);
    row.setAttribute("aria-selected", String(selected));
  });
  refreshRovingList(sessionList, ".journal-session", (item) => item.classList.contains("sel"));
  _journalFeedFetchesInFlight += 1;
  let payload;
  try {
    payload = await _fetchJournalJson(
      "/api/journal/sessions/" + encodeURIComponent(sessionId));
  } finally {
    _journalFeedFetchesInFlight -= 1;
  }
  // A slow response for a session the user has already navigated away
  // from (or that Hidden invalidated) must not overwrite the feed - but it
  // still has to fall through to _maybeRefetchJournalFeed() below: any
  // completion (stale, generation-invalidated, whatever) can be the last
  // one in flight, and returning early here would strand a deferred live
  // event set after the invalidation (e.g. a pre-Hidden fetch draining
  // after Open already deferred an event for the fresh view).
  const valid = generation === _journalContentGeneration && !_isHiddenActive();
  if (valid && _journalSelectedSessionId === sessionId) {
    _renderJournalFeed(payload ? payload.events : [], contextEventPosition);
    _reloadJournalAnnotationsIfOpen(sessionId);
    _reloadJournalConsolidationIfOpen(sessionId);
  }
  _maybeRefetchJournalFeed();
}

// Safety lives here, not at the call sites: every fetch completion calls
// this unconditionally, and this decides whether a refetch is safe (all
// fetches drained, not Hidden, deferred session still on screen).
function _maybeRefetchJournalFeed() {
  if (_journalFeedFetchesInFlight !== 0) return;
  if (_isHiddenActive()) return;
  if (_journalFeedRefetchSessionId === null) return;
  const sessionId = _journalFeedRefetchSessionId;
  _journalFeedRefetchSessionId = null;
  // A deferred event for a session no longer on screen needs no refetch -
  // that session's feed is fetched fresh whenever it is selected again.
  if (sessionId !== _journalSelectedSessionId) return;
  selectJournalSession(sessionId);
}

// task-journal-07: Search is a transient replacement for the selected
// session feed. It never changes the selected-session state, so clearing a
// query or jumping to a hit can restore the user's previous context.
function _journalSearchCriteria() {
  return {
    query: document.getElementById("journalSearchQuery").value.trim(),
    dateFrom: document.getElementById("journalSearchDateFrom").value,
    dateTo: document.getElementById("journalSearchDateTo").value,
  };
}

function _isJournalSearchActive() {
  return _journalSearchActive;
}

function _clearJournalSearchControls() {
  const query = document.getElementById("journalSearchQuery");
  if (!query) return;
  query.value = "";
  document.getElementById("journalSearchDateFrom").value = "";
  document.getElementById("journalSearchDateTo").value = "";
}

function _deactivateJournalSearch() {
  _journalSearchActive = false;
  _journalSearchGeneration += 1;
  if (_journalSearchTimer !== null) {
    window.clearTimeout(_journalSearchTimer);
    _journalSearchTimer = null;
  }
}

function onJournalSearchInputChanged() {
  if (_isHiddenActive()) return;
  const criteria = _journalSearchCriteria();
  if (!criteria.query && !criteria.dateFrom && !criteria.dateTo) {
    clearJournalSearch();
    return;
  }
  _journalSearchActive = true;
  _scheduleJournalSearch();
}

function _scheduleJournalSearch() {
  if (!_isJournalSearchActive()) return;
  _journalSearchGeneration += 1;
  const searchGeneration = _journalSearchGeneration;
  if (_journalSearchTimer !== null) window.clearTimeout(_journalSearchTimer);
  _journalSearchTimer = window.setTimeout(() => {
    _journalSearchTimer = null;
    _runJournalSearch(searchGeneration);
  }, 250);
}

async function _runJournalSearch(searchGeneration) {
  const criteria = _journalSearchCriteria();
  const parameters = new URLSearchParams();
  parameters.set("query", criteria.query);
  if (criteria.dateFrom) parameters.set("date_from", criteria.dateFrom);
  if (criteria.dateTo) parameters.set("date_to", criteria.dateTo);
  const contentGeneration = _journalContentGeneration;
  const payload = await _fetchJournalJson(
    "/api/journal/search?" + parameters.toString());
  if (
    searchGeneration !== _journalSearchGeneration ||
    contentGeneration !== _journalContentGeneration ||
    _isHiddenActive() ||
    !_isJournalSearchActive()
  ) return;
  _renderJournalSearchResults(payload ? payload.hits : [], criteria.query !== "");
}

function clearJournalSearch() {
  const wasSearching = _isJournalSearchActive();
  _deactivateJournalSearch();
  _clearJournalSearchControls();
  if (!wasSearching || _isHiddenActive()) return;
  if (_journalSelectedSessionId !== null) {
    selectJournalSession(_journalSelectedSessionId);
  } else {
    _showJournalNoSelection();
    refreshJournalSessions();
  }
}

function _renderJournalSearchResults(hits, highlightMatches) {
  const feed = document.getElementById("journalFeed");
  const empty = document.getElementById("journalFeedEmpty");
  _stopJournalPlayback();
  _clearJournalContextHighlight();
  feed.replaceChildren();
  empty.hidden = hits.length !== 0;
  empty.textContent = uiString("journal_search_no_results");
  if (hits.length === 0) return;

  const groups = new Map();
  for (const hit of hits) {
    const group = groups.get(hit.session_id) || [];
    group.push(hit);
    groups.set(hit.session_id, group);
  }
  for (const [sessionId, sessionHits] of groups) {
    const group = document.createElement("section");
    group.className = "journal-search-group";
    group.appendChild(_journalSearchSessionHeader(sessionId, sessionHits[0].timestamp));
    for (const hit of sessionHits) {
      group.appendChild(_journalSearchHitElement(hit, highlightMatches));
    }
    feed.appendChild(group);
  }
  feed.scrollTop = 0;
}

function _journalSearchSessionHeader(sessionId, timestamp) {
  const header = document.createElement("div");
  header.className = "journal-search-session";
  const when = document.createElement("span");
  when.textContent = _formatJournalDate(timestamp) + " " + _formatJournalTime(timestamp);
  const title = document.createElement("span");
  title.className = "journal-search-session-title";
  const session = _journalSessions.find((item) => item.id === sessionId);
  title.textContent = session ? session.title : sessionId;
  header.append(when, title);
  return header;
}

function _journalSearchHitElement(hit, highlightMatches) {
  const result = document.createElement("button");
  result.type = "button";
  result.className = "journal-search-hit";
  const meta = document.createElement("div");
  meta.className = "journal-msg-meta";
  const source = document.createElement("span");
  source.className = "journal-msg-source";
  source.textContent = uiString("journal_source_assistant");
  const time = document.createElement("span");
  time.textContent = _formatJournalTime(hit.timestamp);
  meta.append(source, time);
  const snippet = document.createElement("div");
  snippet.className = "journal-search-snippet";
  if (highlightMatches) {
    _appendHighlightedJournalSnippet(snippet, hit.snippet);
  } else {
    snippet.textContent = hit.snippet;
  }
  result.append(meta, snippet);
  result.addEventListener("click", () => _jumpToJournalSearchHit(hit));
  return result;
}

function _appendHighlightedJournalSnippet(container, snippet) {
  for (const part of String(snippet).split(/(\[[^\]]+\])/)) {
    const match = /^\[([^\]]+)\]$/.exec(part);
    if (match) {
      const mark = document.createElement("mark");
      mark.textContent = match[1];
      container.appendChild(mark);
    } else {
      container.appendChild(document.createTextNode(part));
    }
  }
}

function _jumpToJournalSearchHit(hit) {
  _deactivateJournalSearch();
  _clearJournalSearchControls();
  selectJournalSession(hit.session_id, hit.event_position);
}

function _clearJournalContextHighlight() {
  if (_journalContextHighlightTimer !== null) {
    window.clearTimeout(_journalContextHighlightTimer);
    _journalContextHighlightTimer = null;
  }
  document.querySelectorAll(".journal-context-hit").forEach((element) => {
    element.classList.remove("journal-context-hit");
  });
}

function _highlightJournalContextEvent(position) {
  const target = document.querySelector(
    '#journalFeed [data-event-position="' + String(position) + '"]');
  if (!target) return;
  target.classList.add("journal-context-hit");
  target.scrollIntoView({ block: "center" });
  _journalContextHighlightTimer = window.setTimeout(() => {
    target.classList.remove("journal-context-hit");
    _journalContextHighlightTimer = null;
  }, 1400);
}

// task-journal-06: live feed. A journal_event delta updates the session
// list metadata (new sessions appear, timestamps/duration move) and appends
// the turn to the open feed only when the affected session is the one
// displayed - viewing an old session must not jump to the current one.
function applyJournalEvent(payload) {
  // demo.html loads app.js without the journal markup (pre-journal QA
  // harness) - same no-op guard as _onJournalVisibilityChanged().
  if (!document.getElementById("journalView")) return;
  // Defense in depth alongside the transport suppressing pushes while
  // Hidden: even a stray push must not touch the wiped DOM.
  if (_isHiddenActive()) return;
  if (!_isJournalActive()) return;
  refreshJournalSessions();
  if (_shouldSelectJournalInputSession(payload)) {
    _journalSelectPendingInputSession = false;
    selectJournalSession(payload.session_id);
    return;
  }
  if (_isJournalSearchActive()) {
    _scheduleJournalSearch();
    return;
  }
  if (payload.session_id !== _journalSelectedSessionId) return;
  if (_journalFeedFetchesInFlight > 0) {
    // A feed fetch that started before this event may resolve after it and
    // _renderJournalFeed() would rebuild the feed from the older response,
    // silently dropping the appended turn. Defer to a refetch once every
    // in-flight response has landed instead of racing them.
    _journalFeedRefetchSessionId = payload.session_id;
    return;
  }
  _appendJournalTurn(payload);
}

function _shouldSelectJournalInputSession(payload) {
  return (
    _journalSelectPendingInputSession &&
    payload.role === "user" &&
    (payload.source === "dock" || payload.source === "attachment")
  );
}

// Bottom-anchoring: pinned-to-bottom stays pinned as turns append; a user
// who scrolled up keeps their position. Appending never re-renders existing
// turns, so a playing audio tile survives (single appendChild, no
// replaceChildren on the live path).
function _appendJournalTurn(event) {
  const feed = document.getElementById("journalFeed");
  const pinned =
    feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 40;
  document.getElementById("journalFeedEmpty").hidden = true;
  feed.appendChild(_journalEventElement(event));
  if (pinned) feed.scrollTop = feed.scrollHeight;
}

function _renderJournalFeed(events, contextEventPosition = null) {
  const feed = document.getElementById("journalFeed");
  const empty = document.getElementById("journalFeedEmpty");
  // replaceChildren() detaches any playing tile, and a detached <audio>
  // keeps sounding - stop explicitly before the DOM swap.
  _stopJournalPlayback();
  _clearJournalContextHighlight();
  feed.replaceChildren();
  empty.hidden = events.length !== 0;
  empty.textContent = uiString("journal_empty_feed");
  for (const [position, event] of events.entries()) {
    feed.appendChild(_journalEventElement(event, position));
  }
  // Bound once (initContextMenuTrigger() is idempotent via its own
  // dataset flag): the container itself survives every replaceChildren(),
  // so this single delegated listener also covers messages appended later
  // by _appendJournalTurn() without needing to rebind per message.
  initContextMenuTrigger(feed, ".journal-msg", _journalMessageMenuEntries);
  // Bottom-anchored: the newest turn sits just above the reserved input
  // dock, messenger-style.
  feed.scrollTop = feed.scrollHeight;
  if (contextEventPosition !== null) {
    _highlightJournalContextEvent(contextEventPosition);
  }
}

// Image thumbnails load after the feed is rendered and have no reserved
// height, so each load grows scrollHeight and would leave the feed no
// longer pinned to the bottom. Re-anchor on load, but only when the view
// is still (near) the bottom - growth from the loaded image itself counts
// as "near", a user who deliberately scrolled further up must not be
// yanked back down.
function _reanchorJournalFeedAfterGrowth(growthPixels) {
  const feed = document.getElementById("journalFeed");
  const distanceFromBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight;
  if (distanceFromBottom <= growthPixels + 40) {
    feed.scrollTop = feed.scrollHeight;
  }
}

function _journalEventElement(event, position = null) {
  const message = document.createElement("div");
  message.className = "journal-msg";
  message.dataset.role = event.role;
  message.dataset.source = event.source;
  if (position !== null) message.dataset.eventPosition = String(position);

  const meta = document.createElement("div");
  meta.className = "journal-msg-meta";
  const source = document.createElement("span");
  source.className = "journal-msg-source";
  source.textContent = _journalSourceLabel(event.source);
  const time = document.createElement("span");
  time.textContent = _formatJournalTime(event.timestamp);
  meta.append(source, time);
  const metaSpacer = document.createElement("span");
  metaSpacer.className = "journal-msg-meta-spacer";
  meta.appendChild(metaSpacer);
  if (event.role === "assistant" && event.text) {
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "journal-copy";
    copy.title = uiString("journal_copy_answer");
    copy.appendChild(_icon("copy"));
    // task-ui-ux-5: the flash-to-"Copied" text lands on this label span,
    // not the button itself - flashing button.textContent would also wipe
    // the icon just appended above and never bring it back (textContent
    // read/write only sees flattened text, so "restoring the original"
    // afterward would restore flat text, permanently losing the icon).
    const copyLabel = document.createElement("span");
    copyLabel.textContent = uiString("journal_copy_answer");
    copy.appendChild(copyLabel);
    copy.addEventListener("click", () => copyJournalAnswer(event.text, copyLabel));
    meta.appendChild(copy);
  }
  // Play-from-here (story-v1.8.3): starts a sequence at this turn - an
  // assistant reply (re-synthesized) or a voice user turn (its own recording).
  // Only a known feed position (the full render, never a live append)
  // addresses a specific past turn, and the button doubles as the anchor the
  // now-playing highlight lands on as the sequence advances onto this row.
  if (position !== null && _journalEventIsPlayable(event)) {
    meta.appendChild(_journalReplayButton(_journalSelectedSessionId, position));
  }
  const menuButton = document.createElement("button");
  menuButton.type = "button";
  menuButton.className = "context-menu-button";
  menuButton.textContent = "...";
  menuButton.title = uiString("context_menu_open");
  menuButton.setAttribute("aria-label", uiString("context_menu_open"));
  menuButton.addEventListener("click", (clickEvent) => {
    clickEvent.stopPropagation();
    openItemContextMenu(message, menuButton, _journalMessageMenuEntries);
  });
  meta.appendChild(menuButton);
  message.appendChild(meta);

  for (const item of event.media || []) {
    message.appendChild(
      item.path.toLowerCase().endsWith(".wav")
        ? _journalAudioTile(item)
        : _journalImageThumbnail(item)
    );
  }
  if (event.text) {
    const text = document.createElement("div");
    text.className = "journal-msg-text";
    text.textContent = event.text;
    message.appendChild(text);
  }
  // Transcript controls only attach to a known event position (the full feed
  // render, never a live append whose position is not yet known) and only to
  // events carrying transcribable audio. Transcription is a deliberate
  // historical action on a past voice turn, never an implied background job.
  if (position !== null && _journalEventHasAudio(event)) {
    message.appendChild(_journalTranscriptPanel(event, position));
  }
  const provenanceDetail = _journalProvenanceDetail(event);
  if (provenanceDetail !== null) message.appendChild(provenanceDetail);
  const outcomeDetail = _journalOutcomeDetail(event);
  if (outcomeDetail !== null) message.appendChild(outcomeDetail);
  const spokenDerivativeDetail = _journalSpokenDerivativeDetail(event);
  if (spokenDerivativeDetail !== null) message.appendChild(spokenDerivativeDetail);
  return message;
}

function _journalEventHasAudio(event) {
  return (event.media || []).some((item) =>
    item.path.toLowerCase().endsWith(".wav")
  );
}

// A turn a play-from-here sequence can play (story-v1.8.3): an assistant reply
// with text (re-synthesized) or a voice user turn with a stored .wav (played
// directly). Typed-user and system turns are not playable.
function _journalEventIsPlayable(event) {
  if (event.role === "assistant") return Boolean(event.text);
  return (
    event.role === "user" &&
    event.source === "voice" &&
    _journalEventHasAudio(event)
  );
}

function _journalReplayButton(sessionId, position) {
  // Play on a reply plays it and every later reply in the session back to back
  // (story-v1.8.3 task 2), and a Pause<->Resume button shown only while a
  // sequence runs. The now-playing highlight (the Stop state + the Pause
  // button) is driven entirely by replay_progress deltas - see
  // applyReplayProgress - so it follows playback across rows rather than
  // sticking to the row that was clicked; the click only opens the held
  // sequence request. Session id and event position are stamped on both
  // controls so a progress delta can find the reply that is now playing.
  const fragment = document.createDocumentFragment();
  const pause = _journalReplayPauseButton();
  pause.dataset.sessionId = sessionId;
  pause.dataset.eventPosition = position;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "journal-replay";
  button.dataset.sessionId = sessionId;
  button.dataset.eventPosition = position;
  const label = document.createElement("span");
  button.appendChild(label);
  _setJournalReplayButtonState(button, label, false);
  button.addEventListener("click", () =>
    _toggleJournalReplay(sessionId, position, button)
  );

  fragment.appendChild(button);
  fragment.appendChild(pause);
  return fragment;
}

function _journalReplayPauseButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "journal-replay-pause";
  button.hidden = true;
  const label = document.createElement("span");
  button.appendChild(label);
  _setJournalReplayPauseState(button, label, false);
  button.addEventListener("click", () =>
    _toggleJournalReplayPause(button, label)
  );
  return button;
}

function _setJournalReplayButtonState(button, label, active) {
  button.dataset.active = active ? "true" : "false";
  const title = uiString(active ? "journal_replay_stop" : "journal_replay");
  button.title = title;
  button.setAttribute("aria-label", title);
  const existingIcon = button.querySelector(".icon");
  if (existingIcon) existingIcon.remove();
  button.prepend(_icon(active ? "stop" : "play"));
  label.textContent = title;
}

function _setJournalReplayPauseState(button, label, paused) {
  button.dataset.paused = paused ? "true" : "false";
  const title = uiString(
    paused ? "journal_replay_resume" : "journal_replay_pause"
  );
  button.title = title;
  button.setAttribute("aria-label", title);
  const existingIcon = button.querySelector(".icon");
  if (existingIcon) existingIcon.remove();
  button.prepend(_icon(paused ? "play" : "pause"));
  label.textContent = title;
}

// Pause/resume are signals that do NOT resolve the held replay fetch (unlike
// Stop): the replay stays running, suspended at its playback position, so the
// Play<->Stop toggle above is untouched here.
async function _toggleJournalReplayPause(button, label) {
  const paused = button.dataset.paused === "true";
  const url = _journalUrl(
    paused
      ? "/api/journal/replies/replay/resume"
      : "/api/journal/replies/replay/pause"
  );
  if (url === null) return;
  try {
    const response = await fetch(url, { method: "POST" });
    const body = await response.json();
    // Flip only when the server confirms it actually (un)paused a clip.
    // pause()/resume() return false when there was nothing to act on (the
    // replay already ended, or a momentary gap between segments); trusting
    // the fetch alone would leave the button showing Resume while audio
    // keeps playing - a state that lies about what is happening.
    const changed = paused ? body.resumed === true : body.paused === true;
    if (changed) _setJournalReplayPauseState(button, label, !paused);
  } catch (error) {
    /* leave the button state unchanged on failure */
  }
}

// The Play POST is held open by the server for the whole sequence (see the
// transport handler): it resolves only when playback ends - by finishing, by
// Stop, by a new live turn, by Ctrl+Alt+I, or by TTS being disabled. The
// button's visible state is NOT derived from this promise: replay_progress
// deltas move the now-playing highlight across rows (applyReplayProgress),
// and the server's final clear delta - plus this promise's end as a
// belt-and-suspenders - reset it. A busy press (a sequence already running)
// is rejected by the core with its own beep + error; the UI keeps no busy
// check of its own.
async function _toggleJournalReplay(sessionId, position, button) {
  if (button.dataset.active === "true") {
    const stopUrl = _journalUrl("/api/journal/replies/replay/stop");
    if (stopUrl !== null) {
      try {
        await fetch(stopUrl, { method: "POST" });
      } catch (error) {
        /* the clear progress delta still resets the highlight */
      }
    }
    return;
  }
  const url = _journalUrl(
    "/api/journal/replies/" +
      encodeURIComponent(sessionId) +
      "/" +
      position +
      "/replay-sequence"
  );
  if (url === null) return;
  try {
    await fetch(url, { method: "POST" });
  } catch (error) {
    /* the clear progress delta resets the highlight; nothing to do here */
  } finally {
    _clearReplayProgress();
  }
}

// replay_progress delta: the sequence advanced to a new reply (value carries
// its session_id + event_position) or ended (value is null). Move the
// now-playing highlight - the Stop state and the Pause button - onto that
// reply's row, or clear it. Stop/Pause act on the shared player, so it does
// not matter which row shows them; the highlight only tells the user which
// block is playing now (story-v1.8.3 task 2).
function applyReplayProgress(value) {
  _clearReplayProgress();
  if (!value) return;
  const selector =
    '[data-session-id="' +
    CSS.escape(value.session_id) +
    '"][data-event-position="' +
    CSS.escape(String(value.event_position)) +
    '"]';
  const button = document.querySelector(".journal-replay" + selector);
  if (button) {
    _setJournalReplayButtonState(button, button.querySelector("span"), true);
  }
  const pause = document.querySelector(".journal-replay-pause" + selector);
  if (pause) {
    _setJournalReplayPauseState(pause, pause.querySelector("span"), false);
    pause.hidden = false;
  }
}

function _clearReplayProgress() {
  document
    .querySelectorAll('.journal-replay[data-active="true"]')
    .forEach((button) =>
      _setJournalReplayButtonState(button, button.querySelector("span"), false)
    );
  document.querySelectorAll(".journal-replay-pause").forEach((pause) => {
    _setJournalReplayPauseState(pause, pause.querySelector("span"), false);
    pause.hidden = true;
  });
}

// Reuses each existing per-message action verbatim - .click() on the same
// button its own visible control already wires - rather than duplicating
// their fetch/error/refs handling here. Generate transcript and Generate
// annotation only appear when the message actually carries that control
// (an audio turn for transcript; a known feed position, set only by the
// full render and never a live append, for annotation - see the "known
// event position" comment above _journalTranscriptPanel's call site).
function _journalMessageMenuEntries(row) {
  const copyButton = row.querySelector(".journal-copy");
  const transcriptGenerate = row.querySelector(".journal-transcript-generate");
  const replayButton = row.querySelector(".journal-replay");
  const pauseButton = row.querySelector(".journal-replay-pause");
  const position = row.dataset.eventPosition;
  return [
    copyButton && {
      label: uiString("journal_copy_answer"),
      icon: _icon("copy"),
      run: () => copyButton.click(),
    },
    replayButton && {
      label: uiString(
        replayButton.dataset.active === "true"
          ? "journal_replay_stop"
          : "journal_replay"
      ),
      icon: _icon(replayButton.dataset.active === "true" ? "stop" : "play"),
      run: () => replayButton.click(),
    },
    pauseButton &&
      !pauseButton.hidden && {
        label: uiString(
          pauseButton.dataset.paused === "true"
            ? "journal_replay_resume"
            : "journal_replay_pause"
        ),
        icon: _icon(pauseButton.dataset.paused === "true" ? "play" : "pause"),
        run: () => pauseButton.click(),
      },
    transcriptGenerate && {
      label: uiString("journal_transcript_generate"),
      run: () => transcriptGenerate.click(),
      disabled: transcriptGenerate.disabled,
    },
    position !== undefined && {
      label: uiString("journal_annotation_generate_message"),
      run: () => _generateJournalAnnotationForMessage(Number(position)),
    },
  ];
}

// Composes two already-existing actions (open the panel, generate for an
// explicit range) rather than adding a new endpoint: a single message's
// own position as both the start and end of the existing range-generate
// call is just a one-event range, the same request shape
// generateJournalAnnotationRange() already sends by hand from the panel's
// From/To inputs.
async function _generateJournalAnnotationForMessage(position) {
  if (!_journalAnnotationOpen) await toggleJournalAnnotationPanel();
  await _generateJournalAnnotation(position, position);
}

// Derived transcript overlay controls for one voice event (task-v1.8.0-20).
// The panel reads and edits the derived overlay only; it never rewrites the
// raw journal event, and generation runs the explicit, user-invoked
// transcription endpoint - there is no automatic background transcription.
function _journalTranscriptPanel(event, position) {
  const panel = document.createElement("div");
  panel.className = "journal-transcript";
  panel.dataset.eventPosition = String(position);

  const head = document.createElement("div");
  head.className = "journal-transcript-head";
  const title = document.createElement("span");
  title.className = "journal-transcript-title";
  title.textContent = uiString("journal_transcript_title");
  const status = document.createElement("span");
  status.className = "journal-transcript-status";
  head.append(title, status);

  const textarea = document.createElement("textarea");
  textarea.className = "journal-transcript-text";
  textarea.rows = 5;
  textarea.placeholder = uiString("journal_transcript_edit_placeholder");

  const actions = document.createElement("div");
  actions.className = "journal-transcript-actions";
  const generate = document.createElement("button");
  generate.type = "button";
  generate.className = "journal-transcript-generate";
  generate.textContent = uiString("journal_transcript_generate");
  const save = document.createElement("button");
  save.type = "button";
  save.className = "journal-transcript-save";
  save.textContent = uiString("journal_transcript_save");
  actions.append(generate, save);

  const message = document.createElement("div");
  message.className = "journal-transcript-message";
  message.setAttribute("role", "status");

  panel.append(head, textarea, actions, message);
  enableStandaloneF2Edit(panel);

  const refs = { panel, status, textarea, generate, save, message };
  generate.addEventListener("click", () =>
    generateJournalTranscript(event.session_id, position, refs)
  );
  save.addEventListener("click", () =>
    saveJournalTranscript(event.session_id, position, refs)
  );
  _loadJournalTranscript(event.session_id, position, refs);
  return panel;
}

function _journalTranscriptStatusLabel(source) {
  if (source === "generated") return uiString("journal_transcript_generated");
  if (source === "edited") return uiString("journal_transcript_edited");
  return uiString("journal_transcript_none");
}

function _applyJournalTranscriptRead(refs, payload) {
  const transcript = payload && payload.transcript;
  if (payload && payload.found && transcript) {
    refs.textarea.value = transcript.text;
    refs.status.textContent = _journalTranscriptStatusLabel(transcript.source);
  } else {
    refs.textarea.value = "";
    refs.status.textContent = uiString("journal_transcript_none");
  }
}

async function _loadJournalTranscript(sessionId, position, refs) {
  const url = _journalTranscriptUrl(sessionId, position);
  if (url === null) {
    refs.status.textContent = uiString("transport_no_token");
    return;
  }
  try {
    const response = await fetch(url);
    const payload = await response.json();
    if (payload.status === "hidden") return;
    _applyJournalTranscriptRead(refs, payload);
  } catch (error) {
    console.error("Transcript load failed:", error);
    refs.status.textContent = uiString("journal_transcript_load_failed");
  }
}

async function saveJournalTranscript(sessionId, position, refs) {
  const text = refs.textarea.value.trim();
  if (!text) {
    refs.message.textContent = uiString("journal_transcript_empty");
    return;
  }
  const url = _journalTranscriptUrl(sessionId, position);
  if (url === null) {
    refs.message.textContent = uiString("transport_no_token");
    return;
  }
  refs.save.disabled = true;
  try {
    const response = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const payload = await response.json();
    if (payload.status === "ok") {
      _applyJournalTranscriptRead(refs, payload);
      refs.message.textContent = uiString("journal_transcript_saved");
      return;
    }
    refs.message.textContent = _journalTranscriptSaveError(payload);
  } catch (error) {
    console.error("Transcript save failed:", error);
    refs.message.textContent = uiString("journal_transcript_save_failed");
  } finally {
    refs.save.disabled = false;
  }
}

function _journalTranscriptSaveError(payload) {
  if (payload.reason === "text_empty") {
    return uiString("journal_transcript_empty");
  }
  if (payload.reason === "text_too_long") {
    return uiString("journal_transcript_over_limit").replace(
      "{max}",
      String(payload.max_chars)
    );
  }
  return uiString("journal_transcript_save_failed");
}

async function generateJournalTranscript(sessionId, position, refs) {
  const url = _journalTranscriptUrl(sessionId, position, "/generate");
  if (url === null) {
    refs.message.textContent = uiString("transport_no_token");
    return;
  }
  refs.generate.disabled = true;
  refs.save.disabled = true;
  refs.message.textContent = uiString("journal_transcript_generating");
  try {
    const response = await fetch(url, { method: "POST" });
    const payload = await response.json();
    if (payload.status === "ok") {
      refs.textarea.value = payload.transcript || "";
      refs.status.textContent = uiString("journal_transcript_generated");
      refs.message.textContent = "";
      return;
    }
    refs.message.textContent = _journalTranscriptGenerateError(payload);
  } catch (error) {
    console.error("Transcript generation failed:", error);
    refs.message.textContent = uiString("journal_transcript_generate_failed");
  } finally {
    refs.generate.disabled = false;
    refs.save.disabled = false;
  }
}

function _journalTranscriptGenerateError(payload) {
  if (payload && payload.reason === "no_audio_media") {
    return uiString("journal_transcript_generate_no_audio");
  }
  return uiString("journal_transcript_generate_failed");
}

function _journalTranscriptUrl(sessionId, position, suffix = "") {
  return _journalUrl(
    "/api/journal/transcripts/" +
      encodeURIComponent(sessionId) +
      "/" +
      encodeURIComponent(String(position)) +
      suffix
  );
}

// Derived annotation overlay panel for the selected session (task v1.8.0-23
// slice 4). Annotations are optional, source-grounded notes over a whole
// session or an explicit event range - a summary, never the original
// conversation, which is why the panel note says so explicitly and every
// card shows its target and source instead of presenting the text as a raw
// turn. The panel is session-scoped (unlike Memory's two fixed files): it
// loads for _journalSelectedSessionId when opened and reloads whenever the
// selected session changes while it stays open.
let _journalAnnotationOpen = false;
// Bumped at the start of every _loadJournalAnnotations() call and captured
// locally, so a response is applied only if no newer load has started since -
// otherwise an older, slower load (e.g. the panel's own open-load) could
// resolve after a newer one (e.g. the post-generate reload) and overwrite the
// freshly generated list with the stale one. _journalContentGeneration alone
// does not catch this: both loads target the same session and generation.
let _journalAnnotationLoadToken = 0;
let _journalAnnotationGenerateInFlight = false;
// Bumped whenever a generate call starts or the panel is cleared (Hidden), and
// captured locally by each _generateJournalAnnotation() call. Clearing while a
// generate is in flight resets the flag/buttons immediately so a reopened
// panel is not stuck disabled, but the abandoned fetch is still running
// server-side; without this token its late completion would reach the same
// finally block and clobber the flag/buttons/message a newer, still-running
// generate call owns. Only a completion whose captured token still matches
// the current one may touch that shared state.
let _journalAnnotationGenerateToken = 0;

async function toggleJournalAnnotationPanel() {
  if (_isHiddenActive()) {
    _setJournalInputStatus(uiString("journal_annotation_hidden"));
    return;
  }
  _journalAnnotationOpen = !_journalAnnotationOpen;
  document.getElementById("journalAnnotationPanel").hidden = !_journalAnnotationOpen;
  document.querySelector("#journalAnnotationToggle .toggle-label").textContent = uiString(
    _journalAnnotationOpen ? "journal_annotation_close" : "journal_annotation_open");
  if (_journalAnnotationOpen) await _loadJournalAnnotations(_journalSelectedSessionId);
}

function _clearJournalAnnotationPanel() {
  _journalAnnotationOpen = false;
  _journalAnnotationLoadToken += 1;
  _journalAnnotationGenerateInFlight = false;
  _journalAnnotationGenerateToken += 1;
  const panel = document.getElementById("journalAnnotationPanel");
  if (panel) panel.hidden = true;
  const toggleLabel = document.querySelector("#journalAnnotationToggle .toggle-label");
  if (toggleLabel) toggleLabel.textContent = uiString("journal_annotation_open");
  const list = document.getElementById("journalAnnotationList");
  if (list) list.replaceChildren();
  const message = document.getElementById("journalAnnotationMessage");
  if (message) message.textContent = "";
  _setJournalAnnotationGenerateButtonsDisabled(false);
}

// Called after selectJournalSession() settles so an already-open panel
// follows the session switch instead of showing the previous session's
// annotations.
function _reloadJournalAnnotationsIfOpen(sessionId) {
  if (!_journalAnnotationOpen) return;
  _loadJournalAnnotations(sessionId);
}

async function _loadJournalAnnotations(sessionId) {
  const list = document.getElementById("journalAnnotationList");
  const empty = document.getElementById("journalAnnotationEmpty");
  const message = document.getElementById("journalAnnotationMessage");
  _journalAnnotationLoadToken += 1;
  const token = _journalAnnotationLoadToken;
  if (sessionId === null) {
    list.replaceChildren();
    empty.hidden = false;
    return;
  }
  const generation = _journalContentGeneration;
  const payload = await _fetchJournalJson(
    "/api/journal/annotations/" + encodeURIComponent(sessionId));
  // A slow response for a session the user has navigated away from (or that
  // Hidden invalidated) must not overwrite the panel; the token check also
  // rejects an older overlapping load for the same session/generation
  // finishing after a newer one (e.g. the panel's open-load racing a
  // post-generate reload) so it cannot clobber the fresher list.
  if (
    generation !== _journalContentGeneration ||
    _journalSelectedSessionId !== sessionId ||
    token !== _journalAnnotationLoadToken
  ) {
    return;
  }
  if (!payload) {
    message.textContent = uiString("journal_annotation_load_failed");
    return;
  }
  message.textContent = "";
  const annotations = payload.annotations || [];
  list.replaceChildren();
  empty.hidden = annotations.length !== 0;
  for (const annotation of annotations) {
    list.appendChild(_journalAnnotationElement(annotation));
  }
  initRovingList(list, ".journal-annotation", {
    getLabel: (card) => card.querySelector(".journal-annotation-target")?.textContent || "",
  });
}

function _journalAnnotationElement(annotation) {
  const card = document.createElement("section");
  card.tabIndex = -1; // roving tabindex, set by initRovingList() above
  card.className = "journal-annotation";
  card.dataset.annotationId = annotation.annotation_id;

  const head = document.createElement("div");
  head.className = "journal-annotation-card-head";
  const target = document.createElement("button");
  target.type = "button";
  target.className = "journal-annotation-target";
  target.textContent = _journalAnnotationTargetLabel(annotation.target);
  if (annotation.target.start_position === null) {
    target.disabled = true;
  } else {
    target.addEventListener("click", () =>
      _highlightJournalContextEvent(annotation.target.start_position));
  }
  const source = document.createElement("span");
  source.className = "journal-annotation-source";
  source.textContent = _journalAnnotationSourceLabel(annotation);
  head.append(target, source);

  const textarea = document.createElement("textarea");
  textarea.className = "journal-annotation-text";
  textarea.rows = 4;
  textarea.value = annotation.text;
  textarea.placeholder = uiString("journal_annotation_edit_placeholder");

  const footer = document.createElement("div");
  footer.className = "journal-annotation-footer";
  const save = document.createElement("button");
  save.type = "button";
  save.className = "journal-annotation-save";
  save.textContent = uiString("journal_annotation_save");
  const status = document.createElement("span");
  status.className = "journal-annotation-status";
  footer.append(save, status);

  card.append(head, textarea, footer);

  const refs = { card, source, textarea, save, status };
  save.addEventListener("click", () =>
    saveJournalAnnotation(annotation.target.session_id, annotation.annotation_id, refs));
  return card;
}

function _journalAnnotationTargetLabel(target) {
  if (target.start_position === null || target.end_position === null) {
    return uiString("journal_annotation_target_session");
  }
  return uiString("journal_annotation_target_range")
    .replace("{start}", String(target.start_position))
    .replace("{end}", String(target.end_position));
}

function _journalAnnotationSourceLabel(annotation) {
  const key = annotation.source === "edited"
    ? "journal_annotation_source_edited"
    : "journal_annotation_source_generated";
  const label = uiString(key);
  return annotation.status === "dismissed"
    ? label + " " + uiString("journal_annotation_status_dismissed")
    : label;
}

async function saveJournalAnnotation(sessionId, annotationId, refs) {
  const text = refs.textarea.value.trim();
  if (!text) {
    refs.status.textContent = uiString("journal_annotation_text_empty");
    return;
  }
  const url = _journalAnnotationUrl(sessionId, annotationId);
  if (url === null) {
    refs.status.textContent = uiString("transport_no_token");
    return;
  }
  refs.save.disabled = true;
  try {
    const response = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const payload = await response.json();
    if (payload.status === "ok") {
      refs.textarea.value = payload.annotation.text;
      refs.source.textContent = _journalAnnotationSourceLabel(payload.annotation);
      refs.status.textContent = uiString("journal_annotation_saved");
      return;
    }
    refs.status.textContent = _journalAnnotationSaveError(payload);
  } catch (error) {
    console.error("Annotation save failed:", error);
    refs.status.textContent = uiString("journal_annotation_save_failed");
  } finally {
    refs.save.disabled = false;
  }
}

function _journalAnnotationSaveError(payload) {
  if (payload.reason === "text_empty") {
    return uiString("journal_annotation_text_empty");
  }
  if (payload.reason === "text_too_long") {
    return uiString("journal_annotation_over_limit").replace(
      "{max}",
      String(payload.max_chars)
    );
  }
  return uiString("journal_annotation_save_failed");
}

async function generateJournalAnnotationSession() {
  await _generateJournalAnnotation(null, null);
}

function generateJournalAnnotationRange() {
  const start = _parseJournalAnnotationRangeInput(
    document.getElementById("journalAnnotationRangeStart").value);
  const end = _parseJournalAnnotationRangeInput(
    document.getElementById("journalAnnotationRangeEnd").value);
  if (start === null || end === null || start > end) {
    document.getElementById("journalAnnotationMessage").textContent = uiString(
      "journal_annotation_range_invalid");
    return;
  }
  _generateJournalAnnotation(start, end);
}

function _parseJournalAnnotationRangeInput(value) {
  if (value === "") return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

async function _generateJournalAnnotation(start, end) {
  const sessionId = _journalSelectedSessionId;
  const message = document.getElementById("journalAnnotationMessage");
  if (sessionId === null) return;
  const url = _journalAnnotationUrl(sessionId, null, "generate");
  if (url === null) {
    message.textContent = uiString("transport_no_token");
    return;
  }
  if (_journalAnnotationGenerateInFlight) return;
  _journalAnnotationGenerateInFlight = true;
  _journalAnnotationGenerateToken += 1;
  const token = _journalAnnotationGenerateToken;
  _setJournalAnnotationGenerateButtonsDisabled(true);
  message.textContent = uiString("journal_annotation_generating");
  try {
    const hasRange = start !== null;
    const response = await fetch(url, {
      method: "POST",
      headers: hasRange ? { "Content-Type": "application/json" } : {},
      body: hasRange
        ? JSON.stringify({ start_position: start, end_position: end })
        : undefined,
    });
    const payload = await response.json();
    // A stale response - the panel was cleared (Hidden) and a newer generate
    // call now owns the flag/buttons/message - must not touch any of them.
    if (token !== _journalAnnotationGenerateToken) return;
    if (payload.status === "ok") {
      message.textContent = "";
      await _loadJournalAnnotations(sessionId);
      return;
    }
    message.textContent = _journalAnnotationGenerateError(payload);
  } catch (error) {
    console.error("Annotation generation failed:", error);
    if (token === _journalAnnotationGenerateToken) {
      message.textContent = uiString("journal_annotation_generate_failed");
    }
  } finally {
    if (token === _journalAnnotationGenerateToken) {
      _journalAnnotationGenerateInFlight = false;
      _setJournalAnnotationGenerateButtonsDisabled(false);
    }
  }
}

function _setJournalAnnotationGenerateButtonsDisabled(disabled) {
  const sessionButton = document.getElementById("journalAnnotationGenerateSession");
  const rangeButton = document.getElementById("journalAnnotationGenerateRange");
  if (sessionButton) sessionButton.disabled = disabled;
  if (rangeButton) rangeButton.disabled = disabled;
}

function _journalAnnotationGenerateError(payload) {
  if (payload && payload.reason === "unknown_range") {
    return uiString("journal_annotation_generate_unknown_range");
  }
  if (
    payload &&
    (payload.reason === "source_too_large" || payload.reason === "source_text_too_large")
  ) {
    return uiString("journal_annotation_generate_too_large");
  }
  return uiString("journal_annotation_generate_failed");
}

function _journalAnnotationUrl(sessionId, annotationId, suffix = "") {
  let path = "/api/journal/annotations/" + encodeURIComponent(sessionId);
  if (annotationId !== null) path += "/" + encodeURIComponent(annotationId);
  if (suffix) path += "/" + suffix;
  return _journalUrl(path);
}

// Derived far-consolidation dry-run/execute panel for the selected session
// (task v1.8.0-25). Unlike Annotations, this panel never edits text - it only
// previews (GET, no I/O side effect) and, on explicit confirm, executes the
// one destructive action anywhere in the Journal surface: removing audio
// files that already have a transcript. Session-scoped like Annotations,
// with the same load-token guard against out-of-order responses and the same
// in-flight-call token guard for the one action button, both carried over
// from the annotation panel's own fixes rather than re-discovered here.
let _journalConsolidationOpen = false;
let _journalConsolidationLoadToken = 0;
let _journalConsolidationExecuteInFlight = false;
let _journalConsolidationExecuteToken = 0;
let _journalConsolidationRemovableCount = 0;

async function toggleJournalConsolidationPanel() {
  if (_isHiddenActive()) {
    _setJournalInputStatus(uiString("journal_consolidation_hidden"));
    return;
  }
  _journalConsolidationOpen = !_journalConsolidationOpen;
  document.getElementById("journalConsolidationPanel").hidden =
    !_journalConsolidationOpen;
  document.querySelector("#journalConsolidationToggle .toggle-label").textContent = uiString(
    _journalConsolidationOpen
      ? "journal_consolidation_close"
      : "journal_consolidation_open");
  if (_journalConsolidationOpen) {
    await _loadJournalConsolidation(_journalSelectedSessionId);
  }
}

function _clearJournalConsolidationPanel() {
  _journalConsolidationOpen = false;
  _journalConsolidationLoadToken += 1;
  _journalConsolidationExecuteInFlight = false;
  _journalConsolidationExecuteToken += 1;
  _journalConsolidationRemovableCount = 0;
  const panel = document.getElementById("journalConsolidationPanel");
  if (panel) panel.hidden = true;
  const toggleLabel = document.querySelector("#journalConsolidationToggle .toggle-label");
  if (toggleLabel) toggleLabel.textContent = uiString("journal_consolidation_open");
  const summary = document.getElementById("journalConsolidationSummary");
  if (summary) summary.textContent = "";
  const list = document.getElementById("journalConsolidationMediaList");
  if (list) list.replaceChildren();
  const lastRun = document.getElementById("journalConsolidationLastRun");
  if (lastRun) lastRun.textContent = "";
  const message = document.getElementById("journalConsolidationMessage");
  if (message) message.textContent = "";
  _setJournalConsolidationExecuteDisabled(true);
}

// Called after selectJournalSession() settles so an already-open panel
// follows the session switch instead of showing the previous session's plan.
function _reloadJournalConsolidationIfOpen(sessionId) {
  if (!_journalConsolidationOpen) return;
  _loadJournalConsolidation(sessionId);
}

async function _loadJournalConsolidation(sessionId) {
  const list = document.getElementById("journalConsolidationMediaList");
  const message = document.getElementById("journalConsolidationMessage");
  _journalConsolidationLoadToken += 1;
  const token = _journalConsolidationLoadToken;
  if (sessionId === null) {
    document.getElementById("journalConsolidationSummary").textContent = "";
    list.replaceChildren();
    document.getElementById("journalConsolidationLastRun").textContent = "";
    _journalConsolidationRemovableCount = 0;
    _setJournalConsolidationExecuteDisabled(true);
    return;
  }
  const generation = _journalContentGeneration;
  const base = "/api/journal/consolidation/" + encodeURIComponent(sessionId);
  const [planPayload, statusPayload] = await Promise.all([
    _fetchJournalJson(base),
    _fetchJournalJson(base + "/status"),
  ]);
  // Same out-of-order guard as annotations: an older overlapping load (the
  // panel's own open-load racing a post-execute reload, or a session switch
  // mid-flight) must not overwrite what a newer load already rendered.
  if (
    generation !== _journalContentGeneration ||
    _journalSelectedSessionId !== sessionId ||
    token !== _journalConsolidationLoadToken
  ) {
    return;
  }
  if (!planPayload) {
    message.textContent = uiString("journal_consolidation_load_failed");
    _setJournalConsolidationExecuteDisabled(true);
    return;
  }
  message.textContent = "";
  _renderJournalConsolidationPlan(planPayload.plan);
  _renderJournalConsolidationLastRun(statusPayload ? statusPayload.run : null);
}

function _renderJournalConsolidationPlan(plan) {
  const summary = document.getElementById("journalConsolidationSummary");
  const list = document.getElementById("journalConsolidationMediaList");
  list.replaceChildren();

  if (plan.plan_status === "active_session") {
    summary.textContent = uiString("journal_consolidation_active_session");
    _journalConsolidationRemovableCount = 0;
    _setJournalConsolidationExecuteDisabled(true);
    return;
  }
  if (plan.plan_status === "unknown_session") {
    summary.textContent = uiString("journal_consolidation_unknown_session");
    _journalConsolidationRemovableCount = 0;
    _setJournalConsolidationExecuteDisabled(true);
    return;
  }

  summary.textContent = uiString("journal_consolidation_summary")
    .replace("{events}", String(plan.event_count))
    .replace("{annotations}", String(plan.annotation_count))
    .replace("{removable}", String(plan.removable_count));
  for (const item of plan.media_items) {
    list.appendChild(_journalConsolidationMediaElement(item));
  }
  _journalConsolidationRemovableCount = plan.removable_count;
  _setJournalConsolidationExecuteDisabled(plan.removable_count === 0);
}

function _journalConsolidationMediaElement(item) {
  const row = document.createElement("div");
  row.className = "journal-consolidation-media-item";
  const media = document.createElement("span");
  media.className = "journal-consolidation-media-name";
  media.textContent = item.media;
  const action = document.createElement("span");
  action.className =
    "journal-consolidation-media-action journal-consolidation-media-action-" +
    item.action;
  action.textContent = uiString(
    item.action === "remove"
      ? "journal_consolidation_action_remove"
      : "journal_consolidation_action_keep");
  const reason = document.createElement("span");
  reason.className = "journal-consolidation-media-reason";
  reason.textContent = uiString("journal_consolidation_reason_" + item.reason);
  row.append(media, action, reason);
  return row;
}

function _renderJournalConsolidationLastRun(run) {
  const lastRun = document.getElementById("journalConsolidationLastRun");
  if (!run) {
    lastRun.textContent = uiString("journal_consolidation_no_prior_run");
    return;
  }
  const statusKey =
    run.status === "completed"
      ? "journal_consolidation_run_completed"
      : "journal_consolidation_run_partial_failure";
  lastRun.textContent = uiString(statusKey)
    .replace("{removed}", String(run.removed_count))
    .replace("{failed}", String(run.failed_count))
    .replace("{bytes}", String(run.bytes_reclaimed));
}

async function executeJournalConsolidation() {
  const sessionId = _journalSelectedSessionId;
  const message = document.getElementById("journalConsolidationMessage");
  if (sessionId === null || _journalConsolidationExecuteInFlight) return;
  if (
    !window.confirm(
      uiString("journal_consolidation_confirm").replace(
        "{count}", String(_journalConsolidationRemovableCount)))
  ) {
    return;
  }
  const url = _journalUrl(
    "/api/journal/consolidation/" + encodeURIComponent(sessionId) + "/execute");
  if (url === null) {
    message.textContent = uiString("transport_no_token");
    return;
  }
  _journalConsolidationExecuteInFlight = true;
  _journalConsolidationExecuteToken += 1;
  const token = _journalConsolidationExecuteToken;
  _setJournalConsolidationExecuteDisabled(true);
  message.textContent = uiString("journal_consolidation_executing");
  try {
    const response = await fetch(url, { method: "POST" });
    const payload = await response.json();
    // A stale response - the panel was cleared (Hidden) and a newer execute
    // call now owns the flag/buttons/message - must not touch any of them.
    if (token !== _journalConsolidationExecuteToken) return;
    if (payload.status !== "ok") {
      message.textContent = uiString("journal_consolidation_execute_failed");
      return;
    }
    message.textContent = "";
    await _loadJournalConsolidation(sessionId);
  } catch (error) {
    console.error("Consolidation execute failed:", error);
    if (token === _journalConsolidationExecuteToken) {
      message.textContent = uiString("journal_consolidation_execute_failed");
    }
  } finally {
    if (token === _journalConsolidationExecuteToken) {
      _journalConsolidationExecuteInFlight = false;
      _setJournalConsolidationExecuteDisabled(
        _journalConsolidationRemovableCount === 0);
    }
  }
}

function _setJournalConsolidationExecuteDisabled(disabled) {
  const button = document.getElementById("journalConsolidationExecute");
  if (button) button.disabled = disabled;
}

function _journalProvenanceDetail(event) {
  if (event.source !== "fork" || !event.metadata || !event.metadata.seed) {
    return null;
  }
  const seed = event.metadata.seed;
  if (!seed.truncated && !seed.dropped_turns) return null;
  const detail = document.createElement("div");
  detail.className = "journal-provenance-detail";
  detail.textContent = uiString("journal_fork_truncated").replace(
    "{count}", String(seed.dropped_turns || 0));
  return detail;
}

// task-v1.7.0-3: an assistant entry that never got a normal completed
// answer (hotkey interrupt or a hard backend failure) is tagged
// event.metadata.outcome by JournalRecorder.record_assistant() - shown the
// same way fork's seed-truncation note is, so it reads as an explicit
// recorded outcome rather than a silently unanswered turn.
function _journalOutcomeDetail(event) {
  if (event.role !== "assistant" || !event.metadata || !event.metadata.outcome) {
    return null;
  }
  const key = "journal_outcome_" + event.metadata.outcome;
  const detail = document.createElement("div");
  detail.className = "journal-provenance-detail";
  detail.textContent = uiString(key);
  return detail;
}

// story-v1.9.0 task 3: mode 3's second pass attaches its spoken derivative
// to the SAME assistant JournalEvent as the canonical reply (metadata,
// additive, no second turn - see JournalRecorder.record_assistant()), so
// it renders here the same way, always collapsed by default per the
// story's own "collapsed block under the reply" requirement - <details>
// gives that for free with no click-handler bookkeeping of our own.
function _journalSpokenDerivativeDetail(event) {
  if (
    event.role !== "assistant" ||
    !event.metadata ||
    event.metadata.spoken_derivative === undefined
  ) {
    return null;
  }
  const detail = document.createElement("details");
  detail.className = "journal-spoken-derivative";
  const summary = document.createElement("summary");
  summary.textContent = uiString("journal_spoken_derivative_label");
  detail.appendChild(summary);
  const text = document.createElement("div");
  text.className = "journal-spoken-derivative-text";
  text.textContent = event.metadata.spoken_derivative;
  detail.appendChild(text);
  if (event.metadata.spoken_derivative_interrupted) {
    const note = document.createElement("div");
    note.className = "journal-provenance-detail";
    note.textContent = uiString("journal_spoken_derivative_interrupted");
    detail.appendChild(note);
  }
  return detail;
}

function _journalSourceLabel(source) {
  const key = "journal_source_" + source;
  const catalog = UI_STRINGS[currentUiLanguage()] || UI_STRINGS[DEFAULT_UI_LANGUAGE];
  // The event source is an open set by design (story-v1.5.0: later
  // sources must not require a format change), so an unknown source
  // renders as-is instead of throwing.
  return Object.prototype.hasOwnProperty.call(catalog, key) ? uiString(key) : source;
}

// task-journal-06: playback. One tile plays at a time - starting a tile
// pauses the previous one; Hidden and any feed re-render stop playback via
// _stopJournalPlayback() (a detached <audio> would keep sounding). The tile
// keeps the task-journal-05 flat layout so the v1.5.1+ right-click menu
// attaches without re-layout. Playback uses the plain HTML5 <audio> element
// against the task-journal-04 media endpoint - no player library, no
// file:// access.
let _journalActiveAudio = null;

function _stopJournalPlayback() {
  if (_journalActiveAudio === null) return;
  _journalActiveAudio.pause();
  _journalActiveAudio = null;
}

// The tile UI (button glyph, progress fill) only ever changes from the
// audio element's own play/pause/timeupdate events, never optimistically
// from the click handler - same "the UI shows confirmed state" shape as
// the engine-driven controls above.
function _journalAudioTile(mediaItem) {
  const tile = document.createElement("div");
  tile.className = "journal-audio-tile";

  const audio = document.createElement("audio");
  audio.preload = "metadata";
  audio.src = mediaItem.url;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "journal-audio-play";
  button.textContent = "▶";
  button.title = uiString("journal_audio_play");

  const progress = document.createElement("div");
  progress.className = "journal-audio-progress";
  const fill = document.createElement("div");
  fill.className = "journal-audio-progress-fill";
  progress.appendChild(fill);

  const duration = document.createElement("span");
  duration.className = "journal-audio-duration";
  duration.textContent = "--:--";
  audio.addEventListener("loadedmetadata", () => {
    duration.textContent = _formatJournalSeconds(audio.duration);
  });

  const name = document.createElement("span");
  name.className = "journal-audio-name";
  name.textContent = mediaItem.path.split("/").pop();

  button.addEventListener("click", () => _toggleJournalPlayback(audio));
  audio.addEventListener("play", () => {
    tile.dataset.playing = "true";
    button.textContent = "⏸";
    button.title = uiString("journal_audio_pause");
  });
  // Shared paused-state updater (review P1): pause and natural end must
  // both release the single-playback slot and return the button to the
  // play glyph - relying on browsers to always emit pause on ended left
  // the tile stuck in "active" and the next click paused instead of
  // replaying.
  const showPaused = () => {
    tile.dataset.playing = "false";
    button.textContent = "▶";
    button.title = uiString("journal_audio_play");
    if (_journalActiveAudio === audio) _journalActiveAudio = null;
  };
  audio.addEventListener("pause", showPaused);
  audio.addEventListener("timeupdate", () => {
    const ratio = audio.duration > 0 ? audio.currentTime / audio.duration : 0;
    fill.style.width = (ratio * 100).toFixed(1) + "%";
    duration.textContent = _formatJournalSeconds(
      audio.paused && audio.currentTime === 0 ? audio.duration : audio.currentTime);
  });
  audio.addEventListener("ended", () => {
    showPaused();
    audio.currentTime = 0;
    fill.style.width = "0%";
    duration.textContent = _formatJournalSeconds(audio.duration);
  });

  tile.append(button, progress, duration, name, audio);
  return tile;
}

function _toggleJournalPlayback(audio) {
  if (_journalActiveAudio === audio) {
    audio.pause();
    return;
  }
  // Single-playback invariant: pausing the previous tile before starting
  // this one (its pause listener clears _journalActiveAudio).
  _stopJournalPlayback();
  _journalActiveAudio = audio;
  audio.play().catch((error) => {
    console.error("Journal audio playback failed:", error);
    if (_journalActiveAudio === audio) _journalActiveAudio = null;
  });
}

async function copyJournalAnswer(text, label) {
  try {
    await _writeClipboardText(text);
    const original = label.textContent;
    label.textContent = uiString("journal_copy_done");
    window.setTimeout(() => {
      label.textContent = original;
    }, 900);
  } catch (error) {
    console.error("Journal copy failed:", error);
    _setJournalInputStatus(uiString("journal_copy_failed"));
  }
}

async function _writeClipboardText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const scratch = document.createElement("textarea");
  scratch.value = text;
  scratch.setAttribute("readonly", "");
  scratch.style.position = "fixed";
  scratch.style.left = "-9999px";
  document.body.appendChild(scratch);
  scratch.select();
  const copied = document.execCommand("copy");
  scratch.remove();
  if (!copied) throw new Error("document.execCommand copy failed");
}

// Copy feedback for context-menu actions (task-ui-ux-2), which have no
// button of their own left on screen by the time the copy resolves - the
// menu that triggered them is already closed. Journal actions (session
// title, a feed message reached via its menu instead of its own Copy
// button) report through the existing input-status line; a tool row has
// no such line, so it flashes its own label the same way copyJournalAnswer
// flashes its button.
async function _copyToClipboardWithJournalStatus(text) {
  try {
    await _writeClipboardText(text);
    _setJournalInputStatus(uiString("clipboard_copied"));
  } catch (error) {
    console.error("Copy failed:", error);
    _setJournalInputStatus(uiString("clipboard_copy_failed"));
  }
}

async function _copyToClipboardWithLabelFlash(text, label) {
  const original = label.textContent;
  try {
    await _writeClipboardText(text);
    label.textContent = uiString("clipboard_copied");
  } catch (error) {
    console.error("Copy failed:", error);
    label.textContent = uiString("clipboard_copy_failed");
  }
  window.setTimeout(() => {
    label.textContent = original;
  }, 900);
}

function _journalImageThumbnail(mediaItem) {
  const tile = document.createElement("div");
  tile.className = "journal-image-tile";
  const image = document.createElement("img");
  image.src = mediaItem.url;
  image.alt = mediaItem.path.split("/").pop();
  image.loading = "lazy";
  const missing = document.createElement("div");
  missing.className = "journal-image-missing";
  missing.textContent = uiString("journal_image_missing");
  missing.hidden = true;
  image.addEventListener("load", () => {
    _reanchorJournalFeedAfterGrowth(image.offsetHeight);
  });
  image.addEventListener("error", () => {
    image.hidden = true;
    missing.hidden = false;
  });
  tile.append(image, missing);
  return tile;
}

function _formatJournalDate(isoTimestamp) {
  const date = new Date(isoTimestamp);
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function _formatJournalTime(isoTimestamp) {
  const date = new Date(isoTimestamp);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function _formatJournalDuration(startIso, endIso) {
  const seconds = (new Date(endIso) - new Date(startIso)) / 1000;
  return _formatJournalSeconds(seconds);
}

function _formatJournalSeconds(totalSeconds) {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return "--:--";
  const whole = Math.round(totalSeconds);
  const minutes = Math.floor(whole / 60);
  const seconds = String(whole % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function _formatJournalBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return "0 B";
  if (value < 1024) return `${Math.round(value)} B`;
  const units = ["KB", "MB", "GB"];
  let scaled = value / 1024;
  for (const unit of units) {
    if (scaled < 1024) return `${scaled.toFixed(scaled < 10 ? 1 : 0)} ${unit}`;
    scaled /= 1024;
  }
  return `${scaled.toFixed(0)} TB`;
}

// task-ui-ux-1: interaction foundation. Runs on every surface that loads
// app.js (the live console and demo.html's QA harness alike) - unlike the
// transport bootstrap below, which only runs where a real WS transport
// exists. Escapables are registered in the order they should be checked
// last-to-first (see interaction.js's handleGlobalEscape()): the context
// menu (task-ui-ux-2) draws over everything else, including the shortcuts
// overlay, so it registers last of all.
// syncRadioGroup() also runs once here for each group, not only from
// applyThinkingMode()/applyVisibilityMode()/setActiveView(): those only
// fire on a later state change or click, so without this the roving
// tabindex those functions maintain would not exist yet at first paint -
// every button would sit at the browser's native default tabIndex 0
// (individually Tab-focusable) until the first real event arrived.
initRadioGroup(document.getElementById("viewToggle"));
syncRadioGroup(document.getElementById("viewToggle"));
initRadioGroup(document.getElementById("visibilityToggle"));
syncRadioGroup(document.getElementById("visibilityToggle"));
initRadioGroup(document.getElementById("reasoningLevelToggle"));
syncRadioGroup(document.getElementById("reasoningLevelToggle"));
initRadioGroup(document.getElementById("responseModeToggle"));
syncRadioGroup(document.getElementById("responseModeToggle"));
initGlobalKeymap();
_attachStaticIcons();
registerEscapable({
  isOpen: () => document.getElementById("shutdownConfirmRow")?.classList.contains("show") === true,
  close: hideShutdownConfirm,
});
registerEscapable({
  isOpen: () => document.getElementById("journalMemoryPanel")?.hidden === false,
  close: toggleJournalMemoryPanel,
});
registerEscapable({
  isOpen: () => document.getElementById("journalAnnotationPanel")?.hidden === false,
  close: toggleJournalAnnotationPanel,
});
registerEscapable({
  isOpen: () => document.getElementById("journalConsolidationPanel")?.hidden === false,
  close: toggleJournalConsolidationPanel,
});
registerEscapable({
  isOpen: () => document.getElementById("shortcutsOverlay")?.hidden === false,
  close: closeShortcutsOverlay,
});
registerEscapable({
  isOpen: () => document.getElementById("sessionInfoOverlay")?.hidden === false,
  close: closeSessionInfoOverlay,
});
registerEscapable({ isOpen: _contextMenuOpen, close: _closeContextMenu });

if (typeof startUiTransport === "function") {
  installJournalDocumentDropGuard();
  window.addEventListener("beforeunload", (event) => {
    if (!_journalMemoryHasUnsavedChanges()) return;
    event.preventDefault();
    event.returnValue = "";
  });
  startUiTransport("status-console", ["state", "control", "config"], {
    onSnapshot: _applyStateSnapshot,
    onDelta: _applyStateDelta,
    onStatus: _showTransportStatus,
    onError: (message) => console.error("UI transport error:", message),
  });
}
