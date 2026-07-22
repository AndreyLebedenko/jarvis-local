# Task v1.6.4-4: The system log's record of a turn's request

**Status:** Completed. Verified by the human on 2026-07-22 through
the combined v1.6.3 + v1.6.4 checklist in
`tasks/done/task-v1.6.4-3-docs-and-release-verification.md`.
**Story:** `tasks/done/story-v1.6.4-observability-and-logging.md`
**Depends on:** tasks v1.6.4-1 (the file sink) and v1.6.4-2 (which found
this gap and could not close it inside its own boundary).
**Created:** 2026-07-22 (owner decision on task-v1.6.4-2's "Found, not
fixed here").

## Why this card exists

Task v1.6.4-2 was written on the assumption that a turn's request
already produced a detailed English line in the system log, and that the
remaining work was the localized UI half. It did not.
`ModelRequestStarted` is published straight onto the bus in `app.py` and
never passes through `publish_system_event()`.

That inverted the story's premise: after task 2 the console panel could
answer "what did this turn send", while the file - the artifact a user
actually attaches to a problem report - could not. The story's whole
point is that diagnosis is the file's job and the panel is not a
diagnostic tool.

## Outcome

`jarvis.core.model_request_log.model_request_log_message()` renders one
English line from a `ModelRequestStarted`, and `app.py` writes it with
`logger.info()` at the publish site, immediately before the bus publish
and therefore before `backend.chat()`.

**Why not `publish_system_event()`.** That function's guarantee is that
one occurrence reaches both the file log and the events panel together.
A model request is the one case where that guarantee has the wrong
shape: task-v1.6.4-2 already gives the panel a typed, localized entry,
so routing the same fact through `publish_system_event()` would render
every turn twice - once localized, once as a raw English diagnostic. The
two halves are produced separately on purpose, and the comment at the
call site says so, because the next reader's first instinct will be to
"fix" it into the shared helper.

**Why a separate module rather than `system_log.py`.** `system_log.py`
documents itself as the single call that always does both jobs together.
A sibling function inside it that deliberately does only one would
falsify that module's stated invariant for every future reader.
`model_request_log.py` is small, has no bus or UI dependency, and is
directly unit-testable.

**Why before the backend call.** A request that hangs or crashes the
backend is precisely the case the file log exists for. A line written
after the call returns is absent exactly when it is needed.

**Log source tag** is `LLM`, matching the `[SOURCE] message` shape
`publish_system_event()` already writes, so the file reads uniformly
even though this line arrives by a different path.

## Boundary

- One new log call site and its formatter. No change to
  `ModelRequestStarted`, to `publish_system_event()`, to the events
  panel, or to the chip strip.
- Content rule applies in full: modality kinds, their count, and the
  audio duration. No transcript, no clipboard text, no attachment file
  names, no media bytes or sizes.
- No re-levelling of existing log lines; INFO matches the level the
  equivalent panel entry carries.

## Acceptance criteria

- [x] The file log contains one line per accepted turn naming the
      request's modalities, their count, and the audio duration when
      there is one.
- [x] Automated tests cover the formatter for every `ModelRequestInput`
      value, the empty-input case, the audio and non-audio paths, that
      the line is written before the backend call, and that clipboard
      text present in the turn never appears in the line.
- [x] The events panel still shows exactly one entry per turn - the
      localized one from task-v1.6.4-2, not a second English diagnostic.
      Covered by the existing panel tests, which no new producer touches.
- [x] A human-run check confirms the line appears in `logs/jarvis.log`
      for a real turn of each modality.
- [x] `python -m pytest` and Ruff checks are green.

## Human verification handoff

Folded into the combined v1.6.3 + v1.6.4 checklist in
`tasks/done/task-v1.6.4-3-docs-and-release-verification.md`, section
"System log". Running it separately would mean opening the same log file
twice for the same session.
