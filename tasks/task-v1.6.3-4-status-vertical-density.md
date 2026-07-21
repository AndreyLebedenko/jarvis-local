# Task v1.6.3-4: Status vertical density

**Status:** Planned.
**Story:** `tasks/story-v1.6.3-status-console-ui-reorg.md`
**Depends on:** task-v1.6.3-2 (content migration).
**Created:** 2026-07-21 (owner decision from the v1.6.3 review dialog).

## Summary

Make the Status tab fit a 900 px window without an initial scrollbar by
fixing the cause rather than the symptom: compress the "Last request to
model" section into a chip strip under the orb, tighten the column
rhythm, cap the MCP tool list, and revert the window height raised in
task-v1.6.3-2.

## Why this card exists

While implementing tasks 1-2 the window default height was raised from
900 to 1020 px to avoid an initial scrollbar on Status. That is a
symptom fix with two problems:

- 1020 px does not reliably fit a 1080p display once the taskbar and
  the window frame are subtracted;
- it does not survive v1.6.1, whose builtin tools will lengthen the MCP
  tool list and push Shutdown down again regardless of window height.

The height change and the global scrollbar theming introduced alongside
it were also outside the boundary of tasks 1-2 ("pure relocation, no
behavior changes"). This card is where they belong.

## Context you need

- `src/jarvis/ui/status_console_ui/style.css`: `.main` is a flex column
  with `gap: 26px` across seven gaps - roughly 180 px of the column is
  empty space, more than the whole MCP block occupies.
- `.action-feedback` is an always-present wrapper whose only child
  (`#shutdownConfirmRow`) is `display: none` until confirmation. The
  wrapper contributes no height but still consumes one `.main` gap.
- `applyLastModelRequest()` (`app.js`) renders one row per modality of
  the most recent turn, plus audio duration for the two audio kinds.
  It is fed from `state.last_model_request` in `_applyStateSnapshot()`,
  so it is current state that survives reconnect, not a scrolling log.
- The Journal labels each message with its source
  (`journal_source_voice` / `_text` / `_dock` / `_attachment`) but has
  no equivalent for `last_request_screenshot` and never shows audio
  duration. Removing the panel outright would delete the only place in
  the UI that answers "was a screenshot sent to the model" - an
  honesty-axis fact, not a convenience.

## Boundary

- Layout and CSS only. No transport or contract changes, no changes to
  what `applyLastModelRequest()` receives, no new engine state.
- The set of modalities rendered stays exactly as it is today,
  including audio duration; only its presentation changes.
- All text keeps coming from the language catalog. The chip strip reuses
  the existing `last_request_*` keys; `last_request_title` becomes
  unused on this surface and is removed only if no other surface
  (including `touchstrip.html`) still references it.
- Moving the request record into the system events panel is explicitly
  out of scope - it needs a typed event and a contract change, and is
  story v1.6.4's work.

## Requirements

- The "Last request to model" section is replaced by a chip strip
  rendered directly under the orb state text: no heading, no separate
  section, one wrapping row. It stays localized and stays sourced from
  the state snapshot.
- `.main` vertical rhythm is tightened (gap 26 -> 16 px) and the empty
  `.action-feedback` wrapper stops consuming a gap when no confirmation
  is showing.
- The MCP tool list gets a bounded height (about 180 px) with its own
  internal scroll, so tool-count growth cannot displace Shutdown.
- Shutdown is pinned to the bottom of the Status column
  (`margin-top: auto`) and stays horizontally centered on the column's
  existing vertical axis. It stays on Status, stays the single
  destructive action, and stays out of the global header.
- `StatusConsoleWindow` default height returns to 900.
- The global scrollbar theming added in task-v1.6.3-2 is kept and
  documented here as a deliberate, console-wide decision rather than an
  unexplained side effect of the tab work.

## Acceptance criteria

- [ ] Automated tests assert: the chip strip renders from
      `last_request_*` catalog keys in both languages; no
      `last-request-panel` section remains; the MCP tool list rule
      carries a bounded height with `overflow-y: auto`; Shutdown is
      pinned with `margin-top: auto`; the window default height is 900.
- [ ] A human-run visual check at 900 px confirms: Status shows no
      initial scrollbar with a cold MCP list, Shutdown sits at the
      bottom, the screenshot and audio-duration facts are still visible
      after a turn that used them, and a long MCP tool list scrolls
      inside its own card instead of moving Shutdown.
- [ ] `python -m pytest` and Ruff checks are green.

## Human visual review handoff

Run Jarvis normally and open the Status Console at its default size.
Confirm:

- No scrollbar on Status immediately after startup.
- After a voice turn, the chip strip under the orb shows the voice
  modality with its duration; after a turn that captured the screen, it
  shows the screenshot modality.
- Both UI languages render the chip strip without clipping.
- With MCP enabled and a long tool list, the list scrolls inside the MCP
  card and Shutdown does not move.
- Shutdown still asks for confirmation, and the confirmation panel
  appearing does not shift Shutdown itself.
