// Status Console shell rendering (task-ui-02/task-ui-03/task-ui-04).
//
// Every apply*/appendSystemEvent function takes a plain JSON object shaped
// like ui_contract.py's dataclasses (converted to snake_case dicts by
// status_console.py's *_payload() helpers) and updates the DOM. Nothing here
// reads engine state on its own - status_console.py pushes it in via
// pywebview's evaluate_js bridge (in-process IPC, no network).
//
// toggleThinking()/requestModuleReset()/requestContextReset() are the other
// direction (JS -> Python, pywebview's js_api - see status_console.py's
// StatusConsoleApi). They deliberately do not optimistically update the DOM
// themselves: the switch/chips only ever change via applyThinkingMode()/
// appendSystemEvent(), driven by the real engine event coming back through
// evaluate_js, so the UI can never show a state the engine hasn't actually
// confirmed. window.pywebview is undefined outside a real pywebview window
// (e.g. demo.html opened in an ordinary browser), so every call is guarded -
// visibility mode is still a reserved placeholder, task-ui-05's job.

const RUNTIME_STATES = ["idle", "warming", "listening", "thinking", "speaking", "error"];
const MODULE_IDS = ["backend", "microphone", "tts", "memory", "vision"];
const HEALTH_STATUSES = ["ok", "degraded", "error", "unavailable"];
const EVENT_LEVELS = ["info", "active", "warn", "error"];

// Caps DOM growth for a long-running process feeding a live-appending log
// (task-ui-03's Scope: "recent events", not an unbounded transcript).
const MAX_LOG_ENTRIES = 200;

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
  const meta = chip.querySelector(".chip-meta");
  meta.textContent = payload.detail || "";
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

function _pywebviewApi() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

function toggleThinking() {
  const api = _pywebviewApi();
  if (api) api.toggle_thinking();
}

function requestModuleReset(moduleId) {
  if (!MODULE_IDS.includes(moduleId)) {
    throw new Error("Unknown module id: " + moduleId);
  }
  const api = _pywebviewApi();
  if (api) api.reset_module(moduleId);
}

function showResetConfirm() {
  document.getElementById("confirmRow").classList.add("show");
}

function hideResetConfirm() {
  document.getElementById("confirmRow").classList.remove("show");
}

function confirmContextReset() {
  hideResetConfirm();
  const api = _pywebviewApi();
  if (api) api.reset_context();
}
