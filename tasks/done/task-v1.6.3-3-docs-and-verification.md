# Task v1.6.3-3: Docs and verification

**Status:** Completed. Docs and localization audit complete; the
checklist below was superseded 2026-07-22 by the combined v1.6.3 + v1.6.4
checklist in
`tasks/done/task-v1.6.4-3-docs-and-release-verification.md` (sections A-E
are this card's items, unchanged) - both stories exercise the same Status
Console, and two separate runs would open the same window twice. The
human ran the combined checklist on 2026-07-22; outcomes are recorded
there, not here.
**Story:** `tasks/done/story-v1.6.3-status-console-ui-reorg.md`
**Depends on:** tasks v1.6.3-1..2, and v1.6.3-4 (density), which reworked
the Status column after this card was written.

## Summary

Update documentation for the three-tab layout, audit localization
completeness, and prepare the human-run release verification
checklist for v1.6.3.

## Context you need

- Story acceptance criteria (the full per-tab layout contract).
- `PROJECT.md`: any sections describing the Status Console's
  structure (view names, where controls live) that the
  reorganization dates.
- README/user docs where the console UI is described or
  screenshotted.
- Release verification precedent:
  `tasks/done/task-v1.5.2-8-docs-and-release-verification.md`.

## Boundary

- Documentation and checklist only; verification-revealed fixes
  larger than trivial become bug reports per the project protocol.

## Requirements

- `PROJECT.md` and user docs reflect the three-tab structure and the
  runtime-vs-cold-config placement rule as the recorded design
  criterion (so future controls get placed by the rule, not by
  taste).
- Localization audit: every string added, moved, or removed across
  tasks 1-2 is present in both languages and no orphaned entries
  remain in the catalog.
- Human-run checklist covering: all three tabs in both UI languages,
  header honesty indicators and Open/Hidden on every tab, Hidden
  mode parity with pre-reorg behavior, each moved control end to end
  (reasoning from UI/hotkey/voice once v1.6.1 lands - scope to what
  exists at verification time), MCP toggle and tool list, a settings
  edit applying, context reset only in the Journal, and Shutdown.
- Note explicitly in the checklist that WebView visual review is
  human-run per the testing protocol.

## Localization audit result (2026-07-21)

Audited by comparing the two catalogs in `strings.js` against every
consumer (`index.html`, `demo.html`, `touchstrip.html`, `app.js`,
`touchstrip.js`), accounting for keys built from a prefix at runtime
(`last_request_`, `mcp_`, `chip_reset_`, `journal_source_`, and the
rest):

- The `en` and `ru` key sets are identical; neither has a key the other
  lacks.
- No unreferenced keys remain. `btn_settings`, `confirm_reset_text`,
  `btn_confirm_reset`, `view_console`, and `last_request_title` were
  removed with their controls. `btn_reset_context` stays because
  `touchstrip.html` still uses it - it is not orphaned by the console's
  removal of the duplicate reset.

## Human-run verification checklist

WebView visual review is human-run per the testing protocol; nothing
below is something the agent can sign off. Run Jarvis normally, once per
UI language (`[ui].language = "en"` and `"ru"`), and record the outcome.

**Header, on every tab**

1. Exactly three tabs render: Status, Journal, Settings.
2. Brand, `LOCAL`, `LOCAL SOURCES`, and Open/Hidden stay in place and
   keep their values when switching tabs.
3. Tab captions are translated; no English text leaks into the Russian
   UI and no key names render raw.

**Status**

4. No scrollbar at the default window size immediately after startup.
5. After a voice turn, the chip strip under the orb shows the voice
   modality with its duration; after a screen-capture turn, it shows the
   screenshot modality.
6. Module chips, including the v1.6.2 camera chip, reflect live health.
7. Reasoning level changes made by hotkey and by voice both render here,
   not only changes made from this tab.
8. MCP toggle round-trips: enable, tools appear, disable, tools clear.
   With a long tool list, the list scrolls inside its own card and
   Shutdown does not move.
9. System events keep arriving while other tabs are open and after
   returning to Status.
10. Shutdown asks for confirmation; opening the confirmation does not
    move the Shutdown button. Cancel leaves the engine running.
11. There is no context reset control anywhere on Status.

**Journal**

12. Opens without reload loops; the feed, memory files, and attachments
    behave as before the reorganization.
13. "Новый контекст" is present and is the only context reset on this
    surface.
14. Switching away with unsaved memory edits still asks for
    confirmation, and cancelling keeps the edits.

**Settings**

15. Contains model, microphone, UI language, TTS routes, and VAD.
16. Entering the tab refreshes model and microphone options; Apply stays
    disabled until both have loaded.
17. A settings edit saves and reports restart-to-apply; the change is
    present in `config.ui.toml` and takes effect after a restart.
18. There is no Settings button anywhere on Status.

**Hidden mode**

19. Hidden behaves exactly as before the reorganization on all three
    tabs; Journal content is replaced by the generic placeholder and no
    memory or journal text is exposed.
20. Switching tabs while Hidden never reveals content that Open mode
    would show.

## Acceptance criteria

- [x] `PROJECT.md` and user docs updated in the same release as the
      layout change. Screenshots in the README files are refreshed by
      the human, not by the agent.
- [x] The localization audit is complete and recorded above.
- [x] The human-run checklist is prepared and handed off; verified
      outcomes are recorded before the story closes.
- [x] `python -m pytest` and Ruff checks are green.
