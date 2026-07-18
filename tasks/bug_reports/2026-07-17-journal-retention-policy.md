# Journal retention policy remains open

**Detected commit:** `3e0484a`
**Detected during:** task-journal-08 screenshot and release preparation on 2026-07-17
**Status:** Open

## Symptoms

The v1.5.0 journal persists JSONL logs, voice audio, and screenshots, but the
runtime has no automatic retention, pruning, quota, or disk-growth warning.
Journal data remains on disk until the user removes it manually.

## Suspected cause

The story defines the append-only raw log and rebuildable search index, but no
retention duration, size limit, cleanup command, or privacy policy was decided
during implementation. Adding automatic deletion at release wrap-up would be
a destructive product decision rather than documentation-only housekeeping.

## Temporary decision

Record the absence of a policy explicitly and ship without automatic deletion.
This preserves the raw journal as the source of truth and avoids silently
destroying user audio or screenshots. The limitation is called out in
`PROJECT.md` and both user-facing READMEs.

## Disposition (2026-07-18)

The policy question is resolved at the design level by the roadmap's v1.7.0
near/far journal consolidation pipeline
(`tasks/roadmap-v1.5.1-v1.7.md`, section "v1.7.0 - Memory layer B, part 1:
consolidation (near/far journal)"). The near log keeps recent sessions with
full media. The far log keeps transcripts, compressed images, and
model-written annotations. Consolidation is explicit: it runs on command or
schedule, not silently in the background.

This report stays open until that pipeline ships. What closes here is the
open question "which policy", not the implementation. Until v1.7.0 exists,
the only interim relief is v1.5.2's disk-usage visibility and manual
deletion. Automatic deletion remains forbidden, especially for audio before
its transcript exists (`tasks/roadmap-v1.5.1-v1.7.md`, cross-cutting rule 8).

## Future considerations and boundaries

- Define the v1.7.0 near/far boundary age and image-compression parameters in
  the v1.7.0 story card.
- Define a preview and confirmation flow for deleting sessions and media.
- Define how cleanup interacts with the rebuildable FTS5 index and Hidden mode.
- Do not pull cleanup behavior into v1.5.1; v1.5.2 may add only visibility and
  manual deletion, while automatic media reduction waits for v1.7.0.
