# Task v1.6.4-2: User-facing model-request log

**Status:** Planned.
**Story:** `tasks/story-v1.6.4-observability-and-logging.md`
**Depends on:** task-v1.6.4-1 (system log split established).

## Summary

Let the user scroll back through what Jarvis has been sending to the
model. The console's events panel gains a per-turn record of the
request modalities, localized in the interface language.

## Context you need

- `src/jarvis/ui/status_console_ui/app.js`: `appendSystemEvent()`
  renders `payload.message` verbatim - a free-form engine string that
  never passes through `uiString()`. Only the panel chrome
  (`log_title`, `log_sub`, `legend_*`) is localized today. This is why
  the record must arrive typed rather than pre-rendered.
- `applyLastModelRequest()` and the `last_request_*` catalog keys: the
  vocabulary already exists in both languages, including
  `last_request_screenshot`, which the Journal has no equivalent for,
  and the audio duration handled for `_AUDIO_DURATION_KINDS`.
- `MAX_LOG_ENTRIES = 200` and `_clearSystemEvents()` on snapshot reload:
  the panel is a bounded, resettable view. It is history, not state -
  which is exactly why task-v1.6.3-4's chip strip under the orb stays.
- `src/jarvis/ui/contract.py`'s `SystemEvent`: this card adds a sibling
  typed event rather than adding fields to `SystemEvent` itself. If
  that turns out to be impossible without reshaping `SystemEvent`, stop
  per the story's stop condition.

## Boundary

- One new typed event and its rendering. No changes to how any existing
  system event is produced, levelled, or displayed.
- The engine never sends display text for this event and never learns
  the interface language. It sends the kind and, where it has one, the
  duration; the UI resolves both through the catalog.
- Content rule applies in full: modality kinds and durations only. No
  transcript, no clipboard text, no file names, no sizes beyond what
  the existing chip strip already shows.
- The chip strip from task-v1.6.3-4 is not removed or altered.

## Hidden mode constraint

The events panel has no `html[data-visibility="hidden"]` rule and stays
visible in Hidden mode. That is acceptable only while its entries carry
modality names and nothing else. This card must not be the change that
makes the panel worth hiding. If the entry ever needs to carry
something more specific than a modality kind, the Hidden rules must be
revisited first - stop and raise it rather than deciding inline.

## Requirements

- A typed model-request event reaches the UI carrying the same
  modality kinds `applyLastModelRequest()` already handles, plus audio
  duration for the audio kinds.
- The panel renders it through the existing `last_request_*` keys, so
  switching the interface language re-renders it correctly with no new
  catalog entries beyond what the entry's own framing needs.
- The entry is visually distinguishable from engine diagnostics in the
  same panel; it is a user-facing record, not a warning or an error.
- The event is included in the state snapshot's `system_events` replay
  on the same terms as existing events, so a reconnect does not produce
  a panel that disagrees with itself.
- The corresponding detailed English line continues to reach the system
  log through `publish_system_event()`'s `log_message` path.

## Acceptance criteria

- [ ] Automated tests cover: the typed event's payload shape; the UI
      renders it from catalog keys in both languages with no hardcoded
      modality text; the audio-duration path; snapshot replay.
- [ ] An automated test asserts the event carries no payload content.
- [ ] A human-run check confirms the panel shows the record for voice,
      screenshot, clipboard, and attachment turns, in both languages,
      and that Hidden mode exposes nothing new.
- [ ] `python -m pytest` and Ruff checks are green.

## Human verification handoff

Run Jarvis and, in each interface language, perform one turn of each
kind: voice, a screenshot-carrying turn, a clipboard turn, and a turn
with an attachment. After each, confirm:

- the events panel shows a record with the correct localized modality,
  and the voice turn shows its duration;
- the chip strip under the orb still shows the same turn's modalities;
- switching the interface language re-renders existing entries rather
  than leaving stale text;
- switching to Hidden mode reveals nothing in the panel that was not
  already visible in Open mode.
