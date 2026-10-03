// Shared JS-side mirror of the Python vocabulary this UI compares against
// (ui_contract.py's enums under task-ui-06's AC: "Same state contract as
// desktop Status Console is reused", plus core/run_mode.py and
// journal/external_canvas.py). Loaded before app.js (index.html/demo.html) and
// before touchstrip.js (touchstrip.html), so the two surfaces validate against
// one list each, not two hand-maintained copies that could silently drift
// apart.

const RUNTIME_STATES = [
  "idle", "warming", "listening", "mcp_waiting", "thinking", "speaking", "error",
];
const MODULE_IDS = ["backend", "microphone", "tts", "memory", "vision", "camera"];
const HEALTH_STATUSES = ["ok", "degraded", "error", "unavailable"];
const EVENT_LEVELS = ["info", "active", "warn", "error"];
const VISIBILITY_MODES = ["open", "hidden"];
const DATA_SOURCES = ["local_only", "lan", "internet", "unknown"];
const MCP_STATUSES = ["off", "connecting", "on", "degraded", "disconnecting"];
// story-v1.3.1: graded reasoning level, off -> low -> medium -> high -> off.
// Not to be confused with RUNTIME_STATES' "thinking" (the orb's live
// activity state) - this is the persistent request-time setting.
const REASONING_LEVELS = ["off", "low", "medium", "high"];
// story-v1.9.0: persistent response mode, text -> voice -> text_voice -> text.
const RESPONSE_MODES = ["text", "voice", "text_voice"];
// The run mode the engine fixes for the process (core/run_mode.py) and the
// source of an answer some other assistant sent
// (journal/external_canvas.py). Named members because both are compared
// against, not validated against a list.
const RUN_MODE = { NORMAL: "normal", MCP: "mcp" };
const MCP_CANVAS_SOURCE = "mcp_canvas";
