// Status Console shell rendering and UI transport client.
//
// Every apply*/appendSystemEvent function takes a plain JSON object shaped
// like ui_contract.py's dataclasses (converted to snake_case dicts by
// status_console.py's *_payload() helpers) and updates the DOM. Engine state
// arrives through the local protocol-v1 WebSocket snapshot/delta stream.
//
// setReasoningLevel()/requestModuleReset()/requestContextReset()/
// setVisibilityMode() send protocol-v1 control messages. They deliberately do
// not optimistically update the DOM themselves: the reasoning-level toggle/
// chips/visibility toggle only ever change via applyThinkingMode()/
// appendSystemEvent()/applyVisibilityMode(), driven by the real engine event
// coming back through the WebSocket (story-v1.3.1: a ReasoningLevelChanged
// projection), so the UI can never show a state the engine has not actually
// confirmed.
//
// RUNTIME_STATES/MODULE_IDS/HEALTH_STATUSES/EVENT_LEVELS/VISIBILITY_MODES/
// REASONING_LEVELS live in contract.js (loaded before this file) - shared
// with touchstrip.js, see that file's header comment (task-ui-06).

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
  applyMcpState(state.mcp || { status: "off", enabled: false, tools: [] });
  applyModelLabel(state.model);
  _clearSystemEvents();
  (state.system_events || []).forEach(appendSystemEvent);
  applyThinkingMode(state.thinking);
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
    mcp: applyMcpState,
    model: applyModelLabel,
    system_event: appendSystemEvent,
    thinking: applyThinkingMode,
    visibility: applyVisibilityMode,
    model_options: applyModelOptions,
    microphone_options: applyMicrophoneOptions,
    pending_restart: applyPendingRestart,
    ui_language: applyUiLanguage,
    config_values: applyConfigValues,
    journal_event: applyJournalEvent,
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

    const reset = document.createElement("button");
    reset.className = "chip-reset";
    reset.title = uiString("chip_reset_" + module);
    reset.textContent = "↻";
    reset.addEventListener("click", () => requestModuleReset(module));
    chip.append(dot, body, reset);
    panel.appendChild(chip);
  }
}

// Both the microphone path (audio) and the upload path (attachment_audio)
// carry the same single-per-turn ModelRequestStarted.audio_duration_seconds
// value (see transport.py's _AUDIO_DURATION_INPUTS) - either kind renders it.
const _AUDIO_DURATION_KINDS = new Set(["audio", "attachment_audio"]);

function applyLastModelRequest(payload) {
  const list = document.getElementById("lastRequestList");
  list.replaceChildren();
  for (const item of payload.items || []) {
    const row = document.createElement("li");
    const detail = _AUDIO_DURATION_KINDS.has(item.kind) && item.duration_seconds !== undefined
      ? ": " + item.duration_seconds.toFixed(1) + " s"
      : "";
    row.textContent = formatLogTime(payload.timestamp) + " - "
      + uiString("last_request_" + item.kind) + detail;
    list.appendChild(row);
  }
}

function applyDataLocality(payload) {
  const badge = document.getElementById("localityBadge");
  badge.setAttribute("data-locality", payload.locality);
  badge.querySelector(".locality-label").textContent =
    uiString(payload.locality === "local" ? "locality_local" : "locality_external");
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

  const list = document.getElementById("mcpTools");
  list.replaceChildren();
  for (const tool of payload.tools || []) {
    const row = document.createElement("li");
    row.setAttribute("data-available", String(tool.available));
    const stateKey = tool.available && tool.enabled
      ? "mcp_tool_available"
      : "mcp_tool_unavailable";
    row.textContent = `${tool.name} - ${tool.provider} - ${uiString(stateKey)}`;
    list.appendChild(row);
  }
  document.getElementById("mcpToolsEmpty").hidden = list.children.length !== 0;
}

function setMcpEnabled() {
  _sendControl("set_mcp_enabled", { enabled: !_mcpEnabled });
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

function appendSystemEvent(payload) {
  if (!EVENT_LEVELS.includes(payload.level)) {
    throw new Error("Unknown event level: " + payload.level);
  }
  const list = document.getElementById("logList");
  const empty = document.getElementById("logEmpty");
  if (empty) empty.remove();

  const row = document.createElement("div");
  row.className = "log-entry";
  row.dataset.level = payload.level;

  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = formatLogTime(payload.timestamp);

  const src = document.createElement("span");
  src.className = "log-src";
  src.textContent = payload.source;

  const msg = document.createElement("span");
  msg.className = "log-msg";
  msg.textContent = payload.message;

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
  document.getElementById("thinkTag").textContent = "level: " + payload.level;
  document.getElementById("thinkStatus").textContent = uiString("think_status_" + payload.level);
}

function setReasoningLevel(levelValue) {
  _sendControl("set_reasoning_level", { level: levelValue });
}

function requestModuleReset(moduleId) {
  if (!MODULE_IDS.includes(moduleId)) {
    throw new Error("Unknown module id: " + moduleId);
  }
  _sendControl("reset_module", { module_id: moduleId });
}

function showResetConfirm() {
  document.getElementById("confirmRow").classList.add("show");
}

function hideResetConfirm() {
  document.getElementById("confirmRow").classList.remove("show");
}

function confirmContextReset() {
  hideResetConfirm();
  _sendControl("reset_context");
}

// story-v1.2.4-task-1: guarded Shutdown control - same confirm-before-
// destructive-action shape as the context reset above (show/hide only
// toggle local UI state; only confirmShutdown() calls back into the
// engine). Unlike context reset, there is no applyShutdown() callback to
// wait for: once request_shutdown() actually tears down the running
// engine, there is nothing left running to push a confirmation back.
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
  renderModules();
  _onJournalVisibilityChanged(payload.mode);
}

function setVisibilityMode(modeValue) {
  _sendControl("set_visibility_mode", { mode: modeValue });
}

// story-v1.2.4-task-3: configuration menu (model + microphone,
// restart-to-apply). toggleConfigMenu() re-fetches both selectors' options
// every time the panel is opened (never on close), so reopening it always
// shows fresh enumeration rather than a stale snapshot from last time -
// each fetch degrades to just the current configured value on failure
// (status_console.py's request_model_options()/request_microphone_options(),
// never invented or guessed here). Like every other control on this page,
// selecting an option does not apply anything by itself - only
// applyConfigSelection() (the "Apply" button) writes config.ui.toml,
// and even that is restart-to-apply, not live (see confirmShutdown() and
// the reset flow above for the same "engine confirms, UI never assumes"
// shape - the difference here is there is no live confirmation event to
// wait for, since nothing changes in the running process at all until the
// next start; applyPendingRestart() is shown immediately after a
// successful save, not deferred to any engine event).
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

function toggleConfigMenu() {
  const panel = document.getElementById("configPanel");
  const opening = !panel.classList.contains("show");
  panel.classList.toggle("show");
  if (!opening) return;
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

function applyMicrophoneOptions(payload, markLoaded = true) {
  _renderOptions(document.getElementById("micSelect"), payload.options, payload.current);
  if (markLoaded) _microphoneOptionsLoaded = true;
  _updateApplyButtonEnabled();
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
  document.getElementById("vadThreshold").value = payload.vad.threshold;
  document.getElementById("vadMaxChunk").value = payload.vad.max_chunk_seconds;
  document.getElementById("vadEndPause").value = payload.vad.request_end_pause_seconds;
  document.getElementById("vadCooldown").value = payload.vad.resume_cooldown_seconds;
  const custom = payload.tts.languages.every((lang) => lang in payload.tts.routes);
  document.getElementById("ttsCustomRoutes").checked = custom;
  _renderTtsRouteRows();
  onConfigInputChanged();
}

function _renderTtsRouteRows() {
  const container = document.getElementById("ttsRouteRows");
  container.innerHTML = "";
  if (_configValues === null) return;
  const enabled = document.getElementById("ttsCustomRoutes").checked;
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
  const microphone = document.getElementById("micSelect").value;
  _sendControl("save_config_selection", {
    model,
    microphone,
    ui_language: document.getElementById("uiLangSelect").value,
    vad: {
      threshold: Number(document.getElementById("vadThreshold").value),
      max_chunk_seconds: Math.round(Number(document.getElementById("vadMaxChunk").value)),
      request_end_pause_seconds: Number(document.getElementById("vadEndPause").value),
      resume_cooldown_seconds: Number(document.getElementById("vadCooldown").value),
    },
    tts_routes: _collectTtsRoutes(),
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

function _isJournalActive() {
  return document.documentElement.getAttribute("data-view") === "journal";
}

function _isHiddenActive() {
  return document.documentElement.getAttribute("data-visibility") === "hidden";
}

function setActiveView(view) {
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
  if (view === "journal" && !_isHiddenActive()) {
    refreshJournalSessions();
  }
}

function _onJournalVisibilityChanged(mode) {
  // demo.html loads app.js without the journal markup (it is a pre-journal
  // QA harness); the hook must be a no-op there.
  if (!document.getElementById("journalView")) return;
  if (mode === "hidden") {
    _clearJournalContent();
  } else if (_isJournalActive()) {
    refreshJournalSessions();
  }
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
  document.getElementById("journalMemoryToggle").textContent = uiString(
    _journalMemoryOpen ? "journal_memory_close" : "journal_memory_open");
  if (_journalMemoryOpen) await loadJournalMemoryFiles();
}

function _clearJournalMemoryPanel() {
  _journalMemoryOpen = false;
  _journalMemoryFiles = new Map();
  const panel = document.getElementById("journalMemoryPanel");
  if (panel) panel.hidden = true;
  const toggle = document.getElementById("journalMemoryToggle");
  if (toggle) toggle.textContent = uiString("journal_memory_open");
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
}

function _journalMemoryFileElement(fileId) {
  const state = _journalMemoryFiles.get(fileId);
  const section = document.createElement("section");
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

async function submitJournalInput() {
  if (_journalInputInFlight) {
    _setJournalInputStatus(uiString("journal_input_busy"));
    return;
  }
  if (_isHiddenActive()) {
    _setJournalInputStatus(uiString("journal_input_hidden"));
    return;
  }
  if (_journalActiveSessionId === null) {
    _setJournalInputStatus(uiString("journal_new_context_required"));
    return;
  }
  const input = document.getElementById("journalTextInput");
  const send = document.getElementById("journalSendButton");
  const text = input.value;
  const url = _journalUrl("/api/journal/input");
  if (url === null) {
    _setJournalInputStatus(uiString("transport_no_token"));
    return;
  }
  _journalInputInFlight = true;
  _journalSelectPendingInputSession = true;
  send.disabled = true;
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const payload = await response.json();
    if (payload.status === "accepted") {
      if (input.value === text) input.value = "";
      _setJournalInputStatus(uiString("journal_input_sent"));
    } else if (payload.status === "hidden") {
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
    send.disabled = false;
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

async function refreshJournalSessions() {
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
  if (_journalSelectedSessionId === null && sessions.length !== 0) {
    selectJournalSession(sessions[0].id);
  }
}

function _applyJournalUsage(payload) {
  const usage = payload || { total_bytes: 0, active_session_id: null, sessions: [] };
  _journalActiveSessionId = usage.active_session_id || null;
  _journalUsageBySession = new Map(
    (usage.sessions || []).map((session) => [session.id, session.bytes || 0]));
  document.getElementById("journalUsageTotal").textContent =
    uiString("journal_usage_total").replace("{size}", _formatJournalBytes(usage.total_bytes || 0));
}

function _journalSessionElement(session) {
  const row = document.createElement("div");
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.className = "journal-session";
  row.dataset.sessionId = session.id;
  row.classList.toggle("sel", session.id === _journalSelectedSessionId);

  const when = document.createElement("div");
  when.className = "journal-session-when";
  const date = document.createElement("span");
  date.textContent = _formatJournalDate(session.start_timestamp);
  const time = document.createElement("span");
  time.textContent = _formatJournalTime(session.start_timestamp);
  const duration = document.createElement("span");
  duration.textContent = _formatJournalDuration(
    session.start_timestamp, session.end_timestamp);
  when.append(date, time, duration);

  const title = document.createElement("div");
  title.className = "journal-session-title";
  title.textContent = session.title;

  const size = document.createElement("div");
  size.className = "journal-session-size";
  size.textContent = _formatJournalBytes(_journalUsageBySession.get(session.id) || 0);

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "journal-session-delete";
  deleteButton.textContent = "×";
  deleteButton.title = uiString(
    session.id === _journalActiveSessionId
      ? "journal_session_active"
      : "journal_session_delete");
  deleteButton.disabled = session.id === _journalActiveSessionId;
  deleteButton.addEventListener("click", (event) => {
    event.stopPropagation();
    deleteJournalSession(session.id);
  });

  const continueButton = document.createElement("button");
  continueButton.type = "button";
  continueButton.className = "journal-session-continue";
  continueButton.textContent = "↪";
  continueButton.title = uiString("journal_session_continue");
  continueButton.disabled =
    session.id === _journalActiveSessionId ||
    session.id === _journalForkInFlightSessionId;
  continueButton.addEventListener("click", (event) => {
    event.stopPropagation();
    continueJournalSession(session.id);
  });

  const actions = document.createElement("div");
  actions.className = "journal-session-actions";
  if (session.id !== _journalActiveSessionId) actions.appendChild(continueButton);
  actions.appendChild(deleteButton);

  row.append(when, title, size, actions);
  row.addEventListener("click", () => selectJournalSession(session.id));
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") selectJournalSession(session.id);
  });
  return row;
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
  document.querySelectorAll("#journalSessionList .journal-session").forEach((row) => {
    row.classList.toggle("sel", row.dataset.sessionId === sessionId);
  });
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
    payload.source === "dock"
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
  if (event.role === "assistant" && event.text) {
    const spacer = document.createElement("span");
    spacer.className = "journal-msg-meta-spacer";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "journal-copy";
    copy.textContent = uiString("journal_copy_answer");
    copy.title = uiString("journal_copy_answer");
    copy.addEventListener("click", () => copyJournalAnswer(event.text, copy));
    meta.append(spacer, copy);
  }
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
  const provenanceDetail = _journalProvenanceDetail(event);
  if (provenanceDetail !== null) message.appendChild(provenanceDetail);
  return message;
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

async function copyJournalAnswer(text, button) {
  try {
    await _writeClipboardText(text);
    const original = button.textContent;
    button.textContent = uiString("journal_copy_done");
    window.setTimeout(() => {
      button.textContent = original;
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

if (typeof startUiTransport === "function") {
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
