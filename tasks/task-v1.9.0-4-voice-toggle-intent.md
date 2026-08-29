# Task v1.9.0-4: Voice-triggered mode switch with intent recognition

**Status:** Proposed. Not started.
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
