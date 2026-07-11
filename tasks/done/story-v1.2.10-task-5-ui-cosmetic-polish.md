# Task: UI cosmetic polish

**Story:** `tasks/story-v1.2.10-ui-transport.md`
**Status:** Completed.
**Release:** v1.2.10

## Summary

Apply the two visual adjustments identified during the v1.2.10 manual review:
replace the muted-microphone label with natural Russian wording and group the
three lower Status Console actions into a centered horizontal layout.

## Current Boundary

In scope:

- Change only the Status Console microphone module-health detail for the
  user-muted state from `усыплён` to `не используется`.
- Group Settings, Reset context, and Shutdown controls into one centered,
  horizontal action row in the Status Console.
- Keep the row responsive: at widths where the three controls cannot fit,
  controls may wrap while remaining centered and usable.
- Update focused pure UI/state tests for the changed text and structure.

Out of scope:

- Any change to microphone sleep/wake behavior, stream restart/recovery, VAD,
  hotkeys, sound cues, or microphone hardware status semantics.
- Touchstrip layout or text changes.
- New controls, protocol fields, or transport behavior.

## Acceptance Criteria

- [x] A user-muted microphone reports the detail `не используется` in the
      Status Console module-health state.
- [x] Settings, Reset context, and Shutdown appear in one centered horizontal
      action row at ordinary desktop Status Console widths.
- [x] At narrow widths, the controls do not overflow or overlap and remain
      centered and operable.
- [x] Existing confirmation flows and control commands are unchanged.
- [x] Focused automated tests cover the text and layout contract; `python -m
      pytest` passes.

## Verification

- Automated: run `python -m pytest`.
- Human: run `python main.py --status-console`, toggle microphone sleep once,
  and verify the chip says `не используется`; verify the three lower controls
  share one centered row without changing their actions or confirmations.

## Stop Conditions

- Stop if the requested layout cannot fit without changing the Status Console
  information architecture or hiding controls.
- Stop if the wording requires changing the distinction between user-muted and
  hardware-unavailable microphone states.
