# Task: Visual language pass - hierarchy, typography, honesty fixes

**Story:** `tasks/story-ui-ux-maturity.md`
**Status:** Proposed. Design-first: gated on an owner-approved mockup
before any restyle lands. May run after tasks 1-3 or in parallel from that
gate.
**Release:** post-v1.8.0 (owner to assign).
**Created:** 2026-08-09 (from the owner's live-interface review).
**Scope class:** front-end only (`status_console_ui/*.css`, minimal
`*.js`/`index.html` for control-type swaps and hiding dead affordances).
No engine, transport, or control-command changes.

## Summary

A review of the running app (Status, Journal, Settings) found the visual
language reads as a debug console rather than a mature product, and
carries a few objective defects. This task raises the visual maturity with
a *specific* checklist, not a vague "make it nicer", and separates
objective fixes (which need no design taste) from subjective design
choices (which do, and go through a mockup the owner signs off first).

## Objective fixes (no design judgment needed)

1. **Dead reset affordances.** Every Status module chip shows a `↺` reset
   button, but `reset_module` only publishes a "not implemented"
   `SystemEvent`. Hide the reset control until a real per-module reset
   exists (consistent with task 2 omitting a Reset context-menu item).
   Do not remove the underlying wiring - only the affordance.
2. **Native form controls break the dark theme.** Checkboxes (Status tool
   lists) and `<select>`s (Settings, e.g. the Piper/Silero engine and
   yes/no dropdowns) render with OS light styling. Theme them to match the
   dark surface (custom checkbox styling; dark-styled selects with a
   themed dropdown affordance), keeping full keyboard operability from
   task 1.
3. **Inconsistent local-tool labels.** "Локальные инструменты" mixes human
   labels ("Доступ к камере", "Запись в память") with raw identifiers
   (`read_history`, `read_history_ranges`). Adopt one rule: a human label
   as the primary line with the identifier secondary/dimmed (the existing
   `_tool_payload` already carries `name` and a model-facing
   `description`; a `ui_description`/label source may be needed rather
   than reusing the model-facing text - decide in the mockup).

## Subjective design (mockup, then owner approval, then build)

4. **Monospace scope.** Reserve the monospace face for genuinely technical
   or tabular data (timestamps, byte sizes, model ids, log lines) and move
   section labels, buttons, and headings to the proportional UI face.
5. **Accent-emphasis scale.** Introduce 2-3 emphasis tiers (primary /
   secondary / ghost) so a primary action reads as primary. Reconcile the
   lone purple selected reasoning-level chip with the otherwise-cyan accent
   system (either fold it into the cyan scale or make purple a deliberate,
   repeated semantic - not a one-off).
6. **Icon set.** A light, consistent inline-SVG icon set for the recurring
   actions (new, continue, delete, memory, annotations, consolidation,
   copy) to cut text weight and pair with the task-2 context menus.
7. **Session-card weight.** Invert the card hierarchy so the title (the
   session's identity) is primary and the timestamp/size are secondary.
   (Derived, non-distinguishing "New context" titles remain a separate,
   out-of-scope limitation.)

## Boundary

- Front-end only; no engine/transport/control changes and no new engine
  capability. Hiding the reset affordance does not remove `reset_module`.
- No editable session titles, no command palette, no Status-chip roving
  navigation (those belong to other tasks or are out of story scope).
- Subjective items ship only after the owner approves the mockup; objective
  fixes may proceed without it but still land in this task's change.

## Acceptance criteria

- [ ] An annotated before/after mockup (Status, Journal sidebar/feed,
      Settings TTS section) is produced and approved by the owner before
      any subjective restyle is applied.
- [ ] Module-chip reset affordances are hidden while `reset_module` is a
      stub; wiring is untouched.
- [ ] Checkboxes and selects match the dark theme in all three views and
      remain fully keyboard-operable.
- [ ] Local-tool rows use one consistent label rule.
- [ ] Monospace is confined to technical/tabular data; labels, buttons,
      and headings use the proportional face.
- [ ] A defined accent-emphasis scale is applied; the reasoning-level
      selection no longer reads as an unexplained one-off color.
- [ ] Session cards lead with the title, not the timestamp.
- [ ] New/changed user-facing strings exist in both `en` and `ru`.
- [ ] Browser-preview handoff prepared covering all three views in light
      and dark surfaces where applicable.
- [ ] `python -m pytest` passes; `ruff check` and `ruff format --check`
      are clean.

## Verification record

(to be filled at completion)
