// Shared JS-side mirror of ui_contract.py's enum values (task-ui-06's AC:
// "Same state contract as desktop Status Console is reused"). Loaded before
// app.js (index.html/demo.html) and before touchstrip.js (touchstrip.html),
// so the two surfaces validate against one list each, not two hand-
// maintained copies that could silently drift apart.

const RUNTIME_STATES = ["idle", "warming", "listening", "thinking", "speaking", "error"];
const MODULE_IDS = ["backend", "microphone", "tts", "memory", "vision"];
const HEALTH_STATUSES = ["ok", "degraded", "error", "unavailable"];
const EVENT_LEVELS = ["info", "active", "warn", "error"];
const VISIBILITY_MODES = ["open", "hidden"];
const DATA_SOURCES = ["local_only", "lan", "internet", "unknown"];
const MCP_STATUSES = ["off", "connecting", "on", "degraded", "disconnecting"];
// story-v1.3.1: graded reasoning level, off -> low -> medium -> high -> off.
// Not to be confused with RUNTIME_STATES' "thinking" (the orb's live
// activity state) - this is the persistent request-time setting.
const REASONING_LEVELS = ["off", "low", "medium", "high"];
