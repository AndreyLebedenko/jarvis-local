# Task v1.9.0-4: Voice-triggered mode switch with intent recognition

**Status:** Implemented. Automated gates green (`python -m pytest` 2320
passed / 1 skipped, `ruff check`, `ruff format --check`). Codex review:
3 P1 + 1 P2 findings in the first pass (probe never reachable in
production - ToolAwareDialog lacked iter_chat; marker accepted inside
prose; no interrupt re-check before set_mode; suppressed command journaled
with no outcome marker), all fixed - re-review: all four RESOLVED, no new
P1/P2. Human-run handoff (below) pending: live voice check with the owner.
**Story:** `tasks/story-v1.9.0-response-modes.md` (scope item 4).
**Depends on:** task-v1.9.0-1 (config field + state), task-v1.9.0-2 (the
`set_mode` path both channels write). This task adds a third channel - voice.

## Summary

Let a spoken command like "switch to voice mode" change the response mode,
while reliably distinguishing that command from ordinary request content that
happens to mention modes ("read me the switch statement, out loud"). The
hotkey and UI (task 2) already ship a working switch; this is the harder,
separable channel. Owner's sketch: a "UX-Aware-Prompt" plus matching result
handlers - pinned down here.

## Read the story's stop condition first

If command-vs-content cannot be separated at acceptable reliability without a
larger addressing/wake-word mechanism, stop: that is a separate story, and the
hotkey+UI switch already ships the feature. Do not grow a wake-word system
inside this card.

## Context you need

- `tasks/story-v1.9.0-response-modes.md` "Voice toggle needs intent
  recognition" design note: the command must be told from request content by
  construction, not guessed post-hoc.
- `src/jarvis/dialog/response_mode.py` (task 1) `ResponseModeState.set_mode`:
  the single write path a recognized voice command routes into, with
  `source="VOICE"` on the change event so the UI/logs attribute it correctly
  (same `source` discipline as `ReasoningLevelChanged`).
- `src/jarvis/app.py` `_start_turn` / the request-intake seam: where a turn's
  user input is first available and where a recognized mode-switch command must
  be intercepted *before* it is dispatched as a normal request, so a switch
  command does not also produce a spoken or text answer to the "request".
- The system-prompt composition (`_compose_effective_system_prompt`, app.py:230)
  and `PromptSettings`: the "UX-Aware-Prompt" directive lives alongside the
  other prompt sections. Pin down its exact contract in this card: what the
  model must emit so a switch intent is machine-recognizable (e.g. a structured
  marker the result handler parses) versus normal content it must pass through
  untouched.
- Existing structured-output precedents in the codebase (e.g. speech-markup
  parsing, tool-call presentation) for how a machine-readable marker is parsed
  out of model output without leaking into TTS or the shown text.

## Boundary

- Only the voice channel. No change to the hotkey/UI channels or the mode
  semantics from tasks 1-3.
- Reuses tasks 1-2's config field and `set_mode`; no new persisted field.
- No wake-word / addressing subsystem. If reliability needs one, stop (above).
- A recognized switch command changes the mode and does not leak a spurious
  answer; an unrecognized/ambiguous utterance is treated as normal content
  (fail safe toward "it was a request", never toward silently swallowing it).

## Requirements

- A "UX-Aware-Prompt" directive (a `PromptSettings` section) that makes the
  model mark a mode-switch intent in a machine-parseable way, distinct from
  request content.
- A result handler that parses that marker, routes a recognized switch into
  `ResponseModeState.set_mode(..., source="VOICE")`, and suppresses the
  normal request dispatch for that utterance; content without the marker flows
  through unchanged.
- The switch intent must not leak into shown text or TTS output.

## Verification

- `python -m pytest`, `ruff check`, `ruff format --check` green.
- Pure tests: the result handler recognizes a marked switch and calls
  `set_mode` with `source="VOICE"`; content mentioning modes without the
  marker is passed through as a normal request (no false switch); the marker
  never reaches shown text or TTS; ambiguous input fails safe to "request".
- Human-run handoff (live model + mic, per Testing protocol): spoken "switch to
  <mode>" reliably changes the mode and is distinguished from a request that
  merely talks about modes. Prepare exact phrases and steps; do not run these
  yourself. If live reliability is unacceptable, invoke the stop condition and
  report rather than adding a wake-word mechanism.

## Acceptance criteria

- [ ] A spoken mode-switch command changes the mode and is reliably
      distinguished from request content; no spurious answer is emitted for the
      command.
- [ ] The switch marker never leaks into the shown text or the spoken output.
- [ ] The voice channel writes the same persisted field as the hotkey/UI.
- [ ] Pure tests and `ruff` gates green; the live voice-intent handoff is
      prepared, or the stop condition is invoked with a written rationale.

## Design decisions (confirmed by owner, 2026-08-30)

- **Non-dialog probe pass over the turn's own audio (the "UX-Aware-Prompt"
  made concrete).** Voice arrives as raw audio the dialog model itself
  transcribes; there is no text to inspect before dispatch. The only
  construction that separates "switch to voice mode" from ordinary content
  mentioning modes is a short additional backend pass: the probe's system
  message (the configured directive) tells the model to answer either with
  one exact marker (`SWITCH_RESPONSE_MODE=<mode>`) or with an explicit
  proceed token, and the result handler (jarvis.dialog.voice_intent.py's
  parse_mode_switch_marker) acts only on the whole reply being exactly the
  one marker line. Everything else - prose, near-misses, unknown mode
  values, multiple lines - fails safe to "it was a request".
- **Probe is transcription-style, never a dialog turn.** It runs the
  backend's raw streaming iterator (ToolAwareDialog.iter_chat, a passthrough
  added in this task) directly - never backend.chat(), whose ResponseToken
  publications would feed probe chatter to TTS and the runtime orb. Same
  isolation rule as OllamaTranscriptionBackend and the annotation backend.
- **Off by default.** The directive lives in `PromptSettings.
  voice_intent_directive` (config `[prompts].voice_intent_directive`,
  default None). None (or blank) means no probe runs and voice turns are
  byte-identical to pre-task-4 behavior. Confirmed with the owner: the
  probe adds a short pass over every voice utterance, so it is an opt-in -
  unlike response_voice/response_text_voice, it gets no built-in default.
- **The recognized command drives the same live path as the hotkey/UI:**
  `ResponseModeState.set_mode(..., source="VOICE")` - session-only since
  task 3b, never touching config.ui.toml. On success the utterance is
  journaled as an assistant event with empty text and the new
  `TurnOutcome.MODE_SWITCHED` outcome (an obeyed command is neither
  interrupted nor failed), and no request dispatch happens for it.
- **Interrupt race closed by re-check:** the probe runs outside
  _active_chat_task (not interrupt-cancellable directly), so after the
  probe and before set_mode the gate re-checks interrupt_requested - a
  late marker can never mutate the mode for an already-cancelled turn.
- **Stop condition not invoked.** Command-vs-content separation is by
  construction (exact marker shape), no wake-word mechanism added.

## Implementation summary (2026-08-30)

- `src/jarvis/dialog/voice_intent.py` (new): PROBE_USER_INSTRUCTION,
  `build_probe_messages(directive)`,
  `parse_mode_switch_marker(text)` (exact-shape: stripped reply must be
  exactly `SWITCH_RESPONSE_MODE=<known mode>`),
  `intent_directive_from_settings(settings)` (None/blank = off).
- `src/jarvis/core/config.py`: `PromptSettings.voice_intent_directive
  : str | None = None`; @file reference resolution added to
  _build_prompts_section's field list (same mechanism as the other
  optional prompts).
- `src/jarvis/dialog/tool_presentation.py`: ToolAwareDialog gained
  `iter_chat()` - a raw streaming passthrough to the transport for
  non-dialog passes (the probe), bypassing the tool loop and ResponseToken
  publication.
- `src/jarvis/journal/events.py`: `TurnOutcome.MODE_SWITCHED` -
  an obeyed mode-switch command's journal outcome.
- `src/jarvis/app.py`: `Orchestrator._run_voice_intent_gate()` (called
  from _start_turn after TurnAccepted/thinking cue, before any ordinary
  dispatch: non-voice sources and unset directive return False
  immediately; recognized marker -> set_mode(source="VOICE") + history
  note + journal entry (empty text, MODE_SWITCHED outcome) + listening
  cue + busy clear + TurnCompleted) and `_run_voice_intent_probe()`
  (raw iter_chat, reasoning off, collects reply locally, never publishes
  ResponseToken/ResponseComplete; any exception returns None - fail safe
  to request). `_MODE_SWITCH_HISTORY_NOTE` system note keeps a later
  turn's history coherent (command obeyed, not answered).
- `src/jarvis/ui/status_console_ui/strings.js`: `journal_outcome_mode_
  switched` (en+ru) - rendered by the existing journal_outcome_* mechanism.
- Tests: `tests/test_voice_intent.py` (pure parser/contract, 17 tests);
  `tests/test_main.py` voice-intent section (probe before dispatch,
  reasoning off via iter_chat, recognized switch w/ source=VOICE event,
  suppressed-turn teardown incl. journal outcome, mode-switch history
  note, probe failure fails safe, non-marker and near-miss pass through,
  interrupt-during-probe race); `tests/test_tool_presentation.py`
  iter_chat passthrough; `tests/test_config.py` extended by the existing
  parametrized prompt tests' field name (voice_intent_directive follows
  the same contract literal/reference/empty rules).

## Human-run handoff (prepared; hardware/live-model, do not run in CI)

Live model + microphone per the Testing protocol. Launch Jarvis with
`python -m jarvis --status-console` (or your usual entry point) after
opting in: set `[prompts] voice_intent_directive` in `config.toml` to the
built-in default below (the feature is OFF without it), then restart.
Reference: `PromptSettings.voice_intent_directive`, default None -
`src/jarvis/core/config.py:~690`. If a turn (probe or answer) hangs and
you need to cancel it, press **Ctrl+Alt+I** (`hotkeys.interrupt`, default
`src/jarvis/core/config.py:134`; may be overridden by `[hotkeys]
interrupt` in config.toml). The directive text that turns the feature
on (paste into `[prompts]` in config.toml, one line):

    voice_intent_directive = "Это системная инструкция для классификации
    голосовой команды. Если аудио - команда сменить режим ответа,
    ответь ровно одной строкой SWITCH_RESPONSE_MODE=<text|voice|
    text_voice> (text - только текст, voice - только голос, text_voice
    - текст и голос). Если это НЕ команда смены режима, ответь ровно
    словом PROCEED. Никакого другого текста."

1. **Command switches the mode.** Say "переключись на голосовой режим".
   Expect: no spoken/text answer to the command (the events panel shows
   the VOICE-source response-mode change; the Status-tab mode buttons
   highlight "Voice"). The journal shows your voice utterance plus an
   assistant entry labeled "Mode-switch command - obeyed, no answer was
   needed." / "Команда переключения режима - выполнена, ответ не
   требовался." - and `config.ui.toml` stays byte-identical (live value
   only, same as task 3b).

2. **Content is not mistaken for a command.** Say something that merely
   mentions modes, e.g. "расскажи, какие режимы ответа существуют, и
   подробно про голосовой режим". Expect: a normal spoken answer to the
   question; the mode buttons DO NOT move.

3. **Marker never leaks.** In both cases above, confirm nothing in the
   spoken reply or on screen contains "SWITCH_RESPONSE_MODE" or
   "PROCEED".

4. **Reliability sample.** Repeat steps 1-2 a few times each (say, 3x
   per phrase, one fresh phrase per repeat). Report: per-phrase outcome,
   any false switch (a request treated as a command - unacceptable),
   any command that leaked an answer (unacceptable). If reliability is
   unacceptable per the story's stop condition, report back - do not
   expect a wake-word mechanism here.

5. **Opt-out still works.** Remove the `[prompts].voice_intent_directive`
   line, restart: a voice turn behaves exactly as before task 4 (no
   probe request in the log, no mode change from spoken commands).
