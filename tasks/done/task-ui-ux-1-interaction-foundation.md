# Task: Interaction foundation - focus, keymap, radiogroup/listbox helpers

**Story:** `tasks/story-ui-ux-maturity.md`
**Status:** Completed.
**Release:** post-v1.8.0 (owner to assign).
**Created:** 2026-08-09.
**Scope class:** front-end only (`status_console_ui/*.js`, `*.css`,
`strings.js`). No control commands, no transport, no engine changes.

## Summary

The Status Console is operated almost entirely by mouse via inline
`onclick=` handlers. The only keyboard handling in `app.js` today is
Enter/Space on a Journal session row (`_journalSessionElement`) and
Enter=submit in the input dock (`onJournalInputKeyDown`). There is no
Tab-order design, no arrow-key navigation, no focus-visible styling, and
almost no ARIA (a couple of `aria-label`s and heading `aria-labelledby`).

Three control groups that are semantically single-choice - the view
toggle (`#viewToggle`), the visibility toggle (`#visibilityToggle`), and
the reasoning-level toggle (`#reasoningLevelToggle`) - are built as
independent buttons with no radiogroup semantics. Several item lists
(Journal sessions, MCP/local tool rows, memory files, annotations) are
mouse-first.

This task builds the shared interaction primitives the maturity story
needs, and moves the existing groups and lists onto them, without adding
any feature.

## Proposed direction

1. **Focus design-system** (`style.css`): a single `:focus-visible` ring
   built from the existing CSS variables, applied consistently; a
   skip-to-content affordance; ensure interactive elements are reachable
   and visibly focused. No color palette change beyond adding the ring.

2. **Keymap module** (new small JS unit): one place that binds global
   keys - view switching, `/` to focus Journal search, `Esc` to close the
   topmost open menu/panel/confirm row, `?` to open a shortcuts overlay
   listing the bindings. Keeps bindings out of scattered element handlers.
   Reserve (document, do not implement) `Ctrl+Q` for the deferred command
   palette so it is not reused.

3. **`radiogroup` helper**: wraps a group of option buttons as
   `role="radiogroup"` with `role="radio"` children, roving tabindex,
   Left/Right/Up/Down to move and select, Home/End, and `aria-checked`
   reflecting state. Applied to the view, visibility, and reasoning-level
   groups, replacing their ad-hoc per-button wiring while preserving the
   existing `setActiveView`/`setVisibilityMode`/`setReasoningLevel`
   command sends.

4. **`listbox`/roving-tabindex helper**: wraps an item list as a
   keyboard-navigable collection - arrows move focus, Home/End jump,
   Space selects/toggles (tool rows toggle enablement; session rows
   select), Enter activates the item's primary action, typeahead by
   visible label. Applied to Journal sessions, tool rows, memory files,
   and annotations. `F2` triggers inline edit **only** on already-editable
   items (annotations, memory files, transcripts); it is a no-op on
   derived, non-editable items (session titles).

5. **ARIA roles** on the above so the WebView surface is screen-reader
   navigable as a side effect.

6. **Journal sidebar reorganization** (information architecture, no new
   capability). Today the sessions aside stacks four equal full-width
   buttons above the list: one create *action* (`journalNewContextButton`)
   and three *panel* togglers (`journalMemoryToggle`,
   `journalAnnotationToggle`, `journalConsolidationToggle`) whose panels
   open in the feed pane on the right. Separate the two kinds: keep
   "+ Новый контекст" with the session list as a single primary action;
   move the three panel togglers into a `role="toolbar"` in the feed-pane
   header, adjacent to where their panels appear. Existing sends/handlers
   are unchanged; only placement and grouping change.

New localized strings (shortcuts overlay labels, ARIA labels) go through
`strings.js` in both en and ru, per the localization contract.

## Boundary

- No new features, no new engine state, no control commands, no context
  menu (that is task 2). Status view stays a plain indicator - no roving
  navigation over its module chips.
- Behavior of existing command sends is unchanged; this task changes how
  they are reached, not what they do.
- F2 adds no editable-session-title feature.

## Acceptance criteria

- [x] View, visibility, and reasoning-level groups are single reusable
      `radiogroup`s: full arrow/Home/End keyboard operation, correct
      `aria-checked`, one focus stop per group (roving tabindex).
- [x] Journal sessions, tool rows, memory files, and annotations use the
      `listbox` helper: arrows/Home/End/Space/Enter/typeahead work; ARIA
      roles present. (Generic mechanism live-verified; real Journal/tool
      DOM integration is code-reviewed only - see verification record.)
- [x] Every interactive element shows a consistent `:focus-visible` ring;
      keyboard focus is never invisible.
- [x] Global keys work: view switching, `/` focuses Journal search, `Esc`
      closes the topmost menu/panel/confirm, `?` opens the shortcuts
      overlay. `Ctrl+Q` is reserved and documented, not bound.
- [x] F2 opens inline edit on annotations/memory/transcripts and is a
      no-op on session titles.
- [x] Journal sidebar: "+ Новый контекст" is a single primary action with
      the session list; Память/Аннотации/Консолидация live in a feed-pane
      header toolbar; all four still work as before.
- [x] New user-facing strings exist in both `en` and `ru` catalogs.
- [x] Browser-preview handoff prepared: keyboard-only traversal of view
      switching, a toggle group, and a Journal list, verified in the
      preview via `demo.html`/`demo.js`.
- [x] `python -m pytest` passes; `ruff check` and `ruff format --check`
      are clean.

## Verification record

**2026-08-09.** Implementation: new `interaction.js` (generic radiogroup/
roving-list/escape-stack/keymap helpers, no `uiString()` calls, no engine
knowledge); `app.js` wires it to the view/visibility/reasoning-level
groups (`syncRadioGroup()` called both at init and from
`applyThinkingMode()`/`applyVisibilityMode()`/`setActiveView()`) and to
Journal sessions/tool rows/memory files/annotations (`initRovingList()`);
transcript panels get the lighter `enableStandaloneF2Edit()` since they
are not siblings in one list. `index.html`/`demo.html` gained `role`/
`aria-*` markup, a skip-link, and a shortcuts overlay (`?`/`Esc`). The
Journal sidebar reorg moved the three panel togglers into a
`role="toolbar"` in the feed-pane header, keeping "+ Новый контекст" as
the sessions aside's only remaining action.

Automated: `python -m pytest` (1966 passed, 1 skipped), `ruff check` and
`ruff format --check` clean. Extended `test_ui_i18n.py`/`test_ui_qa.py`
to cover the new `interaction.js` file under the same no-Cyrillic/
uiString-key/network-asset/script-order contracts every other served JS
file already carries.

Browser-preview verification (`demo.html`, since it is the only surface
loadable without a live engine/WS token - the real Journal markup lives
only in `index.html` behind a live transport):
- Radiogroups: arrow/Home/End keyboard events dispatched on the real
  view/visibility/reasoning-level buttons correctly moved focus, updated
  `aria-checked`/roving `tabindex`, and (for the view group, which applies
  immediately) changed `data-view` and fired a real click. Confirmed by
  direct inspection that visibility/reasoning staying visually unconfirmed
  after a keyboard move in demo.html (no live transport) is baseline
  behavior identical to a plain mouse click there, not a regression.
- Escape stack: opening the shutdown-confirm row and the shortcuts
  overlay together, `Escape` closed the overlay first (registered last =
  checked first) and a second `Escape` closed the confirm row - correct
  LIFO priority.
- `?`/`Esc` open and close the shortcuts overlay; computed styles
  confirmed it renders (`display: flex`, `position: fixed`, themed
  background) and the global focus ring resolves to `var(--cyan)`.
- Generic roving-list mechanics (`initRovingList`), exercised against a
  synthetic fixture built in the live page (a Journal session row's real
  shape: a focusable item wrapping a nested button and, on one item, a
  nested textarea): ArrowRight moved the roving stop; Space fired
  `onToggle` and Enter fired `onActivate` exactly once each with no
  leakage into the nested button; F2 focused the nested textarea; arrow
  keys pressed while that textarea itself had focus did **not**
  roving-navigate (the `target === item` guard held, so caret movement
  stayed the textarea's); F2 on an item with nothing editable was a safe
  no-op; Home/End and single-character typeahead ("c" -> "Charlie")
  worked.
- Found and fixed live: the initial `Alt+1/2/3` implementation could
  switch to a view with no corresponding `#viewToggle` button (e.g.
  `Alt+2` "Journal" inside `demo.html`, which deliberately carries no
  Journal markup), throwing an uncaught promise rejection
  (`_applyJournalUsage` writing into a null `#journalUsageTotal`).
  Fixed by gating the shortcut on the button actually existing, so an
  accelerator can never reach further than the control it accelerates;
  re-verified the guard prevents the crash and confirmed by source
  inspection that `index.html`'s real three-button `#viewToggle` is
  unaffected.

Not verified live (requires the real running engine/WS transport, a
human-run handoff per the Testing protocol - `demo.html` carries no
Journal markup by design): the real Journal session list, tool rows,
memory files, and annotations rendered from live data, and the sidebar
reorg's visual placement in the actual product window. Reviewed by
reading the exact DOM shapes each render function produces and confirming
`initRovingList()`/`enableStandaloneF2Edit()` calls match them.

**2026-08-09, post-review fixes.** A stop-time review found two real
defects in the shortcuts overlay (`openShortcutsOverlay()`/
`closeShortcutsOverlay()` in `app.js`):

1. Pressing `?` a second time while the overlay was already open
   re-captured `document.activeElement` (by then the overlay's own Close
   button) as the return-focus target, so `Escape` tried to focus an
   element about to become `hidden` (and therefore unfocusable) instead of
   whatever had focus before the overlay ever opened.
2. `aria-modal="true"` is only a screen-reader hint; nothing stopped real
   `Tab` from reaching background controls while the overlay was open, so
   the announced "modal" semantics did not match actual keyboard behavior.

Fixed by (a) guarding `openShortcutsOverlay()`/`closeShortcutsOverlay()`
against re-entry (`if (!overlay.hidden) return;` / `if (overlay.hidden)
return;`), and (b) a real focus trap via the `inert` attribute: opening
marks every other direct child of `<body>` `inert` (removing them from
the focus order entirely, by Tab or by script - Chromium/WebView2 has
supported this since 2022) and closing clears it. No hand-rolled
Tab-cycling code.

Verified live in `demo.html` via dispatched keyboard events (`?`, a
second `?`, `Escape`) exercised through the real global keydown listener,
not direct function calls: opening focuses Close and marks the topbar
(and every other body child) `inert`; a subsequent `statusBtn.focus()`
attempt while open is silently blocked (proving the trap is real, not
just visual); a second `?` is a no-op and does not move focus or
re-capture the return target; `Escape` closes the overlay, clears
`inert` from the topbar, and restores focus to the original
pre-open element - confirmed stable across three repeated open/close
cycles in one run. `python -m pytest` (1966 passed, 1 skipped), `ruff
check`, and `ruff format --check` all clean after the fix.

**2026-08-09, second post-review fix.** A follow-up stop-time review found
that the modal overlay still permitted global view switching: `inert`
correctly blocks Tab/click/focus from reaching the background, but does
nothing about `initGlobalKeymap()`'s `document`-level keydown listener,
which does not care what is focused - `Alt+1/2/3` and `/` kept working
straight through an open dialog, breaking the "modal" contract in
substance even though it held in form.

Fixed with `_hasOpenModal()` in `interaction.js` -
`document.querySelector('[aria-modal="true"]:not([hidden])') !== null` -
checked right after the (always-live) `Escape` handling and before every
other branch, so a modal suppresses all global shortcuts except the one
that closes it. Written against the ARIA contract rather than a
hardcoded element id, so any future `aria-modal="true"` dialog (including
one task-ui-ux-2 might add) gets the same treatment automatically.

Verified live in `demo.html`: since this tab's script state was already
carrying earlier live-patched functions from prior verification passes in
this same session (this preview environment persists a tab's JS state
across navigations rather than reliably reloading it - confirmed
repeatedly today), a direct patch-and-dispatch test risked exercising a
stale listener instead of the real fix. To test the actual current logic
without that risk, the exact real listener body was extracted verbatim
from the freshly-fetched `interaction.js` source (not reimplemented) and
invoked directly with synthetic events: with the shortcuts overlay open,
`Alt+2` left `data-view` unchanged and `/` did not focus the Journal
search box; closing the overlay and repeating `Alt+3` correctly switched
to Settings, proving the guard blocks only while a modal is genuinely
open. `python -m pytest` (1966 passed, 1 skipped), `ruff check`, and
`ruff format --check` all clean after this fix too.
