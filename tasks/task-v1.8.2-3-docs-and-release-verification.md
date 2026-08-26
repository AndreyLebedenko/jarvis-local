# Task v1.8.2-3: Docs and release verification

**Status:** Proposed.
**Story:** `tasks/story-v1.8.2-replay-tts.md`
**Depends on:** task-v1.8.2-1 and task-v1.8.2-2 (core and UI complete and
verified).

## Summary

Document the replay feature and run release verification for v1.8.2. Record
the re-synthesis-not-stored-audio and reject-when-busy decisions where they
belong, update user-facing docs, note the forward seam for v1.9.0, and
prepare the human-run verification checklist.

## Context you need

- `tasks/story-v1.8.2-replay-tts.md`: the locked decisions to document.
- `tasks/task-v1.8.2-1-replay-core.md` and
  `tasks/task-v1.8.2-2-play-control-ui.md`: the actual behavior shipped.
- `PROJECT.md`: whether a replay entry belongs in verified facts /
  architecture (the re-synthesis-only choice and the single-channel
  reject-when-busy behavior are architectural decisions; record them if they
  meet the bar, per CLAUDE.md's "update PROJECT.md in the same commit").
- `config.example.toml`: only if replay exposes any config surface; the story
  currently defines none, so this may be a no-op except a documentation
  mention.
- Existing user docs (README / docs used by prior story release cards) for
  where a "re-listen to a reply" note fits.

## Boundary

- Documentation and verification only. No behavior changes; if verification
  finds a defect, that is a bug report or a fix in tasks 1/2, not new scope
  here.

## Requirements

- Document the Play control and re-synthesis behavior in the appropriate
  user-facing doc: any past reply is replayable, playback is fresh synthesis
  under current TTS settings (not stored audio), busy attempts are rejected
  with a beep + error, and Ctrl+Alt+I stops a replay.
- Record the architectural decisions in `PROJECT.md` if they meet the
  project's bar: re-synthesis-not-stored-audio, and single-channel
  reject-when-busy (no queue / no second route).
- State the forward seam: the "text to speak for this turn" accessor is what
  v1.9.0's mode-3 spoken derivative will later retarget, so replay gains the
  nicer source without UI changes.
- Prepare the human-run verification checklist with exact commands/steps for
  the hardware/manual parts (replay audio, busy-reject beep+error,
  Ctrl+Alt+I cancellation, replay of an older reply).

## Acceptance criteria

- [ ] User-facing docs describe replay accurately, including the
      re-synthesis-under-current-settings behavior and the reject-when-busy
      rule.
- [ ] `PROJECT.md` reflects the replay architectural decisions, or a short
      note records why they did not meet the bar for inclusion.
- [ ] The forward seam to v1.9.0 is documented where a future reader will
      find it (story cross-reference and/or PROJECT.md).
- [ ] A human-run verification checklist exists with exact steps and expected
      results for every hardware/manual behavior.
- [ ] `python -m pytest`, `python -m ruff check .`, and
      `python -m ruff format --check .` are green.

## Stop conditions

- Stop if release verification reveals replay behavior that contradicts the
  story's locked decisions - route it back to task 1/2 or a bug report,
  rather than documenting around it.

## Verification

- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
- Human-run release checklist for the replay feature (audio, busy-reject,
  interrupt, older-reply replay).
