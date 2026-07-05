# Task: Clipboard-to-prompt input (clipboard_input.py)

Status: Completed.

Story: [story-v1.1-controlled-input.md](story-v1.1-controlled-input.md)

## Summary

Reads the current clipboard text and turns it into the next user
message - source code and long text that would be unreliable via
screenshot OCR (PROJECT.md's verified OCR-confabulation fact). This is
the first real (non-placeholder) user text in `ConversationHistory`,
since clipboard content is exact and known up front, unlike voice input.

This task also requires refactoring `main.py`'s `Orchestrator`: it
currently has exactly one turn-start path (`on_utterance`), hardcoded
around audio (wav bytes, a fixed history placeholder). Clipboard input is
a second, structurally different kind of turn (real text, no audio, no
media by default). Adding it as a parallel, separate method instead of
factoring out a shared path would duplicate the busy-guard, thinking-cue,
and history-recording logic in two places that must then be kept in sync
by hand - exactly the kind of split that caused the `ResponseComplete`
concurrency bugs found during task-07's review. This must not happen
again for the same reason.

**Scope boundary with task-10 (read this before starting):** this task
builds and unit-tests the clipboard-reading logic, the `ClipboardSubmitted`
event, and the `Orchestrator` refactor - entirely exercised through fakes,
no real hotkey. It deliberately does **not** register a real global
hotkey, does not start any background task in `main.py`'s `run()`, and
does not update `config.example.toml` or run a manual handoff - all of
that is task-10's job, once task-08 and task-09 both exist to wire
together. Keeping this split prevents wiring from starting before the
riskier `Orchestrator` refactor has actually landed and been reviewed.

## Current boundary

In scope:

- A new `clipboard_input.py` module containing: the `ClipboardSubmitted`
  event (carrying the - possibly truncated - text and whether truncation
  happened), and a small class/function that reads clipboard text via an
  injectable read function (defaulting to `pyperclip.paste()`), applies
  the length cap, and builds the event. No hotkey-listening code here yet
  - see the scope boundary above and task-10.
- Clipboard access via `pyperclip`, not Tkinter. Tkinter already caused a
  live thread-safety bug in `capture.py`'s region-select overlay (see
  `tasks/bug_reports/capture-region-select-tkinter-thread-safety.md`);
  reading the clipboard from the same `keyboard`-callback thread via
  Tkinter would risk the same class of failure. `pyperclip` is a small,
  cross-platform dependency that is easy to fake in tests.
- A length cap: new `ClipboardSettings.max_chars` field added to
  `config.py`'s schema (default in the 20000-30000 character range - pick
  one and record the reasoning in `PROJECT.md`, same discipline as
  `request_end_pause_seconds`'s documented default). Text over the cap is
  truncated, not rejected, with a visible in-band marker appended (e.g.
  "[текст обрезан до N символов]") so the model is never handed a
  silently-incomplete document, plus a recoverable-input-error sound cue
  distinct from the clipboard-submission cue (referenced by a new
  `SoundCueSettings` field/key - both exercised via the fake
  `SoundCuePlayer` already used in `main.py`'s tests, real cue file /
  `config.example.toml` entry deferred to task-10).
  Note: adding these fields to `config.py`'s dataclasses (needed for this
  task's own tests) is in scope; updating the checked-in
  `config.example.toml` reference file is not - see the scope boundary
  above. `config.py`'s existing missing-key-falls-back-to-default policy
  means this does not break `test_example_config_matches_documented_
  defaults` in the interim.
- Clipboard turns never attach the pending screenshot (per the story's
  boundary, also recorded in the story's Open decisions since it affects
  UX) - if one is pending when a clipboard submission arrives, it stays
  pending for the next audio turn rather than being consumed or discarded.
- Clipboard turns record the *real* submitted text in
  `ConversationHistory` (not a placeholder), truncated to the same cap if
  applicable.
- Refactor `Orchestrator`: factor `on_utterance`'s shared logic (busy-guard,
  thinking cue, message assembly, `backend.chat()` call, error handling)
  into one internal turn-start method taking the user-facing history text
  and an optional media list, so both the existing audio path and the new
  clipboard path call through it. `on_utterance` becomes a thin adapter
  that decodes wav bytes to base64, attaches any pending screenshot, and
  calls the shared path with the placeholder text; a new `on_clipboard`
  (or similar) adapter consumes a `ClipboardSubmitted` event and calls the
  shared path with the real text and no media.

Out of scope:

- Registering a real global hotkey for clipboard submission, starting any
  background task in `main.py`, updating `config.example.toml`, and the
  manual handoff - all task-10 (see the scope boundary above).
- Non-text clipboard content (e.g. a copied image). Detect and treat as
  the input-error case (empty/unusable clipboard), do not attempt OCR or
  image handling here.
- A UI to preview, edit, or confirm clipboard text before sending.
- Interrupting an in-flight turn to accept a new clipboard submission -
  the existing busy-guard applies unchanged (out of scope per the story).
- ASR/transcription; echo cancellation.

## Dependencies

`bus.py` (task-01), `config.py` (task-02, schema additions only - see
above), `main.py`'s `Orchestrator` (task-07 - this task modifies it
directly, not just wires around it).

## Acceptance criteria

Automated tests (fakes/mocks only, no real clipboard access, no real
hotkey, nothing started in `main.py`'s runtime):

- The shared turn-start path is exercised by both a simulated audio
  utterance and a simulated clipboard submission, confirming busy-guard,
  thinking cue, and history recording behave identically in shape for
  both (only the history text/media differ).
- A clipboard submission longer than `max_chars` is truncated, gets the
  in-band marker appended, and triggers the input-error cue - confirmed
  with a fixture string and a fake clipboard-read function, no real
  clipboard needed.
- A clipboard submission does not attach a pending screenshot; a
  subsequent audio utterance still gets it (screenshot survives a
  clipboard submission that arrived first).
- Config parsing test for `ClipboardSettings.max_chars` and the new sound
  cue field(s), following `config.py`'s existing validation style
  (unknown key rejected, partial section falls back to defaults).

No manual handoff in this task - see task-10.

Review found three real bugs, all fixed with regression tests confirmed
to fail without the fix and pass with it: `on_utterance()`/`on_clipboard()`
consuming the pending screenshot / playing the clipboard ack cue before
checking `_busy`, losing a screenshot or giving false feedback on a turn
the busy-guard would go on to reject; and a mojibake truncation marker,
switched to ASCII (consistent with CLAUDE.md's ASCII-preference rule and
a real encoding incident hit live during review).
