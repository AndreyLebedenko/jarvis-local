# Task: Runtime reasoning-level controls

**Story:** `tasks/story-v1.3.1-graded-reasoning-mode.md`
**Status:** Completed.
**Release:** v1.3.1
**Depends on:** Task 2 completed and verified.

## Summary

Wire the typed reasoning level through accepted turns, the existing global
hotkey, logs, sound feedback, and UI transport. This task does not change UI
markup or styling.

## Current boundary

In scope:

1. Construct one `ReasoningLevelState` in the application composition root.
2. Sample its `level` once when an accepted turn starts and pass that value to
   `OllamaBackend.chat()`.
3. Bind the existing `hotkeys.thinking_toggle` hotkey to `cycle_level()`.
4. Keep the hotkey callback thread-safe: it schedules exactly one cycle on the
   asyncio loop and never reads the current level itself.
5. On each level-changed event, log exactly one INFO message naming the new
   level.
6. On each level-changed event, play sound feedback:
   - `off`: play `thinking_off` once;
   - `low`: play `thinking_on` once;
   - `medium`: play `thinking_on` twice in order;
   - `high`: play `thinking_on` three times in order.
7. Do not add or rename sound-cue configuration fields.
8. Change UI state snapshots and deltas from a boolean-only thinking value to
   a payload containing:
   - `level`: the authoritative string level;
   - `is_enabled`: `false` only for `off`, retained as a derived compatibility
     field for protocol-v1 clients.
9. Add a `set_reasoning_level` control command accepting one `level` argument.
10. Keep `toggle_thinking` as a protocol-v1 compatibility command, but make it
    call `cycle_level()`.
11. Reject a missing, non-string, or unknown level argument with the existing
    protocol-error mechanism and leave state unchanged.
12. Update pure wiring and transport tests.

Out of scope:

- Desktop or touchstrip HTML, CSS, JavaScript, and visual QA.
- New sound files or config migration.
- Persisting the selected level across restart.
- Changing current-turn behavior after the backend call starts.

## Acceptance criteria

- [ ] Every accepted turn receives the level sampled at its start.
- [ ] Changing the level while busy affects only the next accepted turn.
- [ ] Rapid hotkey presses produce the same number of ordered cycles.
- [ ] A hotkey cycle issued after a direct `set_reasoning_level` selection
      continues the `off -> low -> medium -> high -> off` order from the
      directly selected level, not from the level before that selection.
- [ ] Logs name `off`, `low`, `medium`, or `high` exactly.
- [ ] Sound tests assert 0/1/2/3 enabled-cue plays and one off-cue play as
      specified.
- [ ] Snapshot and delta payloads contain correct `level` and derived
      `is_enabled` values.
- [ ] Direct-selection commands accept all four values and reject all other
      inputs without changing state.
- [ ] The compatibility toggle command performs one cycle.
- [ ] A real-bus regression test proves reasoning chunks still cannot reach
      TTS.
- [ ] `python -m pytest` passes.

## Stop conditions

- Stop if orchestration must read level more than once per turn.
- Stop if hotkey and direct UI selection require separate state owners.
- Stop if level-aware cues require changes to audio serialization.
- Stop if the transport would expose reasoning content rather than level
  metadata only.

