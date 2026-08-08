# Edited annotation not recalled from a fresh context shortly after save

**Detected at commit:** 3bc2dd0 (task v1.8.0-23 slice 4, uncommitted UI changes
on top)
**Status:** Deferred to task v1.8.0-26 (retrieval-quality regression). Not
investigated further here - see "Suspected cause" for the two competing
explanations that need a log-backed repro to distinguish.

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

## Temporary decision

Defer. Do not investigate or fix inside task v1.8.0-23; the card explicitly
puts ranking/retrieval-quality work out of scope, and distinguishing the two
explanations above requires the task 26 benchmark harness (or at least a
log-backed repro) rather than ad hoc UI playtesting.

## Future considerations and boundaries

- When task v1.8.0-26 is otherwise complete, revisit this specific scenario
  before closing that card: reproduce the edit -> immediate cross-context
  query sequence with logging around `_on_annotation_overlay_changed` /
  `_reproject_annotation` and the retrieval call, to determine whether it is
  the publish/reprojection race or a plain ranking miss.
- If it is the race: `_journal_annotation_put_handler` returning success
  before reprojection completes is the fix target, not the benchmark or
  ranking logic. Consider whether the PUT response should await
  reprojection completion (mirrors how `_generateJournalAnnotation` already
  waits for the API call before reloading the panel) or whether this is an
  acceptable eventual-consistency window, similar to the accepted boundary in
  `2026-08-08-annotation-fetch-factor-underfill.md`.
- If it is ranking: no action needed beyond whatever card 26's benchmark
  already plans to cover for annotation slices.
