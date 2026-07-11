# Task: Data-source and data-presence axes

**Story:** `tasks/story-v1.3.0-control-center.md`
**Status:** Backlog, blocked by task 1 (IA document).
**Release:** v1.3.0

## Summary

Implement the data-source (where inference runs) and data-presence (what
data currently exists in the turn: audio, screen, clipboard) axes in the
Control Center, driven only by authoritative runtime state, and keep them
visibly independent from the Open/Hidden visibility mode.

## Current Boundary

- Data-source: v1.3.0 only ever reports the existing local value, but the
  contract and badge rendering must not assume a binary local/cloud set -
  the value set stays extensible without markup rework.
- Data-presence: derive strictly from events that exist (screenshot
  captured, clipboard submitted, mic state); no inferred or assumed
  presence. Elements without an authoritative source are omitted per the
  IA document, not approximated.
- Privacy semantics preserved exactly as the story states: locality is
  independent from visibility mode; Open/Hidden does not imply
  cloud/offline; Hidden does not mute ordinary voice turns.
- If the IA document classified an axis element as "small event needed",
  the event is added to `ui_contract.py` and the bus mapping here, within
  the boundary the IA document fixed.
- UI changes ride the existing `state` channel; no transport changes.

## Acceptance Criteria

- [ ] Each rendered axis element names its authoritative event/state source
      in the IA document, and tests assert the mapping.
- [ ] Adding a hypothetical new data-source value requires no markup
      change (verified by the data-driven rendering test, not by
      implementing a fake value).
- [ ] Visibility mode changes do not alter data-source or data-presence
      display, covered by tests.
- [ ] `python -m pytest` passes.
- [ ] Manual verification steps prepared for task 4's consolidated QA.

## Stop Conditions

- Stop if data locality, data presence, and visibility semantics conflict
  in any concrete UI state - this is a story-level stop condition.
- Stop if an axis element cannot be driven by authoritative state within
  the IA-fixed boundary.
