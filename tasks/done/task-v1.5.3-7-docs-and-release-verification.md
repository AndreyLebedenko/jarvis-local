# Task v1.5.3-7: Docs and release verification

**Status:** Completed.
**Story:** `tasks/story-v1.5.3-memory-layer-a.md`
**Depends on:** tasks v1.5.3-1 through v1.5.3-6.

## Summary

Record the v1.5.3 architecture in PROJECT.md, finish config/user docs,
and prepare the human-run release checklist that closes the story.

## Context you need

- `PROJECT.md`: per-release architecture entries; task-v1.5.3-2 already
  revised the journal-context contract sentence - verify the final
  wording is consistent with what actually shipped.
- All six task cards of this story and their outcomes.
- `tasks/done/task-v1.5.2-8-docs-and-release-verification.md` as the shape
  precedent.

## Boundary

- Documentation and verification only; larger findings become bug
  reports, not fixes here.

## Requirements

- PROJECT.md gains an "Architecture v1.5.3" entry: fork contract
  (fork-not-continuation, verbatim text-only tail, budget,
  provenance, source-log immutability), memory files contract
  (locations, caps, injection order, session-start sampling,
  user-edited-only in this release), and the Hidden/locality
  boundaries.
- `config.example.toml` and README reflect the new `[memory]` settings
  and features.
- A consolidated human-run checklist covers the manual handoffs of
  tasks 3 and 6 plus an end-to-end pass: write a fact into memory.md,
  restart, confirm recall in a spoken answer; fork a session and
  confirm contextual continuity; verify the source session unchanged.
- Out-of-scope findings become reports under `tasks/bug_reports/`.

## Acceptance criteria

- [ ] PROJECT.md updated in the same change as the story closure.
- [ ] Human-run checklist executed with results recorded; findings
      filed as reports.
- [ ] `python -m pytest` and Ruff checks are green.
- [ ] Story closure per the task documentation workflow after human
      approval.

## Human-run verification checklist

Run from the repository root after automated checks are green:

```powershell
python -m jarvis --status-console
```

Manual pass:

- Session fork: choose a non-active past Journal session, click Continue,
  confirm the new session is selected, shows a fork/provenance marker, and the
  first new turn answers with awareness of the seeded source context.
- Source immutability: record the source session id before forking, then
  confirm its `journal/<session_id>/events.jsonl` bytes are unchanged after the
  fork.
- Fork rejections: while Jarvis is busy, attempt a fork and confirm localized
  busy feedback; switch to Hidden and confirm the Journal/fork controls are
  suppressed and the endpoint returns Hidden behavior.
- Memory editing: open the Journal memory panel, edit and save both `self.md`
  and `memory.md`, restart Jarvis, and confirm the content survives restart.
- Memory recall: write a distinctive fact to `memory.md`, restart, ask a
  spoken question that depends on that fact, and confirm the spoken answer
  reflects it.
- Memory limits and unsaved changes: exceed a file cap and confirm client-side
  blocking plus graceful server rejection if submitted; edit without saving and
  confirm closing the panel or leaving Journal asks before discarding.
- Hidden suppression: switch to Hidden while the memory panel is open and
  confirm memory content disappears from the UI and read/write endpoints return
  Hidden behavior.

Record the human result here before moving task cards to `tasks/done/`.

## Human verification result

Executed by the human on 2026-07-19.

- Initial pass: all checks passed except the memory/self editing keyboard
  path.
- Initial memory/self editing result: textareas lost input focus after one
  typed character. Clipboard paste worked as a temporary workaround.
- Follow-up fix in this task changed the memory editor input path to refresh
  the existing file controls in place instead of re-rendering the textarea.
- Rerun after the focus fix: memory/self editing works normally.

Release-verification result: passed. Follow-up UX concern captured as
`tasks/task-v1.5.3-8-explicit-new-context-ui.md`.
