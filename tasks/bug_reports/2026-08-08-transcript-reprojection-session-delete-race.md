# Transcript re-projection can resurface a deleted session (race)

**Detected at commit:** 10df02b (task v1.8.0-23 slice 1).
**Component:** `src/jarvis/journal/lifecycle.py` - transcript re-projection path
(`_on_transcript_overlay_changed` / `_reproject_transcript_event`).
**Severity:** low-probability data-correctness race; not user-reported.

## Symptoms

After a session is deleted, its transcript-derived corpus/FTS/semantic rows can
reappear, so retrieval and Journal search may return content from a session the
user deleted. Requires a `TranscriptOverlayChanged` re-projection to be in
flight at the same moment the session is deleted.

## Suspected cause

`_reproject_transcript_event` reads the raw source event and writes the derived
corpus/semantic rows as two separate `asyncio.to_thread` steps:

1. `read_event(reference)` (off-thread), then
2. `self._project_event(record)` (off-thread).

`JournalHistoryService.delete_session` deletes the raw session and then calls
`HistoryProjectionLifecycle.delete_session_projections`, which clears the
derived projections. Nothing serializes that deletion against an in-flight
transcript re-projection. If the re-projection already read the event (step 1)
before deletion cleared the projections, its step-2 write commits the stale
rows back after deletion, so the derived projections again contain the deleted
session.

This is the same class of race fixed for the annotation re-projection path in
this commit, where read+write of one annotation was made a single critical
section under a shared lock that `delete_session_projections` also takes.

## Temporary decision

Left unfixed in task v1.8.0-23. This card's scope is annotation retrieval,
API, and UI; the transcript re-projection path is task v1.8.0-18..20 code that
is already merged and released. Fixing it here would pull released,
out-of-scope code into an annotation slice, against the scope discipline in
AGENTS.md (section 0.3, "a change affects more than expected") and the
task-card boundary rule. The annotation fix already added
`_annotation_write_lock`; extending the same lock (or a shared one) to the
transcript path is a small, mechanical change but belongs in its own change so
its own tests and review cover the transcript projections.

Chosen over the nearby alternative of fixing both paths in this commit because
that alternative widens the diff and review surface of an annotation-scoped
card into the transcript subsystem, and over doing nothing/not recording it
because the race is real and would otherwise be lost.

## Future considerations and boundaries

- Fix: make `_reproject_transcript_event` read the event and project it as one
  critical section under the same lock `delete_session_projections` takes (the
  annotation path is the template), or unify both re-projection paths behind a
  shared serialization helper.
- A regression test should mirror
  `test_deleted_session_does_not_reappear_via_inflight_reprojection`: block a
  transcript re-projection mid-write, delete the session concurrently, unblock,
  and assert the corpus/FTS/semantic rows for that session do not reappear.
- Boundary: this report covers only the delete-vs-reproject race. It is not a
  claim about any other transcript projection behavior, and it does not change
  the released transcript contract.
