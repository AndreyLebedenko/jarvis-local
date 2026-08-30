# Backlog: In-flight status indicator for the reply-render gap before the journal entry lands

**Status:** Open. Not blocking.
**Source:** Owner's manual verification of
`tasks/done/task-v1.9.0-3-mode3-second-pass-and-tts-suppression.md`
(2026-08-30). Playtest quality/speed judged good; this is a cosmetic
observation filed for later consideration, not a defect in that task.

## Summary

During the mode-3 handoff run, the chat-log entry for the assistant's reply
did not appear on screen until close to when the derivative ("деривация")
pass started - i.e. the events panel showed `Текстовый ввод` at 17:30:46 and
`деривация` at 17:31:05, and the reply text rendered around the same time as
the second line, not incrementally as the first pass streamed. Between those
two events there is no visible sign that anything is happening.

## Context

- `status_console_ui/app.js` renders chat-log entries from journal events
  (`event.role === "assistant"`, see `app.js:2478` and the
  `record_assistant()`-sourced `event.metadata.outcome` handling around
  `app.js:3518-3542`), not from a live per-token stream. The journal entry for
  a turn is only built once the full reply text is assembled
  (`App.on_response_complete` -> `record_assistant(full_text)`,
  [app.py:1267-1276](../../src/jarvis/app.py)), which for mode 3 lands close
  to when the derivative sub-pass dispatches
  ([task-v1.9.0-3](../done/task-v1.9.0-3-mode3-second-pass-and-tts-suppression.md)).
  That the chat log renders from the finished journal object rather than the
  live token stream is the owner's own read of the cause, and matches what
  `app.js` does; this backlog item does not require re-deriving it further.
- This is not specific to mode 3 - any turn has the same gap between
  dispatch and the journal entry appearing - but mode 3's extra pass makes
  the gap long enough to notice.
- The events panel itself already shows activity (`В МОДЕЛЬ` rows), so the
  gap is only "invisible" from the chat-log/reply-area point of view, not
  from the events panel.

## Current Boundary

- Not blocking any open task or story.
- This is about adding a lightweight in-flight indicator, not about making
  the chat log stream tokens incrementally - the owner did not ask for
  streaming rendering, only for some sign of activity during the existing
  gap.
- Whatever indicator is chosen should not be tied to the log window
  specifically - the owner suggested alternatives such as animating the
  `.brand-mark` ("J" icon, [index.html:62](../../src/jarvis/ui/status_console_ui/index.html:62))
  or showing byte/exchange statistics for the in-flight request.

## Possible Approaches

- Animate `.brand-mark` (or add a small activity dot/spinner near it) while
  a request is outstanding, driven by the existing `ModelRequestStarted` /
  `ResponseComplete` events already reaching the UI transport.
- Show a lightweight byte-count or elapsed-time readout for the in-flight
  request somewhere in the topbar, sourced from the same events.
- Confirm exactly which UI transport event(s) the frontend already receives
  between request start and journal-entry arrival, so the indicator can be
  wired to real state instead of a client-side timer guess.

## Acceptance Criteria

- [ ] Some visible indicator (icon animation, stat readout, or similar) shows
      activity between a request's `ModelRequestStarted` and the chat-log
      entry appearing, without changing chat-log rendering to be
      token-incremental.
- [ ] The indicator works for ordinary single-pass turns too, not only mode
      3 (the gap exists there as well, just shorter).
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` green.

## Stop Conditions

- If closing this gap turns out to require making the chat log stream
  tokens incrementally (rather than adding a separate indicator), stop and
  confirm with the owner first - that is a larger rendering-model change
  than what was asked for here.
