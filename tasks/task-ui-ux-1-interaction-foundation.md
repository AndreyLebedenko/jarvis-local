# Task: Interaction foundation - focus, keymap, radiogroup/listbox helpers

**Story:** `tasks/story-ui-ux-maturity.md`
**Status:** Proposed.
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

- [ ] View, visibility, and reasoning-level groups are single reusable
      `radiogroup`s: full arrow/Home/End keyboard operation, correct
      `aria-checked`, one focus stop per group (roving tabindex).
- [ ] Journal sessions, tool rows, memory files, and annotations use the
      `listbox` helper: arrows/Home/End/Space/Enter/typeahead work; ARIA
      roles present.
- [ ] Every interactive element shows a consistent `:focus-visible` ring;
      keyboard focus is never invisible.
- [ ] Global keys work: view switching, `/` focuses Journal search, `Esc`
      closes the topmost menu/panel/confirm, `?` opens the shortcuts
      overlay. `Ctrl+Q` is reserved and documented, not bound.
- [ ] F2 opens inline edit on annotations/memory/transcripts and is a
      no-op on session titles.
- [ ] Journal sidebar: "+ Новый контекст" is a single primary action with
      the session list; Память/Аннотации/Консолидация live in a feed-pane
      header toolbar; all four still work as before.
- [ ] New user-facing strings exist in both `en` and `ru` catalogs.
- [ ] Browser-preview handoff prepared: keyboard-only traversal of view
      switching, a toggle group, and a Journal list, verified in the
      preview via `demo.html`/`demo.js`.
- [ ] `python -m pytest` passes; `ruff check` and `ruff format --check`
      are clean.

## Verification record

(to be filled at completion)
