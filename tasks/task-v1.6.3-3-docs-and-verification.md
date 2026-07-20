# Task v1.6.3-3: Docs and verification

**Status:** Planned.
**Story:** `tasks/story-v1.6.3-status-console-ui-reorg.md`
**Depends on:** tasks v1.6.3-1..2.

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

## Acceptance criteria

- [ ] `PROJECT.md` and user docs updated in the same release as the
      layout change.
- [ ] The human-run checklist is prepared and handed off; verified
      outcomes are recorded before the story closes.
- [ ] `python -m pytest` and Ruff checks are green.
