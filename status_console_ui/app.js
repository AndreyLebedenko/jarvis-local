// Status Console shell rendering (task-ui-02).
//
// Every function here takes a plain JSON object shaped like ui_contract.py's
// dataclasses (converted to snake_case dicts by status_console.py's
// *_payload() helpers) and updates the DOM. Nothing here reads engine state
// on its own - status_console.py pushes it in via pywebview's evaluate_js
// bridge (in-process IPC, no network). No function here talks to a real
// bus event yet; that wiring belongs to task-ui-03 (events)/task-ui-04
// (think/reset)/task-ui-05 (visibility).

const RUNTIME_STATES = ["idle", "warming", "listening", "thinking", "speaking", "error"];
const MODULE_IDS = ["backend", "microphone", "tts", "memory", "vision"];
const HEALTH_STATUSES = ["ok", "degraded", "error", "unavailable"];

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
