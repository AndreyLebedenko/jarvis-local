# Edited annotation not recalled from a fresh context shortly after save

**Detected at commit:** 3bc2dd0 (task v1.8.0-23 slice 4, uncommitted UI changes
on top)
**Status:** Closed, 2026-08-08. The race mechanism is confirmed real (see
"Determination" below) and no code change was made for it, but the owner
manually replayed the exact original scenario after task v1.8.0-26 landed
(see "Owner reverification") and it no longer reproduces. Root cause between
the two candidate explanations remains formally undetermined - the
"Measurement handoff" and "If a recurrence is observed" follow-ups in "Future
considerations" stay valid and should be picked up if this resurfaces - but
the reported symptom itself is gone, which is what this report tracks. Full
record in `PROJECT.md`'s "Retrieval-quality regression (task v1.8.0-26)"
entry.

## Owner reverification (2026-08-08)

Owner manually repeated the exact reported repro - edit an annotation via the
PUT-backed UI, then within roughly the same order-of-magnitude gap open a
fresh context and ask about the edited content - and confirmed correct
recall. No code changed between the original miss and this retest (task 26
added tests/docs only, per its own boundary and the determination above), so
this is evidence the symptom is not persistently reproducible, not evidence
of what fixed it. Consistent with the determination's mild lean toward the
original incident being a one-off (transient race timing or a marginal
ranking call) rather than a standing defect.

## Determination (task v1.8.0-26)

`tests/test_retrieval_quality_regression.py::test_annotation_edit_reprojection_race_is_real_and_bounded_by_wait_for_idle`
gives a deterministic repro: the PUT-edit/reprojection race (explanation 1
below) is real today, upgraded from suspected to confirmed. `AnnotationOverlayChanged`
publish only schedules `HistoryProjectionLifecycle._run_annotation_reprojection`
as a background task and returns; a retrieval query issued before that task
runs can miss an edit the PUT handler already reported as saved.

**What this task cannot determine: the window's real-world duration.** An
unforced repro (same flow, no artificial block on reprojection) found the
edit already searchable *immediately* after publish, but that only shows the
in-process SQLite writes are cheap - it says nothing about the live path,
which this task's pure-suite scope (no live Ollama, network, or hardware,
per the card's requirements) cannot exercise. The only existing latency
numbers in `PROJECT.md` (~85-235 ms warm-to-cold-start) are the task-8
*query*-embedding measurement - a different call site (short benchmark query
text, retrieval-time) from the one this race actually depends on
(`AnnotationSemanticIndex.reproject_annotation`, which embeds the full
annotation *passage*, up to the 20,000-char overlay limit, under
`_annotation_write_lock` alongside session-deletion and other pending
reprojections). Reusing the query-embedding figure to bound the reprojection
window, as an earlier version of this report did, was an unsupported
extrapolation across call sites and has been retracted. No measurement of
passage-reprojection latency under realistic load exists yet.

**Conclusion:** the race is confirmed to exist exactly as suspected, which is
new, solid evidence for explanation 1; the task-26 annotation semantic/lexical
retrieval slices additionally show no ranking defect on their own held-out
queries (all recall/precision 1.000), which is at least mild evidence against
a *systemic* ranking problem, though a 9-query synthetic benchmark cannot
disprove one specific historical miss. Neither explanation is ruled out, and
attribution of the original ~1-minute-gap incident stays open. A fix (e.g. the
PUT handler awaiting reprojection completion) is not implemented here either:
a properly scoped fix would await only *this* annotation's reprojection, not
every pending lifecycle task (a blanket `wait_for_idle()` would block the HTTP
response on unrelated work, against decision 6's predictable-latency goal),
and building that per-annotation wait means adding new lifecycle plumbing -
exactly what this card's stop conditions bar ("stop if fixing failure requires
reopening settled lifecycle or wiring"). See "Future considerations" for the
concrete, scoped follow-up.

## Symptoms

Manual playtest during slice 4 UI verification, session
`20260803-225905-3aec72` ("song about Astartes" conversation):

1. Generated a range annotation for events 3-4 (whole-session annotation for
   this session pre-existed from earlier browsing).
2. Edited the annotation text via the new PUT-backed textarea/save UI,
   replacing "воин" with "Астартес"; save returned success.
3. Within roughly a minute, opened a brand-new empty context and asked
   "Я имею в виду мою песню про Астартес, которую мы обсуждали ранее. Ты
   помнишь?"
4. Jarvis reported no memory of the song at all - not a partial match, a full
   miss - and asked the user to resend the lyrics.

A comparable smoke test earlier the same session (asking a fresh context
about "аннотации (v1.7.0)", relying on a freshly-generated whole-session
annotation on an unrelated old session) *did* recall correctly, so retrieval
of freshly generated/edited annotations is not universally broken - this is
either a narrow race or a ranking miss specific to this query/session pair.

## Suspected cause

Two candidate explanations, not distinguished yet:

- **Reprojection race.** The PUT edit handler
  (`src/jarvis/ui/transport.py:1334`) does `await self._bus.publish(
  AnnotationOverlayChanged(...))` and returns "ok" as soon as publish
  returns. The subscriber
  (`HistoryProjectionLifecycle._on_annotation_overlay_changed`,
  `src/jarvis/journal/lifecycle.py:436-450`) only schedules a background task
  (`_run_annotation_reprojection` -> `_reproject_annotation`) and returns
  immediately; it does not block `publish()` until lexical+semantic
  reindexing (which calls out to Ollama for the embedding) actually
  completes. If the query in the new context landed before that background
  task finished, the edited annotation would not yet be searchable. This
  would be a real defect in slice 4's contract ("Projection updates are
  lifecycle-owned") if reindexing latency routinely exceeds the gap between
  save and next query.
- **Out-of-scope ranking miss.** Fusion/ranking quality for the hybrid
  surface is explicitly card 26's territory (task 23's current boundary
  excludes "Selector anti-pollution ranking (card 16)" and "the
  retrieval-quality regression (card 26)"). "мою песню про Астартес, которую
  мы обсуждали ранее" may simply not have scored high enough against other
  candidates for this cold-start context, independent of any race.

No server log was captured for this specific interaction (only the earlier
502/backend-down traces were saved), so neither explanation is confirmed.

## Temporary decision (superseded by the task-26 determination above)

Task v1.8.0-23's original deferral - do not investigate inside that card,
revisit at task 26 - is done: task 26 confirmed the race mechanism is real.
What task 26 could not do, being scoped to the pure automated suite (no live
Ollama, network, or hardware), is measure the race's real-world duration or
capture a log for this specific incident. The decision now is to keep this
report open with the scoped follow-up below, rather than close it on an
unmeasured assumption in either direction.

## Future considerations and boundaries

- **Measurement handoff (human-run, mirrors `measure_semantic.py`).** Measure
  `AnnotationSemanticIndex.reproject_annotation` / `AnnotationSearchIndex.reproject_annotation`
  wall time against live Ollama for a passage near the 20,000-char overlay
  limit, both uncontended and while `_annotation_write_lock` is held by a
  concurrent reprojection, to get a real bound for the PUT-edit/reprojection
  window instead of the retracted query-embedding extrapolation. If that
  measurement lands in the sub-second-to-low-seconds range (consistent with
  one embedding call), it still cannot explain a ~1-minute gap and the ranking
  explanation gains weight; if it is materially larger (contention, model
  swap, thread-pool queuing), the race becomes a credible sole explanation and
  the fix below should be scheduled.
- **If a fix is warranted:** scope it to awaiting only the edited annotation's
  own reprojection (e.g. `_run_annotation_reprojection` returning a
  future/event the PUT handler can await), not a blanket
  `HistoryProjectionLifecycle.wait_for_idle()`, which would block the HTTP
  response on every unrelated pending reprojection lifecycle-wide. That is new
  lifecycle plumbing and belongs in its own task card, not folded into a
  measurement or benchmark change.
- **If a recurrence is observed:** capture logs around
  `_on_annotation_overlay_changed` / `_reproject_annotation_locked` and the
  retrieval call for that turn - still the fastest way to settle this exact
  incident, independent of the general latency question above.
