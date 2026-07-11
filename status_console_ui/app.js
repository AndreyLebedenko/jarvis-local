// Status Console shell rendering and UI transport client.
//
// Every apply*/appendSystemEvent function takes a plain JSON object shaped
// like ui_contract.py's dataclasses (converted to snake_case dicts by
// status_console.py's *_payload() helpers) and updates the DOM. Engine state
// arrives through the local protocol-v1 WebSocket snapshot/delta stream.
//
// toggleThinking()/requestModuleReset()/requestContextReset()/
// setVisibilityMode() send protocol-v1 control messages. They deliberately do
// not optimistically update the DOM themselves: the switch/chips/visibility
// toggle only ever change via applyThinkingMode()/appendSystemEvent()/
// applyVisibilityMode(), driven by the real engine event coming back through
// the WebSocket, so the UI can never show a state the engine has not actually
// confirmed.
//
// RUNTIME_STATES/MODULE_IDS/HEALTH_STATUSES/EVENT_LEVELS/VISIBILITY_MODES
// live in contract.js (loaded before this file) - shared with
// touchstrip.js, see that file's header comment (task-ui-06).

// task-ui-05 (human decision): Hidden only changes what this UI shows - it
// never touches audio_in.py/tts.py/Orchestrator. The one concrete UI-level
// behavior it drives here: the vision/screen chip's detail text (which
// could carry a captured region size/timestamp once a real capture-health
// signal exists) is replaced with a generic placeholder while Hidden is
// active, regardless of what was last pushed - "screen previews hidden by
// default, sensitive snippets not shown" from tasks/task-ui-privacy-and-
// touchstrip-requirements.md. The real detail is remembered so switching
// back to Open restores it without needing another push from Python.
let _lastVisionDetail = "";

// Caps DOM growth for a long-running process feeding a live-appending log
// (task-ui-03's Scope: "recent events", not an unbounded transcript).
const MAX_LOG_ENTRIES = 200;

const _showTransportStatus = typeof createTransportStatusHandler === "function"
  ? createTransportStatusHandler()
  : () => {};

function _sendControl(command, argumentsObject = {}) {
  if (typeof sendUiControl !== "function" || !sendUiControl(command, argumentsObject)) {
    _showTransportStatus(false, "Нет связи с engine");
  }
}

function _clearSystemEvents() {
  const list = document.getElementById("logList");
  list.replaceChildren();
}

function _applyStateSnapshot(state) {
  applyRuntimeState(state.runtime);
  Object.values(state.modules || {}).forEach(applyModuleHealth);
  applyDataLocality(state.data_locality);
  applyModelLabel(state.model);
  _clearSystemEvents();
  (state.system_events || []).forEach(appendSystemEvent);
  applyThinkingMode(state.thinking);
  applyVisibilityMode(state.visibility);
  applyModelOptions(state.model_options, false);
  applyMicrophoneOptions(state.microphone_options, false);
  applyPendingRestart(state.pending_restart);
}

function _applyStateDelta(payload) {
  dispatchStateDelta(payload, {
    runtime: applyRuntimeState,
    modules: (value) => Object.values(value).forEach(applyModuleHealth),
    data_locality: applyDataLocality,
    model: applyModelLabel,
    system_event: appendSystemEvent,
    thinking: applyThinkingMode,
    visibility: applyVisibilityMode,
    model_options: applyModelOptions,
    microphone_options: applyMicrophoneOptions,
    pending_restart: applyPendingRestart,
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
  const chip = document.getElementById("chip-" + payload.module);
  if (!chip) return;
  chip.setAttribute("data-status", payload.status);
  chip.querySelector(".chip-dot").setAttribute("data-status", payload.status);
  if (payload.module === "vision") {
    _lastVisionDetail = payload.detail || "";
    _renderVisionChipMeta();
    return;
  }
  const meta = chip.querySelector(".chip-meta");
  meta.textContent = payload.detail || "";
}

function _renderVisionChipMeta() {
  const isHidden = document.documentElement.getAttribute("data-visibility") === "hidden";
  document.getElementById("chip-vision").querySelector(".chip-meta").textContent = isHidden
    ? "превью скрыто (Hidden)"
    : _lastVisionDetail;
}

function applyDataLocality(payload) {
  const badge = document.getElementById("localityBadge");
  badge.setAttribute("data-locality", payload.locality);
  badge.querySelector(".locality-label").textContent =
    payload.locality === "local" ? "Локально" : "Внешний backend";
}

function applyModelLabel(payload) {
  document.getElementById("chip-backend").querySelector(".chip-meta").textContent = payload.label;
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
  const enabled = payload.is_enabled;
  document.getElementById("thinkSwitch").classList.toggle("on", enabled);
  document.getElementById("thinkTag").textContent = "think: " + (enabled ? "on" : "off");
  document.getElementById("thinkStatus").textContent = enabled
    ? "Глубже, медленнее - с расширенной обработкой запроса"
    : "Быстрее, без рассуждения";
}

function toggleThinking() {
  _sendControl("toggle_thinking");
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
  _renderVisionChipMeta();
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
// applyConfigSelection() (the "Применить" button) writes config.ui.toml,
// and even that is restart-to-apply, not live (see confirmShutdown() and
// the reset flow above for the same "engine confirms, UI never assumes"
// shape - the difference here is there is no live confirmation event to
// wait for, since nothing changes in the running process at all until the
// next start; applyPendingRestart() is shown immediately after a
// successful save, not deferred to any engine event).
// Regression guard (2026-07-07, real live-session bug): both <select>s
// start empty (no <option>s) until request_model_options()/
// request_microphone_options() resolve - a click on "Применить" before
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
  document.getElementById("btnConfigApply").disabled =
    !(_modelOptionsLoaded && _microphoneOptionsLoaded);
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
    el.textContent = option === "" ? "(системный микрофон по умолчанию)" : option;
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

function applyConfigSelection() {
  const model = document.getElementById("modelSelect").value;
  const microphone = document.getElementById("micSelect").value;
  _sendControl("save_config_selection", { model, microphone });
}

if (typeof startUiTransport === "function") {
  startUiTransport("status-console", ["state", "control", "config"], {
    onSnapshot: _applyStateSnapshot,
    onDelta: _applyStateDelta,
    onStatus: _showTransportStatus,
    onError: (message) => console.error("UI transport error:", message),
  });
}
