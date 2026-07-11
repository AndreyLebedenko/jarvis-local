# Task: Web UI static text localization

**Story:** `tasks/story-v1.2.11-ui-english-localization.md`
**Status:** Completed.
**Release:** v1.2.11

## Summary

Localize the static text of the Status Console and Touchstrip pages
(`status_console_ui/index.html`, `touchstrip.html`, `app.js`,
`touchstrip.js`, and the demo pages) using a per-language dictionary in the
web layer, selected by the active UI language delivered by the transport
(task 1). English is the default before the first transport message arrives.

## Current Boundary

In scope:

- A JS string dictionary (`en`/`ru`) for all static labels: headers, button
  captions, confirmation dialogs, settings form labels, placeholder texts,
  and any Russian literals in `app.js`/`touchstrip.js`.
- HTML text nodes either populated from the dictionary on load or updated
  when the language arrives over the transport; pre-transport fallback is
  English.
- Demo pages (`demo.html`, `demo.js`) updated to the same mechanism or to
  plain English, so no stale Russian copy diverges from the real UI.
- Pure UI/state tests updated where they assert on visible text.

Out of scope:

- Python-side strings (task 1).
- Visual redesign, layout, or CSS changes beyond what differing text lengths
  require (e.g. a longer English caption must not overflow, but do not
  restyle).
- An in-UI language switcher.

## Acceptance Criteria

- [ ] With default config, both pages contain no visible Russian text: all
      headers, buttons, confirmations, and settings labels are English.
- [ ] With `ui.language: ru`, both pages render the current Russian wording.
- [ ] English captions fit the existing layout at ordinary and narrow widths
      (no overflow or clipped controls).
- [ ] Demo pages match the real UI language behavior or are plain English.
- [ ] `python -m pytest` passes.

## Stop Conditions

- Stop if English text lengths force information-architecture changes to the
  Status Console or Touchstrip layout.
- Stop if the transport cannot deliver the language early enough to avoid a
  visible language flash and fixing that requires transport protocol changes
  beyond adding the field from task 1.
