# Task v1.9.0-3: Mode 3 second pass + first-pass TTS suppression

**Status:** Completed. Automated logic tests green (`python -m pytest`: 2277
passed, 1 skipped; `ruff check`, `ruff format --check` clean). Structured
`/code-review high` (8 angles, 10 ranked findings) plus an independent Codex
second-opinion pass on the same findings, then a final `/codex:review`
working-tree pass (no further findings): 6 findings fixed and re-verified
(interrupted-derivative journal tagging without misusing `TurnOutcome`,
derivative-pass busy-clearing race, empty-derivative-text UI guard, a stale
exception comment, the duplicated pass-audibility flag, `pass_kind` promoted
to an `Enum`); 1 refuted by Codex (reentrance safety - already structurally
enforced by `claim_turn_end()`, not just documented); 1 closed as by-design,
not a bug (events-panel ring-buffer cost of logging the derivative pass -
required by this card's own "Second-pass logging" decision below); 2 left
open and unresolved for a follow-up decision (CLAUDE.md 7.4 task-id
references in production comments; a small precedence-duplication in
`transport.py`) - see the bug report and this session's own record for
detail. Human-run mode-3 audio-timing handoff prepared below; not yet run.
Merged to `main`.
**Story:** `tasks/story-v1.9.0-response-modes.md` (scope item 3). The load-
bearing slice.
**Depends on:** task-v1.9.0-1 (the `text_voice` mode and its contract seam),
task-v1.9.0-2 (a way to actually select the mode for manual verification).

## Summary

Make `text_voice` (mode 3) two-pass. Pass 1 produces the canonical rich text,
streamed to the screen as today. Pass 2, with **reasoning off**, takes that
*exact shown text* as input and produces a spoken derivative under the
spoken-derivative contract (may reference visible content). In mode 3 the
first pass's sentence-buffered streaming TTS is muted - only the derivative is
spoken; the screen still streams the first pass immediately. The derivative is
persisted *additively inside the same turn's journal record* (not a second
turn, not a new event) and rendered as a collapsed "spoken aloud >" block
under the reply. The derivative is kept out of the retrieval/memory corpus.

Post-implementation interpretation, owner-approved 2026-08-30: mode 3 is a
text canvas plus spoken commentary/log, not duplicate output. The first pass is
the authoritative canvas for retrieval, memory, annotation source material, and
future reasoning. The second pass is a lossy spoken guide to that canvas. This
is a deliberate quality-for-latency feature: it spends an extra local backend
pass so the user can inspect the rich answer and hear Jarvis talk through it.
If a later indexer helps a user find a turn by words they remember hearing, it
must be locator-only and hydrate the canonical canvas, not treat the spoken
derivative as standalone memory.

## Design: playback directive on the expected-response metadata (owner)

Do NOT branch `TtsOutput` on the response mode. Instead extend the
expected-response metadata - the `ModelRequestStarted` event published the
moment a request is successfully dispatched to the backend
([app.py:1089](../src/jarvis/app.py)) - with a **playback directive** for the
response that dispatch expects. `TtsOutput` reads the directive; it never
learns about modes.

- The directive is derived from the active response mode at the same seam
  where `reasoning_level` is snapshotted for the turn
  ([app.py:928-935](../src/jarvis/app.py)) and threaded down into
  `_dispatch_backend_request` exactly parallel to `reasoning_level`. This
  freezes it per-turn: a mode toggle mid-turn does not retarget the in-flight
  turn's audio, matching the existing "applies to the next turn" contract.
- The field always carries an explicit value with a documented default; it is
  NOT a nullable "is a directive present". Absence / the default value means
  today's behavior (speak the streaming pass), so modes 1 and 2 and any
  un-tagged caller stay byte-identical. Suggested shape: a small
  `speak_streaming: bool` (default `True`) or a `PlaybackDirective` enum if a
  third state is foreseeable; pick the minimal one that covers mode 3.
- **Mode 3 then falls out of two ordinary dispatches, not a bolted-on mute.**
  Pass 1 dispatches with the directive "do not speak the streaming pass";
  pass 2 (the derivative) is a *second* dispatch that emits its *own*
  `ModelRequestStarted` with the directive "speak the streaming pass", over
  the derivative text with `reasoning_level=OFF`. The derivative is spoken
  through the unchanged TTS path. There is no mode-specific code inside
  `TtsOutput` at all - only a single entry gate that honors the latched
  directive.

Two invariants the implementation must nail (consequences of the above, not
optional polish):

- **Directive-to-token-stream latch/order.** `ModelRequestStarted`,
  `ResponseToken`, and `ResponseComplete` carry no turn id; they are serialized
  by the single active turn and the shared playback channel. `TtsOutput` must
  latch the directive from the most recent `ModelRequestStarted` and apply it
  to the token stream that follows. "Dispatch precedes streaming" is true today
  ([app.py:1105](../src/jarvis/app.py) publishes before the chat task at
  `:1118`); pin it as an explicit invariant the gate relies on, not a
  coincidence.
- **Second-pass logging.** The derivative pass emits a real
  `ModelRequestStarted` and reaches the events panel and file log like any
  request. That is honest (a real inference call), but tag it as a
  sub-pass (e.g. `pass=derivative`) so it is not mistaken for a second turn in
  the panel.

## Read the story's stop conditions first

Two of them gate this task; check both before implementing:

- **Second pass needs the complete first-pass text.** If the pipeline has no
  point where the full final first-pass text is available before TTS would
  otherwise begin, stop - that is a pipeline-shape problem. (Preliminary read:
  `App.on_response_complete` (app.py:1153) already receives `full_text` and is
  where `record_assistant(full_text)` runs, so the complete text *does* exist
  at a single seam. Confirm this is the right hook for launching pass 2.)
- **First-pass TTS suppression must be a localized gate.** The directive design
  above is meant to make this a single entry gate in `TtsOutput`, not a rework
  of sentence buffering. If `TtsOutput`'s structure does not permit such a
  clean entry gate and honoring the directive would force reworking the
  sentence-buffering contract shared with modes 1 and 2, stop.

## Context you need

- `src/jarvis/app.py:1153` `App.on_response_complete`: `full_text` +
  `_history.add("assistant", ...)` + `_journal_recorder.record_assistant(...)`.
  This is the natural hook for the mode-3 second pass and for attaching the
  derivative. `record_aborted_turn` (`:1165`) is the aborted-turn twin - decide
  whether an aborted mode-3 turn skips the second pass (it should: no audio to
  speak if the turn was interrupted).
- `src/jarvis/app.py:1051-1122` `_dispatch_backend_request` and its
  `ModelRequestStarted` construction (`:1089`): the expected-response metadata
  gains the playback-directive field (see the Design section). The second pass
  is a second call through this same path, carrying its own directive.
- `src/jarvis/app.py:928-935`: where `reasoning_level` is snapshotted from
  runtime state for the turn; the playback directive is derived from the active
  response mode at the same seam and threaded down parallel to it.
- `src/jarvis/app.py:1120` the backend chat call with `reasoning_level=`: the
  second pass calls the same backend with `reasoning_level=ReasoningLevel.OFF`
  and the spoken-derivative contract as system prompt, messages = the exact
  first-pass text. It is a pure form transformation, not a re-derivation.
- `src/jarvis/audio/tts.py:333` `TtsOutput` (streaming sentence-buffered TTS,
  driven by `ResponseToken`/`ResponseComplete` on the bus): gains a single
  entry gate that latches the current turn's playback directive from the last
  `ModelRequestStarted` and honors it. It does NOT learn about response modes.
- `src/jarvis/audio/tts_mute.py` `TtsMuteState`: the WRONG tool for this - it
  is a global runtime mute for all modes, with no per-turn granularity. The
  first-pass suppression rides the per-turn directive instead (Design section);
  do not overload `TtsMuteState`.
- `src/jarvis/journal/recorder.py:88` `record_assistant` and
  `src/jarvis/journal/events.py:114` `JournalEventRecord`: extend the assistant
  record with an optional `spoken_derivative` field *additively* - same event,
  same turn, append-only journal invariant preserved. No new event type, no
  phantom duplicate turn.
- The retrieval/memory corpus feed (history/memory indexing path): confirm the
  derivative is never indexed. Only the canonical first-pass text reaches
  history and the retrieval/memory corpus, exactly as today.
- `src/jarvis/ui/status_console_ui/`: the chat-log reply rendering. Add the
  collapsed "spoken aloud >" block, always present when a derivative exists,
  expandable on click. i18n label in `strings.js`. Mind the `file://`
  sub-resource cache (CLAUDE.md note 7).
- `tasks/done/story-v1.8.2-replay-tts.md`: the Play control is NOT here. This
  task only persists the derivative *text*; replay retargets to it later. No
  playback control added by this card.

## Boundary

- Only mode 3 changes behavior. Modes 1 and 2 keep their single-pass behavior
  exactly - they carry the default directive (speak streaming).
- The second pass is reasoning-off, form-only, over the exact first-pass text.
  It must not re-read the request or re-derive content.
- First-pass suppression is expressed as the per-turn playback directive on the
  metadata + a single `TtsOutput` entry gate - not a rewrite of sentence
  buffering, not a reuse of the global mute, not a mode branch inside
  `TtsOutput`.
- Persistence is additive inside the existing assistant record. No second
  turn, no new journal event, derivative excluded from retrieval/memory.
- No Play/replay control (story-v1.8.2 owns that and retargets later).

## Requirements

- Extend the expected-response metadata (`ModelRequestStarted`) with a
  playback directive carrying an explicit default (= speak streaming); derive
  it from the active response mode at the reasoning-level snapshot seam and
  thread it through `_dispatch_backend_request`.
- `TtsOutput` latches the directive from the most recent `ModelRequestStarted`
  and honors it at a single entry gate; the "dispatch precedes streaming"
  ordering it relies on is pinned as an explicit invariant.
- In mode 3, after the first pass's full text is available, run a second
  backend pass with `reasoning_level=OFF` and the spoken-derivative contract,
  input = the exact first-pass text; it is a second dispatch carrying the
  "speak streaming" directive, tagged as a derivative sub-pass in the log.
  The screen still streams the first pass immediately; only the second pass is
  spoken.
- Persist the derivative additively in the turn's assistant journal record;
  keep the append-only invariant; keep the derivative out of the
  retrieval/memory corpus.
- Render the derivative as a collapsed, expandable "spoken aloud >" block under
  the reply, always present when a derivative exists.

## Verification

- `python -m pytest`, `ruff check`, `ruff format --check` green.
- Pure tests: the playback directive is derived correctly per mode and
  defaults to "speak streaming" for modes 1/2 and un-tagged callers;
  `TtsOutput` honors a "do not speak streaming" directive (pass 1 silent) and a
  "speak streaming" directive (pass 2 spoken), with the latch applied to the
  token stream following each `ModelRequestStarted`; second-pass request
  construction (reasoning off, derivative contract, first-pass text as input,
  derivative sub-pass tag); journal record carries the derivative additively
  and the retrieval/memory feed excludes it; UI renders the collapsed block
  from a record that has a derivative and omits it when absent.
- Human-run handoff (hardware audio timing, per Testing protocol): mode-3
  screen streams the first pass immediately; audio waits for pass 1 to
  complete then speaks the derivative; first-pass TTS is silent; spoken
  references ("as in the table above") match actually visible content. Prepare
  exact steps/commands; do not run these yourself.

## Acceptance criteria

- [x] Mode 3 streams canonical rich text immediately, then speaks a
      reasoning-off derivative built from the exact shown text; first-pass
      streaming TTS is silent in this mode; spoken references correspond to
      visible content. (Pure-test coverage in place; human confirmation
      pending the handoff below.)
- [x] The derivative is persisted additively inside its turn's record and shown
      as a collapsed block under the reply; the append-only journal invariant
      holds; the derivative does NOT enter the retrieval/memory corpus.
- [x] Modes 1 and 2 are behaviorally unchanged by this task.
- [x] Pure tests and `ruff` gates green; the mode-3 audio-timing handoff is
      prepared with exact steps (below).

## Human verification handoff (prepared, not yet run)

Hardware-dependent (real audio playback) - per the Testing protocol, the
agent prepares this and stops; the human runs it and reports back.

Corrected 2026-08-30 before the first run (owner rejected the prepared
version for silently depending on an undocumented hotkey binding; see
`tasks/bug_reports/2026-08-30-handoff-silently-depends-on-undocumented-hotkey.md`):
every hotkey is now named literally, and the mode-switch step no longer
assumes the startup default mode (the mode is persistent).

1. Launch Jarvis normally (`python -m jarvis.app` or the usual entry point)
   with TTS enabled.
2. Switch to mode 3 (`text_voice`), by either channel (both write the same
   state; the config-page drop-down reflects whichever you use):
   - Hotkey: press **Ctrl+Alt+O** (the response-mode cycle hotkey,
     `hotkeys.response_mode_toggle`, default in
     `src/jarvis/core/config.py:140`, `[hotkeys] response_mode_toggle`) -
     repeatedly, checking the "Response mode" / "Режим ответа" drop-down in
     the Status Console's config panel after each press, until it shows
     "Text + voice" / "Текст и голос". The hotkey cycles
     text -> voice -> text_voice -> text; the number of presses depends on
     the currently active mode, which persists across restarts.
   - UI only: pick "Text + voice" / "Текст и голос" directly in that
     drop-down (`responseModeSelect`).
   Confirm the drop-down shows the selected mode.
3. Ask a question whose answer naturally has some visible structure worth
   referencing (e.g. "list three ways to reduce audio latency, briefly").
4. Observe pass 1: the reply streams to the screen immediately, exactly as
   in mode 1. No TTS audio plays while this streams (first-pass TTS is
   silent in mode 3).
5. Observe pass 2: once the on-screen reply has finished streaming, after a
   short pause Jarvis speaks - a shorter, reasoning-off "spoken derivative"
   of the reply, not a re-derivation. If the derivative references visible
   content ("as listed above", "the first option"), confirm it actually
   matches what is on screen.
6. In the Status Console's events panel, confirm two request entries appear
   for this one turn: the primary pass, and a second one tagged as a
   derivative sub-pass (not presented as a second turn).
7. Open the Journal view for this session and confirm the turn's assistant
   entry shows a collapsed "spoken aloud >" block; expanding it shows the
   spoken derivative text.
8. Ask a follow-up question in mode 1 (text) or mode 2 (voice) and confirm
   single-pass behavior is unchanged: one request in the events panel, no
   collapsed derivative block in the Journal.
