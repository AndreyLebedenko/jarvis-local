# Task v1.6.4-2: User-facing model-request log

**Status:** Implemented, pending the human verification run.
**Story:** `tasks/story-v1.6.4-observability-and-logging.md`
**Depends on:** task-v1.6.4-1 (system log split established).

## Outcome

`model_request_log_payload()` in `status_console.py` is a sibling of
`system_event_payload()`, not an extension of it: `SystemEvent` is
untouched. The events panel's list now carries two payload shapes,
discriminated by an `entry` field that only the new one sets, so
existing entries keep their exact shape and every existing test of
`system_event_payload()` still describes reality.

`_on_model_request_started()` publishes the same `ModelRequestSummary`
twice: to `last_model_request` (the chip strip, "what is true now") and
to `system_events` (the panel, "what happened"). One source, two
projections, no second code path deriving modalities.

On the UI side `appendSystemEvent()` branches on the discriminator and
`_appendModelRequestEntry()` localizes from the existing
`last_request_*` keys. Both it and the chip strip render a modality
through one shared `_requestItemText()`, so the two surfaces cannot
drift into two wordings for the same fact. Violet marks the entry as a
different kind of line without implying severity.

**Decision: request entries share the panel's 200-entry budget** rather
than getting their own. This is one panel with one bounded history, and
the durable record of what was sent is the file log from task 1, not
these entries. A chatty tool session can evict older request records
from the panel; the chip strip still answers "now" and the file still
answers "then".

**Language switching is not a concern in practice:** `[ui].language` is
restart-to-apply, and `_applyStateSnapshot()` calls `applyUiLanguage()`
before replaying `system_events`, so replayed entries always render in
the current language.

## Pre-existing defect fixed here

The audio duration unit was hardcoded English, so the Russian UI read
"Голос: 3.2 s". Harmless while it appeared once under the orb; wrong
twice over once the same text is also rendered into the events panel.
The unit now comes from a `unit_seconds` catalog key in both languages.
This also fixes the v1.6.3 chip strip.

## Found, not fixed here - needs an owner decision

This card assumed a turn's request already produced a detailed English
line in the system log, and that the work was only to add the localized
UI half. It does not. `ModelRequestStarted` is published straight onto
the bus in `app.py` and never passes through `publish_system_event()`,
so **the file log has no record of what any turn sent to the model.**

That inverts story v1.6.4's premise: the panel now answers "what did
this turn send" while the file - the artifact a user actually attaches
to a problem report - does not.

The fix is one line, but not a line this card may add:

- Calling `publish_system_event()` would also push an English
  `SystemEvent` into the panel, so every turn would show twice: once as
  the localized typed entry, once as a raw diagnostic. Wrong.
- A direct `logger.info(...)` at the `ModelRequestStarted` publish site
  gives the file its line without touching the panel. Right - but it is
  a new log call site, which task-v1.6.4-1's boundary excluded and this
  card's boundary ("one new typed event and its rendering") does not
  cover.

Recommend a small task-v1.6.4-4 for it, before the story closes. The
content rule applies unchanged: modality kinds, count, and duration -
never the text or media that was sent.

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
- ~~The corresponding detailed English line continues to reach the
  system log through `publish_system_event()`'s `log_message` path.~~
  Written on a false premise; see "Found, not fixed here" below.

## Acceptance criteria

- [x] Automated tests cover: the typed event's payload shape; the UI
      renders it from catalog keys with no hardcoded modality text or
      unit; the audio-duration path; the shared modality formatter; and
      that request entries share the panel's bounded budget.
- [x] An automated test asserts the event carries no payload content -
      it pins the payload's exact key set, so a future field that could
      carry content fails the test rather than shipping.
- [ ] A human-run check confirms the panel shows the record for voice,
      screenshot, clipboard, and attachment turns, in both languages,
      and that Hidden mode exposes nothing new.
- [x] `python -m pytest` and Ruff checks are green.

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
