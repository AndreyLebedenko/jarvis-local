# Task UI-01: State and event contract for Status Console

**Story:** story-status-console-ui.md
**Статус:** Completed.
**Приоритет:** высокий
**Зависимости:** нет

## Summary

Define the backend-to-UI contract before building screens. The UI must consume
structured state/events, not scrape logs or infer state from unrelated module
internals.

## Scope

- Define runtime state enum: `IDLE`, `WARMING`, `LISTENING`, `THINKING`,
  `SPEAKING`, `ERROR`.
- Define module health snapshot shape for backend/model, microphone, TTS,
  memory and vision/screen.
- Define system event shape: timestamp, source, level, message, optional
  correlation id.
- Define visibility mode state: `Open` / `Hidden`.
- Define data locality state separately from visibility mode.

## Contract

The contract is implemented as plain data (enums and frozen dataclasses) in
[`ui_contract.py`](../ui_contract.py). No GUI framework dependency, no bus
wiring - task-ui-02 has not chosen a framework yet, and this module must stay
importable regardless of that choice. Shapes:

- `RuntimeState` (enum): `IDLE`, `WARMING`, `LISTENING`, `THINKING`,
  `SPEAKING`, `ERROR`.
- `ModuleId` (enum): `BACKEND`, `MICROPHONE`, `TTS`, `MEMORY`, `VISION`.
- `HealthStatus` (enum): `OK`, `DEGRADED`, `ERROR`, `UNAVAILABLE`. A module
  that is off by design (e.g. vision before any capture this session) is
  `UNAVAILABLE`, not `ERROR` - the two must not look the same in the UI.
- `ModuleHealth` (frozen dataclass): `module`, `status`, `detail` (defaults to
  `""`).
- `EventLevel` (enum): `INFO`, `ACTIVE`, `WARN`, `ERROR` - matches the
  four-way legend already drawn in
  `.planning/UI/mock-ups/jarvis_status_console_v1.html`.
- `SystemEvent` (frozen dataclass): `timestamp` (a `time.time()` float, the UI
  decides display formatting), `source` (short string, e.g. `"ENGINE"`,
  `"LLM"`, `"TTS"`, `"STT"`, `"VAD"`), `level`, `message`,
  `correlation_id` (optional, `None` by default - nothing in v1.0 generates
  one yet, but later turn-scoped correlation can be added without a shape
  change).
- `VisibilityMode` (enum): `OPEN`, `HIDDEN`. Independent of `DataLocality` -
  see story's Key Decisions and
  `tasks/task-ui-privacy-and-touchstrip-requirements.md`.
- `DataLocality` (enum): `LOCAL`, `EXTERNAL`. v1.0 only ever reports `LOCAL`
  (Ollama is the only supported v1.0 backend per `PROJECT.md`); `EXTERNAL` is
  defined now so the enum shape does not need to change later, even though
  cloud provider switching is explicitly out of this story's scope.

## Event Mapping

Existing bus events that already carry (or can double as) contract-relevant
signal, and what still needs to change for the UI to consume them:

| Existing event | Module | Maps to | Notes |
| --- | --- | --- | --- |
| `ResponseToken` (`backend.py`) | backend | `RuntimeState.SPEAKING` transition | Already excludes `message.thinking` (backend.py's stream loop only republishes `message.content`) - satisfies "reasoning chunks excluded from UI events by default" with no further change. The *first* token of a turn is the existing signal `Orchestrator.on_response_token` already uses to play the `speaking` cue; the UI can key off the same thing once it is published (see below). |
| `ResponseComplete` (`backend.py`) | backend | end of `THINKING`/`SPEAKING`, start of `LISTENING` | Carries `LatencyMetrics`; a `SystemEvent` wrapping a summary line (e.g. eval time) is straightforward to add later without changing this event. |
| `MicSleepToggled` (`audio_in.py`) | microphone | Part of `ModuleHealth(MICROPHONE, ...)` and mic chip state | Reflects the user's own privacy intent (`toggle_user_sleep()`), not a hardware-availability signal - see Missing Events below for the gap. |
| `ThinkingModeToggled` (`thinking_mode.py`) | backend | Think toggle UI state | Direct 1:1 mapping, `is_enabled` -> the toggle's on/off state. No new event needed. |
| `ScreenshotCaptured` (`capture.py`) | vision | `SystemEvent(source="VISION", level=INFO)` | Success-only event today; see Missing Events for the failure case. |
| `ClipboardSubmitted` (`clipboard_input.py`) | (input, not a module chip) | `SystemEvent(source="INPUT", level=INFO or WARN)` | `truncated`/`is_empty` fields already carry enough to pick the level. |

## Missing Events (implementation requirements for later task cards)

None of these require a change to `bus.py` itself (it is a generic pub/sub;
adding a new event *type* is additive, not a schema change to existing
consumers) - so the Stop Condition below does not trigger. They are,
however, genuinely new signals that do not exist in the codebase today and
must be built by the task card that needs them:

- **Turn lifecycle event** (`RuntimeState` transitions for `THINKING` start
  and `LISTENING` return). Today `Orchestrator._busy` is private and
  `_start_turn()`/`finish_turn()` only trigger sound cues as a side effect -
  nothing is published. Required for task-ui-02/03 to show `THINKING` at all.
- **Warm-up start/end event** for `RuntimeState.WARMING`. `main.py`'s
  `warm_up()` runs once at startup and publishes nothing; the
  story-voice-trigger-warmup.md backlog (`task-01-ollama-keepalive-warmup.md`,
  `task-02-status-orb-warming-state.md`) has not landed yet either. Whichever
  lands first should publish this.
- **Structured error event.** Every current failure path
  (`Orchestrator._start_turn`'s `except Exception`,
  `_on_full_response_complete`'s `except Exception`) only calls
  `logger.exception(...)` and plays the `error` sound cue - no event is
  published, so the UI has no way to show *what* failed. Needed for
  `RuntimeState.ERROR` and for `ModuleHealth(status=ERROR)` on the backend
  chip.
- **Microphone hardware-availability signal**, distinct from
  `MicSleepToggled`. `audio_in.py`'s `run_microphone_loop()` has no
  try/except around stream construction/reads at all; a missing input
  device would just raise inside the background task with nothing
  structured published. Needed for `ModuleHealth(MICROPHONE, ERROR)`.
- **TTS model/availability signal.** `tts.py`'s `TtsModelNotCachedError` (and
  any synthesis/playback failure) is never caught or published anywhere in
  `main.py`'s wiring - it would surface only as an unhandled-subscriber-
  exception log line from `bus.py`. Needed for `ModuleHealth(TTS, ...)`.
- **Backend reachability signal**, distinct from a single turn's failure.
  There is no persisted health state today - `warm_up()`'s own failure is
  caught and logged, then the process continues anyway with no lasting
  "backend is degraded" state visible to anything.
- **Screenshot failure event.** `capture.py`'s `CaptureInput.publish_*`
  methods have no error handling; an `mss` failure would raise uncaught.
  Needed for `ModuleHealth(VISION, ERROR)` (as opposed to the `UNAVAILABLE`
  default before any capture this session).
- **Visibility mode change event** (`VisibilityMode` does not exist as
  runtime state anywhere yet - task-ui-05's job).
- **Memory/context reset event(s)** (task-ui-04's job) - `ConversationHistory`
  has no reset method today.

`ModuleId.MEMORY`'s current real-world mapping is trivial: `ConversationHistory`
is an in-process object with no failure mode in v1.0 (no external storage), so
until task-ui-04 adds a reset API, its `ModuleHealth` is always `OK`.

## Test Boundary

`ui_contract.py` is pure data (enums, frozen dataclasses) - no bus, no I/O, no
hardware, no GUI framework. `tests/test_ui_contract.py` covers it directly:
enum membership matches this document's lists, dataclass field defaults, and
immutability (`frozen=True`). This is the full pure-logic surface of this
task card; the event-mapping/gap analysis above is documentation, not code,
and the missing events themselves belong to the task cards that need them
(no state-derivation logic is implemented here - that would pull task-ui-02/
03's work into this card).

## Acceptance Criteria

- [x] Contract is documented in a task/story document before implementation.
- [x] Existing events (`MicSleepToggled`, `ThinkingModeToggled`,
      `ResponseToken`, screenshot/clipboard events) are mapped where relevant.
- [x] Missing events are explicitly listed as implementation requirements.
- [x] Reasoning chunks are excluded from UI events by default.
- [x] Contract includes test boundaries for pure logic.

## Stop Condition

If the existing event bus cannot express the UI contract without broad event
schema changes, stop and update `PROJECT.md`/story boundaries before coding.

Evaluated: not triggered. `bus.py` places no constraint on event shape or
count; every gap listed above is a new, additive event type for a later task
card to publish, not a change to `EventBus` or to any existing event's shape
or existing subscribers.
