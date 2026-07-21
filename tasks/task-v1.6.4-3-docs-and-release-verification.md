# Task v1.6.4-3: Docs and release verification

**Status:** Planned.
**Story:** `tasks/story-v1.6.4-observability-and-logging.md`
**Depends on:** tasks v1.6.4-1..2.

## Summary

Record the two-log contract and its content rule where future work will
actually read them, and prepare the human-run release check.

## Context you need

- Story acceptance criteria and the content rule.
- `PROJECT.md`: the runtime locality contract (a local file sink is not
  a network capability and must be stated as such), and any section
  describing the Status Console's events panel.
- Release verification precedent:
  `tasks/done/task-v1.5.2-8-docs-and-release-verification.md`.

## Boundary

- Documentation and checklist only. Fixes revealed by verification that
  are larger than trivial become bug reports per the project protocol.

## Requirements

- `PROJECT.md` records the two-log contract as a design criterion, not
  as an implementation note: which log is for whom, why the system log
  is English, why a UI panel is not a diagnostic tool, and the content
  rule that binds both. Future logging work should be placeable by the
  rule rather than by taste.
- The log file location and rotation bounds agreed in task-v1.6.4-1 are
  documented where a user can find them when asked to attach a log.
- User docs explain, in user terms, what the events panel shows and
  what it deliberately does not.
- The human-run checklist covers: the file appears and survives exit;
  rotation behaves at the configured bound; the panel record renders in
  both languages for every modality; Hidden mode parity; and a
  content-rule spot check across both logs.

## Acceptance criteria

- [ ] `PROJECT.md` and user docs updated in the same release as the
      behavior change.
- [ ] The human-run checklist is prepared and handed off; verified
      outcomes are recorded before the story closes.
- [ ] `python -m pytest` and Ruff checks are green.
