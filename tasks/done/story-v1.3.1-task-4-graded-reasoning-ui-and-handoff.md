# Task: Graded reasoning UI and manual handoff

**Story:** `tasks/story-v1.3.1-graded-reasoning-mode.md`
**Status:** Completed.
**Release:** v1.3.1
**Depends on:** Task 3 completed and verified.

## Summary

Replace the binary thinking controls on the desktop and touchstrip with the
graded product contract, then complete visual and live-system verification.

## Current boundary

In scope:

1. Replace the desktop binary switch with one four-option segmented control:
   Off, Low, Medium, High.
2. A desktop click sends `set_reasoning_level` with the clicked exact level.
3. Do not update the selected option optimistically. Update it only from the
   authoritative snapshot or delta.
4. Keep the touchstrip as one compact Thinking action. Each click sends the
   compatibility cycle command.
5. Show the current touchstrip value as `off`, `low`, `medium`, or `high`.
6. Update English and Russian UI catalogs with matching key sets.
7. Update standalone demo controls so all four received states can be viewed
   without a live backend.
8. Update static and JavaScript behavior tests for both surfaces.
9. Run browser visual checks for the desktop and touchstrip at their existing
   supported dimensions.
10. Prepare one human checklist covering:
    - direct selection of all four levels in Control Center;
    - cycling through all four levels by hotkey and touchstrip;
    - one hotkey/touchstrip cycle press right after a direct Control Center
      selection, confirming the cycle continues from the selected level
      instead of the level before it;
    - audible 1/2/3 enabled-cue sequences and the off cue;
    - one accepted request at each level;
    - a level change during an in-flight response applying only next turn;
    - text, voice/audio, and screenshot turns with no spoken or displayed
      reasoning;
    - restart returning the level to `off`.
11. After the human reports success, update `PROJECT.md` with the final state
    owner, level mapping, controls, cue behavior, default, and isolation rule.
12. Mark all four task cards `Completed.`, move them to `tasks/done/`, then
    mark and move the story only after the full story is accepted by the
    human.

Out of scope:

- Displaying the reasoning trace or token counts.
- Persisting the selected level.
- Adding a second touchstrip control or a dense touchstrip selector.
- Reworking unrelated Control Center layout.
- Starting v1.4.0 work.

## Acceptance criteria

- [x] Desktop offers exactly four directly selectable states.
- [x] Desktop selection changes only after authoritative state arrives.
- [x] Touchstrip displays the exact current state and cycles in the specified
      order.
- [x] English and Russian catalogs have identical keys.
- [x] Demo mode can render all four states.
- [x] Static/behavior tests cover command arguments and state rendering.
- [x] Desktop and touchstrip visual checks show no clipping, overlap, or
      unreadable selected state.
- [x] Project formatter, linter, and pure tests pass.
- [x] The human completes the live checklist and reports success.
- [x] `PROJECT.md` records the implemented architecture and verified manual
      result.

## Required project commands

Run these commands before handoff:

```powershell
python -m ruff format .
python -m ruff check .
python -m pytest
```

## Stop conditions

- Stop if the UI has to infer a level from `is_enabled`.
- Stop if UI controls can become selected before authoritative state arrives.
- Stop if visual QA reveals clipping or overlap.
- Stop on any live Ollama, hardware, or WebView environment failure and report
  the exact command and error without a workaround.

