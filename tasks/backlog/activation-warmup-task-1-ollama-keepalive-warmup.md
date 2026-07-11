# Task: Ollama keep_alive and warmup

**Story:** `tasks/backlog/activation-warmup.md`
**Status:** Backlog.
**Target:** v1.4.0 or later

## Summary

Make Ollama `keep_alive` configurable and add async model warmup through the
existing backend stack.

## Current Boundary

- Use existing `OllamaBackend` and `httpx` stack.
- No UI trigger work in this task.
- Do not add a second Ollama client beside `backend.py`.

## Acceptance Criteria

- [ ] `keep_alive` is read from config.
- [ ] `keep_alive` is passed to every `/api/chat` request.
- [ ] `warm_up_model()` is async/fire-and-forget from callers that trigger
      activation and does not block UI/VAD flow.
- [ ] Concurrent warmup calls are guarded against duplicate requests.
- [ ] Warmup failure is logged and surfaced through existing system-event path
      where available.
- [ ] Warmup failures do not crash the main UI/VAD flow and are not silently
      swallowed.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- Human may later measure real `load_duration` on the RTX 5070 Ti; that timing
  feeds task 2 timeout calibration, not this task's automated acceptance.

## Stop Conditions

- Stop if warmup requires a second Ollama client beside `backend.py`.
- Stop if a failure path would be silently swallowed.
