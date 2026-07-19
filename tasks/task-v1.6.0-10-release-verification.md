# Task v1.6.0-10: Release verification and documentation

**Status:** Backlog.
**Story:** `tasks/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-1 through task-v1.6.0-9 completed and reviewed.

## Summary

Close v1.6.0 with end-to-end verification, human-run Ollama audio checks,
documentation updates, and story cleanup.

## Context you need

- Story acceptance criteria: every box must be checked or explicitly
  re-scoped by the human.
- `PROJECT.md`: record only verified facts and architectural decisions.
- README/user docs if they describe input sources or the Status Console
  Journal view.
- Testing protocol: live Ollama and hardware/media behavior checks are
  human-run handoffs, not agent-run tests.

## Boundary

- Verification and docs only. Code changes are limited to review findings
  explicitly approved during release verification.
- Do not start v1.6.1 builtin tools or v1.6.2 camera work.
- Do not claim uploaded audio behavior as verified until the human-run
  check passes against local Ollama.

## Requirements

- Run the full automated gate: `python -m ruff format --check .`,
  `python -m ruff check .`, and `python -m pytest`.
- Prepare a human-run manual check script or exact command sequence for:
  text attachment, image attachment, uploaded audio attachment, unsupported
  format, text truncation, audio chunking, and Hidden mode. The image check
  must include a real `.jpg`, not only PNG: the live-verified `images`
  precedent (screenshot path) covers PNG only, so JPEG-through-`images` is
  not yet a verified fact (agreed at task-v1.6.0-4 review, 2026-07-19).
- Update `PROJECT.md` with the final v1.6.0 architecture summary and any
  verified uploaded-audio facts.
- Update user-facing docs/screenshots if they enumerate Journal input
  capabilities.
- Update the story card status and move completed task cards to
  `tasks/done/` only after human review approves closure.

## Acceptance criteria

- [ ] Automated Ruff and pytest gates are green.
- [ ] Human-run uploaded-audio check passes or produces a recorded stop
      condition/bug report.
- [ ] `PROJECT.md` records the final architecture and verified facts
      without weakening the locality contract.
- [ ] User-facing docs mention Journal attachments and their limits.
- [ ] Story acceptance criteria are all checked or explicitly re-scoped.

