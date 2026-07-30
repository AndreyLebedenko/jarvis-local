# Task v1.8.0-22: Consolidation executor and control

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-16-transcription-service.md`
- `task-v1.8.0-19-annotation-generator.md`
- `task-v1.8.0-21-consolidation-planner.md`

## Summary

Execute an explicitly requested consolidation plan with crash-safe progress,
then expose preview and execution control through the authenticated Jarvis API
and Journal UI.

## Context you need

- the task 21 plan model
- transcript and annotation generation services
- journal media storage implementation
- `src/jarvis/ui/transport.py`
- `src/jarvis/ui/status_console_ui/`
- Journal UI static files and tests

## Current boundary

- In scope: execution of approved plans and explicit API/UI control.
- Out of scope: idle/background scheduling and a semantic retrieval backend.

## Requirements

- Revalidate session inactivity and source identities before every material
  operation.
- Persist recoverable operation progress outside the raw journal.
- Execute dependency steps sequentially and idempotently.
- Never remove original audio before a verified effective transcript exists.
- Never alter active-session or near-history media.
- Leave the last verified representation intact after cancellation, crash,
  or backend failure.
- Add authenticated preview, execute, status, and cancel API operations.
- Apply Hidden-mode suppression to content-bearing status details.
- Show preview, blocked reasons, progress, and outcomes safely in the Journal
  UI.
- Report reclaimed storage and failures without logging journal content.
- Require explicit invocation; do not start consolidation during app
  startup or idle time.

## Acceptance criteria

- [ ] Repeating a completed or interrupted plan is safe.
- [ ] Stale plans are rejected before destructive work.
- [ ] Simulated failure at every step preserves a readable source or derived
  representation.
- [ ] API and UI tests cover preview, blocked, running, cancelled, failed,
  completed, unauthenticated, and Hidden states.
- [ ] A human-run media checklist is prepared for transcription, reduced
  images,
  audio removal, cancellation, and restart recovery.

## Stop conditions

- Stop if recoverable progress cannot be stored without rewriting the raw
  journal.
- Stop if a proposed delete target cannot be resolved to one validated media
  file inside the configured journal storage.
- Stop on any unexpected filesystem, permission, or live-Ollama error during
  human verification.

## Verification

- Focused executor fault-injection, API, and UI tests.
- Prepare, but do not run, the hardware/live-Ollama checklist.
- Static JavaScript checks defined by the project.
- `python -m pytest`
- Ruff checks.
