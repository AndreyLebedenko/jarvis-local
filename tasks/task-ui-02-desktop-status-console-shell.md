# Task UI-02: Desktop Status Console shell

**Story:** story-status-console-ui.md
**Статус:** Backlog
**Приоритет:** высокий
**Зависимости:** task-ui-01-state-and-event-contract.md

## Summary

Build the first desktop Status Console shell: top-level window, status orb,
module chips and basic layout. This is a status surface, not a settings app.

## Scope

- Main status orb with runtime state label and concise substatus.
- Module chips for model/backend, microphone, TTS, memory and vision/screen.
- Data locality indicator for current supported backend mode.
- Space reserved for Think/reset controls and system events panel.
- Responsive layout that works on ordinary desktop and narrow widths.

## Acceptance Criteria

- [ ] UI can render all contract states from task UI-01.
- [ ] No hardcoded model name; model/backend label comes from config/runtime.
- [ ] No Google Fonts or network-loaded assets.
- [ ] `WARMING` styling is distinct from cloud/network warning.
- [ ] Layout remains readable at narrow widths without overlapping text.

## Stop Condition

If choosing the GUI framework has architectural consequences not settled in
PROJECT.md or story docs, stop and ask before implementing the shell.

