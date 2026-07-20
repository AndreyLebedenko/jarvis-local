# Task v1.6.3-1: Tab shell and global header

**Status:** Planned.
**Story:** `tasks/story-v1.6.3-status-console-ui-reorg.md`
**Depends on:** nothing; first card of the story.

## Summary

Introduce the three-tab shell (Status, Journal, Settings) and the
global header that stays visible on every tab: honesty indicators
(LOCAL / LOCAL SOURCES) and the Open/Hidden switch. Content stays
where it is in this card; only the navigation skeleton changes.

## Context you need

- `src/jarvis/ui/status_console_ui/`: `index.html`, `app.js`,
  `style.css` - the current two-view switch (Консоль/Журнал) and how
  view visibility is toggled today; extend that mechanism to three
  tabs rather than inventing a new one.
- `src/jarvis/ui/status_console_ui/strings.js` and the UI language
  catalog: tab captions ("Статус"/"Status", "Настройки"/"Settings")
  are localized entries; renaming "Консоль" to "Статус" is a catalog
  change, both languages.
- `src/jarvis/ui/visibility.py` and the Hidden-mode presentation: the
  header hosts Open/Hidden; its behavior must be identical before and
  after.
- Story boundary: honesty indicators never disappear behind tab
  switching.

## Boundary

- Navigation and header only. The settings form stays inlined under
  Status until task 2 moves it; the Settings tab may render a
  placeholder or the not-yet-moved content unchanged - whichever
  keeps this card smallest, stated in the card outcome.
- No changes to transport, engine state, or any control's wiring.
- No visual redesign beyond what the tab bar and header require;
  existing styling patterns apply.

## Requirements

- Three tabs with the active tab persisted the same way the current
  view choice is (or not persisted, if it is not today - parity, not
  new behavior; state which in the outcome).
- The header renders on all tabs: brand, tab bar, LOCAL indicator,
  LOCAL SOURCES indicator, Open/Hidden switch - one header component,
  not per-view copies.
- Tab switching must not reload or re-request journal data
  unnecessarily; whatever lazy-load behavior the Journal view has
  today is preserved.
- Keyboard/UI language switching updates tab captions live, same as
  other localized chrome.

## Acceptance criteria

- [ ] Automated tests that cover UI contract/strings today are
      extended to the new tab captions in both languages; no
      hardcoded tab text.
- [ ] A human-run visual check confirms: three tabs render, header
      identical on all tabs, Hidden mode behaves exactly as before,
      journal view unaffected by tab switching.
- [ ] `python -m pytest` and Ruff checks are green.
