# Task: Reasoning-level core contract

**Story:** `tasks/story-v1.3.1-graded-reasoning-mode.md`
**Status:** Completed.
**Release:** v1.3.1
**Depends on:** Task 1 completed with a passing human report.

## Summary

Replace the internal boolean thinking value with one typed four-level value and
send its exact mapped value in every Ollama chat request. This task has no
hotkey, sound, transport, or UI work.

## Current boundary

In scope:

1. In `src/jarvis/dialog/thinking_mode.py`, define a string enum or equivalent
   closed type with exactly `off`, `low`, `medium`, and `high`.
2. Rename the state owner to `ReasoningLevelState`.
3. Give the state owner:
   - a read-only current `level` property;
   - `set_level(level)` for direct selection;
   - `cycle_level()` using `off -> low -> medium -> high -> off`.
4. Start every new state owner at `off`.
5. Publish one immutable level-changed event containing the new level after
   each real change. Setting the current level again publishes nothing.
6. Keep all read-decide-write behavior synchronous on the asyncio event loop;
   do not await between reading and changing the state.
7. Change the backend input from a boolean to the typed level.
8. Map backend payloads exactly:
   - `off` to `think: false`;
   - each enabled level to its same-name string.
9. Continue reading only `message.content` as `ResponseToken` input. Ignore
   `message.thinking`.
10. Update existing backend and state tests instead of maintaining parallel
    boolean and level contracts.

Out of scope:

- Hotkeys, orchestration wiring, logs, sound cues, UI transport, and HTML/JS.
- A compatibility boolean inside the domain state.
- Reasoning trace events or storage.
- Any other backend request option.

## Acceptance criteria

- [ ] The level type accepts exactly four values.
- [ ] State defaults to `off`.
- [ ] `set_level()` publishes exactly one event for a changed value and none
      for an unchanged value.
- [ ] Four calls to `cycle_level()` return to the initial state.
- [ ] Payload tests assert all four exact `think` values.
- [ ] Thinking-only stream chunks publish no `ResponseToken`.
- [ ] Mixed thinking/content chunks publish only content.
- [ ] Media payload tests still use `images` unchanged.
- [ ] `ResponseComplete` and latency metrics behavior remains unchanged.
- [ ] `python -m pytest` passes.

## Stop conditions

- Stop if Task 1 did not verify all four product values.
- Stop if any consumer needs raw `message.thinking` data.
- Stop if the state owner needs backend, UI, or TTS knowledge.
- Stop if a compatibility requirement forces two authoritative state values.

