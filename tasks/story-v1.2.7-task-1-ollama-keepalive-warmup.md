# Task: Ollama keep_alive and warmup

**Story:** `tasks/story-v1.2.7-activation-and-warmup.md`
**Status:** Backlog.
**Release:** v1.2.7
**Detailed card:** `tasks/task-01-ollama-keepalive-warmup.md`

## Summary

Make Ollama `keep_alive` configurable and add async model warmup through the
existing backend stack.

## Current Boundary

- Follow `tasks/task-01-ollama-keepalive-warmup.md`.
- Use existing `OllamaBackend` and `httpx` stack.
- No UI trigger work in this task.

## Acceptance Criteria

- [ ] `keep_alive` is read from config.
- [ ] `keep_alive` is passed to chat requests.
- [ ] `warm_up_model()` is async and does not block caller flow.
- [ ] Concurrent warmup calls are guarded against duplicate requests.
- [ ] Warmup failure is logged and surfaced through existing system-event path
      where available.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if warmup requires a second Ollama client beside `backend.py`.
- Stop if a failure path would be silently swallowed.
