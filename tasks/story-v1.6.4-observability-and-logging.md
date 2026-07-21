# Story v1.6.4: Observability - system log and user-facing request log

**Status:** Planned.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.6.4 section, added
2026-07-21 by owner decision from the v1.6.3 review dialog).
**Created:** 2026-07-21.

## User-facing goal

When something goes wrong, there is a durable record to diagnose it
from; and when the user wants to know what Jarvis has been sending to
the model, the console answers in their own language without making
them read engine internals.

## The split this story exists to make

`publish_system_event()` (`src/jarvis/core/system_log.py`) already takes
two different texts and always has:

- `log_message` - detailed, English, engineering audience;
- `ui_message` - what the console's events panel shows.

The intent was there from the start; the wiring is half missing.
`log_message` goes to `logging`, and `logging` is configured by a bare
`basicConfig()` in `app.py` with no file handler - stderr only. Started
outside a terminal, every detailed line is lost. Meanwhile `ui_message`
is a free-form engine string that never passes through the UI language
catalog, so the panel is English no matter what the user picked.

This story finishes the split instead of blurring it:

- **System log** - detailed, English, on disk, rotating. Not a UI
  surface. This is what a user attaches to a problem report.
- **User-facing log** - the console's events panel, in the interface
  language, including a record of what each turn sent to the model.

## Boundaries

- The system log is local-only. It never leaves the machine by itself;
  sending it anywhere is always an explicit human act of attaching a
  file. No telemetry, no upload path, no network sink - the runtime
  locality contract is unaffected because nothing here opens a socket.
- **Content rule, binding for both logs:** record kinds, counts,
  durations, and sizes - never payload content. No transcript text, no
  clipboard text, no image data, no attachment file contents. File
  names are payload-adjacent and stay out of the user-facing log; if
  the system log needs them for diagnosis, that is a deliberate,
  documented decision made in the relevant task card, not a default.
- Hidden mode must not regress. The events panel is not hidden by
  `data-visibility="hidden"` today, which is fine while it carries only
  modality names; any user-facing log entry added here must stay at
  that level of abstraction so the panel never becomes a way to read
  content that Hidden is supposed to conceal.
- The chip strip under the orb (task-v1.6.3-4) stays. A log answers
  "what happened"; the strip answers "what is true right now" and
  survives reconnect. Neither replaces the other.

## Design decisions (agreed 2026-07-21)

- **English is correct for the system log**, and is not a localization
  gap. It is an engineering artifact, not a user-facing string - the
  same rule the project already applies to identifiers, commit
  messages, and technical documentation.
- **The model-request record becomes a typed event**, not a formatted
  string. The engine emits the kind (and duration where it has one);
  the UI localizes it from the existing `last_request_*` catalog keys.
  Sending pre-rendered text would either lose the translation or force
  the engine to know the interface language - both wrong.
- **A UI panel is not a diagnostic tool.** The events panel holds 200
  entries in memory and is cleared on every reconnect; startup crashes
  happen before the window exists at all. Diagnosis is the file's job.

## Scope (ordered task cards)

- `tasks/task-v1.6.4-1-rotating-file-log.md` - durable system log on
  disk with rotation, replacing stderr-only logging.
- `tasks/task-v1.6.4-2-user-facing-request-log.md` - typed
  model-request event, localized in the events panel.
- `tasks/task-v1.6.4-3-docs-and-release-verification.md` - documenting
  the two-log contract and the content rule, plus the human-run check.

## Acceptance criteria

- [ ] A detailed English log exists on disk after a normal run,
      survives process exit, and rotates instead of growing without
      bound.
- [ ] The console's events panel shows, in the interface language, a
      record of what each turn sent to the model, including the
      screenshot modality and audio duration.
- [ ] Neither log contains payload content per the content rule above,
      and an automated test asserts it for the paths this story adds.
- [ ] Hidden mode behavior is unchanged; no new path exposes content
      the Hidden mode conceals.
- [ ] `python -m pytest` and Ruff checks are green; file-log inspection
      and the WebView check are prepared human-run handoffs.

## Stop conditions

- Stop if making the model-request event typed turns out to require
  reshaping `SystemEvent` itself rather than adding a sibling event -
  that touches every existing producer and is a wider decision than
  this story.
- Stop if the durable log cannot be written to the chosen location
  without elevated permissions or without a config decision the owner
  has not made.
- Stop if any log line under discussion cannot be written without
  including payload content. That is a signal the diagnostic need is
  real but the boundary is wrong, and it needs an explicit owner
  decision, not a quiet exception.
