// Touchstrip glance surface rendering (task-ui-06).
//
// Same state contract as the desktop shell (task-ui-06's AC): every apply*
// function here takes the exact same JSON payload shape status_console.py's
// *_payload() helpers produce for app.js - RUNTIME_STATES/MODULE_IDS/
// HEALTH_STATUSES/VISIBILITY_MODES come from contract.js, loaded before
// this file, not a second hand-maintained copy. The rendering itself is
// deliberately different (two paginated glance/actions screens, no event
// log, dots instead of chip cards) - "its own UI, not a compressed desktop
// dashboard" (Scope).
//
// toggleThinking()/toggleVisibilityFromGlance()/onResetHoldStart()/
// onResetHoldEnd() send the same protocol-v1 control messages as the desktop
// shell. Both surfaces receive the same engine snapshot/deltas.

let _lastModelLabel = "";
let _lastLocalityText = "";

const _showTransportStatus = typeof createTransportStatusHandler === "function"
  ? createTransportStatusHandler()
  : () => {};

function _applyStateSnapshot(state) {
  applyRuntimeState(state.runtime);
  Object.values(state.modules || {}).forEach(applyModuleHealth);
  applyModelLabel(state.model);
  applyDataLocality(state.data_locality);
  applyThinkingMode(state.thinking);
  applyVisibilityMode(state.visibility);
}

function _applyStateDelta(payload) {
  dispatchStateDelta(payload, {
    runtime: applyRuntimeState,
    modules: (value) => Object.values(value).forEach(applyModuleHealth),
    model: applyModelLabel,
    data_locality: applyDataLocality,
    thinking: applyThinkingMode,
    visibility: applyVisibilityMode,
  });
}

function applyRuntimeState(payload) {
  if (!RUNTIME_STATES.includes(payload.state)) {
    throw new Error("Unknown runtime state: " + payload.state);
  }
  document.documentElement.setAttribute("data-state", payload.state);
  document.getElementById("gState").textContent = payload.label;
  document.getElementById("gSub").textContent = payload.substatus || "";
  document
    .getElementById("ring")
    .setAttribute("data-anim", payload.state === "warming" ? "warm" : "normal");
}

// Scope's "key module dots" excludes backend/model - that is represented
// by the combined model/locality line instead (_renderModelLine()), not a
// dot, matching the mock-up's layout.
const _DOT_MODULE_IDS = MODULE_IDS.filter((module) => module !== "backend");

function applyModuleHealth(payload) {
  if (!MODULE_IDS.includes(payload.module)) {
    throw new Error("Unknown module id: " + payload.module);
  }
  if (!HEALTH_STATUSES.includes(payload.status)) {
    throw new Error("Unknown health status: " + payload.status);
  }
  if (!_DOT_MODULE_IDS.includes(payload.module)) return; // backend: no dot here
  const dot = document.getElementById("dot-" + payload.module);
  if (dot) dot.setAttribute("data-status", payload.status);
}

function applyModelLabel(payload) {
  _lastModelLabel = payload.label;
  _renderModelLine();
}

function applyDataLocality(payload) {
  _lastLocalityText = payload.locality === "local" ? "локально" : "внешний backend";
  _renderModelLine();
}

function _renderModelLine() {
  document.getElementById("gModel").textContent = [_lastModelLabel, _lastLocalityText]
    .filter(Boolean)
    .join(" · ");
}

function applyThinkingMode(payload) {
  const enabled = payload.is_enabled;
  document.getElementById("thinkBtn").classList.toggle("on", enabled);
  document.getElementById("thinkSub").textContent = "think: " + (enabled ? "on" : "off");
}

function applyVisibilityMode(payload) {
  if (!VISIBILITY_MODES.includes(payload.mode)) {
    throw new Error("Unknown visibility mode: " + payload.mode);
  }
  // Deliberately never touches a locality element - same independence rule
  // as app.js's applyVisibilityMode() (task-ui-05 AC: "Hidden does not
  // imply cloud/offline status"). There is no screen-preview surface here
  // to hide either (no per-module detail text is ever shown on this
  // surface, unlike the desktop's vision chip) - "screen previews hidden
  // by default" holds trivially, by having nothing sensitive to show.
  document.documentElement.setAttribute("data-visibility", payload.mode);
  document.getElementById("gVisibility").textContent = payload.mode === "open" ? "Open" : "Hidden";
}

function toggleThinking() {
  sendUiControl("toggle_thinking");
}

function toggleVisibilityFromGlance() {
  const current = document.documentElement.getAttribute("data-visibility");
  const next = current === "open" ? "hidden" : "open";
  sendUiControl("set_visibility_mode", { mode: next });
}

// Hold-to-confirm reset (Scope: "context reset with hold-to-confirm"; AC:
// "Reset requires hold or equivalent confirmation") - a 1s pointer hold,
// not a tap+dialog (a modal confirm row would be too much chrome on a
// glance surface this narrow). Releasing early cancels; no partial reset
// ever fires.
const RESET_HOLD_MS = 1000;
let _resetHoldTimer = null;

function onResetHoldStart() {
  document.getElementById("resetBtn").classList.add("holding");
  _resetHoldTimer = setTimeout(() => {
    _resetHoldTimer = null;
    document.getElementById("resetBtn").classList.remove("holding");
    sendUiControl("reset_context");
  }, RESET_HOLD_MS);
}

function onResetHoldEnd() {
  document.getElementById("resetBtn").classList.remove("holding");
  if (_resetHoldTimer !== null) {
    clearTimeout(_resetHoldTimer);
    _resetHoldTimer = null;
  }
}

// story-v1.2.4-task-1: guarded Shutdown control. Same hold-to-confirm
// pattern as context reset above (a modal confirm dialog would be too
// much chrome on this narrow glance surface - see the reset comment), but
// held twice as long (SHUTDOWN_HOLD_MS): stopping the whole running
// engine from a compact touch surface meant to sit in reach in a room is
// a strictly bigger, easier-to-regret action than clearing conversation
// history, so it deliberately takes longer to trigger by accident.
const SHUTDOWN_HOLD_MS = 2000;
let _shutdownHoldTimer = null;
// Set once the hold actually completes and fires - see confirmShutdown()'s
// comment in app.js for why: there is no "shutdown complete" push to wait
// for, the window is known to stay open but inert afterward, and a
// confused repeat hold is a real, observed failure mode (verified live,
// 2026-07-07). Purely cosmetic on top of status_console.py's own
// closed-loop guard, not a substitute for it.
let _shutdownRequested = false;

function onShutdownHoldStart() {
  if (_shutdownRequested) return;
  document.getElementById("shutdownBtn").classList.add("holding");
  _shutdownHoldTimer = setTimeout(() => {
    _shutdownHoldTimer = null;
    _shutdownRequested = true;
    document.getElementById("shutdownBtn").classList.remove("holding");
    sendUiControl("request_shutdown");
  }, SHUTDOWN_HOLD_MS);
}

function onShutdownHoldEnd() {
  document.getElementById("shutdownBtn").classList.remove("holding");
  if (_shutdownHoldTimer !== null) {
    clearTimeout(_shutdownHoldTimer);
    _shutdownHoldTimer = null;
  }
}

function showPage(page) {
  document.documentElement.setAttribute("data-page", page);
  document.getElementById("pageGlance").classList.toggle("show", page === "glance");
  document.getElementById("pageActions").classList.toggle("show", page === "actions");
  document
    .querySelectorAll(".page-dot")
    .forEach((dot, i) => dot.classList.toggle("on", (page === "glance") === (i === 0)));
}

if (typeof startUiTransport === "function") {
  startUiTransport("touchstrip", ["state", "control"], {
    onSnapshot: _applyStateSnapshot,
    onDelta: _applyStateDelta,
    onStatus: _showTransportStatus,
    onError: (message) => console.error("UI transport error:", message),
  });
}
