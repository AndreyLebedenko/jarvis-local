# Task: UI language docs and manual handoff

**Story:** `tasks/story-v1.2.11-ui-english-localization.md`
**Status:** Completed.
**Release:** v1.2.11

## Summary

Document the `ui.language` setting and prepare the human-run visual
verification for both languages. Close the story.

## Current Boundary

In scope:

- Document `ui.language` (values, default, config layering) in the README /
  config documentation, and record the decision in `PROJECT.md` (UI chrome
  is localized; dialog language and system prompt are unaffected).
- A manual check script or checklist covering: default English rendering of
  Status Console and Touchstrip, `ui.language: ru` rendering, microphone
  mute/wake detail texts, settings dialog, reset/shutdown confirmations, and
  absence of any change in spoken output.
- Hand over exact commands for the human run and wait for the report.

Out of scope:

- Any code changes beyond documentation and the manual check materials;
  defects found during the handoff get their own fix scope or a bug report
  under `tasks/bug_reports/`.

## Acceptance Criteria

- [ ] `ui.language` is documented where other config settings are documented.
- [ ] `PROJECT.md` records the UI localization decision and the UI/dialog
      language boundary in the same commit as the change.
- [ ] Manual handoff instructions cover both languages and are executable
      as written.
- [ ] Human report confirms both languages render correctly; issues, if any,
      are filed as bug reports.

## Stop Conditions

- Stop if the manual run reveals mixed-language output whose correct side of
  the UI/dialog boundary is ambiguous.
