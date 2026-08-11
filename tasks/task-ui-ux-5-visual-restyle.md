# Task: Visual language pass - subjective restyle (monospace scope, accent scale, icons, session-card weight)

**Story:** `tasks/story-ui-ux-maturity.md`
**Status:** Proposed. Split out of `tasks/task-ui-ux-4-visual-pass.md` on
close (2026-08-11): that card's owner-approved mockup covers exactly this
scope; this card is the implementation of it. Not yet started.
**Release:** post-v1.8.0 (owner to assign).
**Created:** 2026-08-11 (split from task-ui-ux-4-visual-pass.md).
**Scope class:** front-end only (`status_console_ui/*.css`, `*.js` for
control-type/markup swaps needed to attach icons and restructure the
session card). No engine, transport, or control-command changes.

## Summary

`task-ui-ux-4-visual-pass.md` separated objective fixes (no design taste
needed - done, closed) from subjective design (gated on an owner-approved
mockup). The owner approved that mockup on 2026-08-11. This card
implements exactly what it showed - four items, none of them requiring
further design judgment since the design decisions are already made and
signed off.

## Design reference

The approved mockup (annotated before/after for Status, Journal
sidebar/feed, and Settings TTS, plus accent-scale and icon-set specimens)
was published as a Claude Artifact during task-ui-ux-4's work and reviewed
live by the owner. The decisions below are the mockup's content, recorded
here so this card does not depend on that artifact's URL staying
reachable.

## Requirements

1. **Monospace scope.** Move to the proportional face (matching the
   existing `.chip-label`/card-title convention): section labels/headings
   (`MODULES`, `SESSIONS`, `SPEECH SYNTHESIS (TTS)`, `VOICE DETECTION
   (VAD)`), segmented-toggle button labels (view toggle, visibility
   toggle, reasoning-level toggle), all standalone action buttons (Apply,
   Send, New context, Attach, Memory/Annotations/Consolidation toolbar,
   Shut down), and local/MCP tool-row primary labels (`.tool-row-name`,
   added in task-ui-ux-4). Keep monospace for genuinely technical/tabular
   data: `.chip-meta`, log timestamps/entries, journal session
   timestamp+size, journal usage total, `.tool-row-id` (the identifier
   suffix task-ui-ux-4 already added), VAD numeric inputs, the `level:
   off` tag.
2. **Accent-emphasis scale.** Three tiers, reused across every view:
   - **Primary** (solid `--cyan` fill, dark text): the one commit/create
     action per view - Settings "Apply", Journal input dock "Send",
     Journal sidebar "New context".
   - **Secondary** (today's default look: `--cyan-tint` fill + `--cyan-
     dim` border + `--cyan` text): standing toggles' selected state,
     panel togglers (Memory/Annotations/Consolidation), Enable/Disable,
     MCP Enable/Disable, Attach.
   - **Ghost** (transparent, dim text, border appears on hover): Copy
     actions, Close buttons, session-row icon actions.
   - **Reasoning-level chip:** fold the selected pill's color from
     `--violet` to `--cyan`, matching the View and Open/Hidden segmented
     toggles it sits next to (all three are "one selected option in a
     row" controls and should share one selected-state color). Do not
     remove `--violet` from the palette - Hidden mode keeps it.
3. **Icon set.** Inline-SVG, outline style (24px viewBox, `currentColor`,
   ~1.75px stroke, round linecap/linejoin, no fill) matching the console's
   existing thin-line vocabulary (chip borders, ring, dots). Seven icons,
   wired to their existing actions (no new engine capability - these
   attach to commands that already exist):
   - **New** - Journal sidebar "+ New context" (primary button)
   - **Continue** - session row continue-conversation action (replaces
     the `&#8618;` glyph)
   - **Delete** - session row delete action (replaces the `&times;` glyph)
   - **Memory** - Journal toolbar Memory panel toggle
   - **Annotations** - Journal toolbar Annotations panel toggle
   - **Consolidation** - Journal toolbar Consolidation panel toggle
   - **Copy** - Journal feed copy-answer / copy-title / copy-name actions
4. **Session-card weight.** Invert `_journalSessionElement()`'s reading
   order: session title first (proportional face, full `--text`
   brightness, not dimmed by default), then one combined secondary line
   below it (date, time, duration, size - dimmed, monospace, single line
   in place of today's separate `.journal-session-when`/
   `.journal-session-size` rows). Selection state keeps its current
   border/tint treatment; the timestamp no longer needs to turn cyan to
   signal selection. Derived, non-distinguishing "New context" titles
   remain a separate, already-recorded, out-of-scope limitation.

## Boundary

- Front-end only; no engine/transport/control changes and no new engine
  capability - icons attach to commands that already exist
  (`deleteJournalSession`, `continueJournalSession`, the panel togglers,
  the copy actions).
- No editable session titles, no command palette, no Status-chip roving
  navigation (out of story scope).
- No further design review needed for the four items above - the mockup
  already carries owner approval. A genuinely new visual decision not
  covered by the mockup (not expected, but possible once real markup is
  touched) still stops for a question per this repo's standing rule
  (`CLAUDE.md` section 0.4/0.2).

## Acceptance criteria

- [ ] Monospace is confined to technical/tabular data; the labels,
      buttons, headings, and tool-row primary labels listed above use the
      proportional face.
- [ ] The three-tier accent-emphasis scale is applied per the mapping
      above; the reasoning-level selected chip is cyan, not violet.
- [ ] The seven-icon set is implemented and wired to its existing action
      in each of the seven locations listed above.
- [ ] Session cards lead with the title (full brightness, proportional);
      date/time/duration/size are one dimmed monospace line beneath it.
- [ ] New/changed user-facing strings (if any icon needs an accessible
      name beyond what already exists) are in both `en` and `ru`.
- [ ] Browser-preview handoff prepared covering Status, Journal
      sidebar/feed, and Settings TTS in light and dark surfaces where
      applicable.
- [ ] `python -m pytest` passes; `ruff check` and `ruff format --check`
      are clean.

## Verification record

(to be filled at completion)
