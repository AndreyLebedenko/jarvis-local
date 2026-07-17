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

## Future considerations and boundaries

- Decide whether retention is time-based, size-based, or user-triggered.
- Define a preview and confirmation flow for deleting sessions and media.
- Define how cleanup interacts with the rebuildable FTS5 index and Hidden mode.
- Add a separate task card after the owner chooses the disk-growth and privacy
  policy; do not pull cleanup behavior into v1.5.0 release wrap-up.
