# Task: Tool row states and refresh after a toggle

**Status:** Completed.
**Verified:** owner-run visual check, 2026-07-25.
**Raised by:** owner, 2026-07-24, reviewing the Status Console after
v1.6.2 closed.
**Related:** `tasks/task-local-and-external-tool-panels.md` does the
structural half. This card is the wording and freshness half and lands
first, so that card only moves rows rather than also redefining them.

## Summary

A tool row in the Status Console reports two orthogonal facts - can the
provider serve this tool, and has the user switched it on - through one
word, and then does not refresh when that word changes. Give the row the
three states it actually has, and repaint it when a toggle lands.

## Context you need

- `src/jarvis/ui/status_console_ui/app.js:226`:
  `tool.available && tool.enabled ? "mcp_tool_available" :
  "mcp_tool_unavailable"`. Two words for three states.
- `src/jarvis/ui/status_console.py:119`: `available` for a builtin tool is
  `tool.provider_kind == "builtin" or mcp_available`, so a builtin tool is
  always available. A builtin tool that is merely switched off therefore
  renders as "unavailable" - the word the UI also uses for a dead
  provider.
- `src/jarvis/ui/status_console.py:583`, `set_tool_enabled()`: it mutates
  the registry and publishes nothing. The camera is the exception only by
  accident - it routes through `_set_camera_enabled()`, which publishes
  camera state, which is why the observed screenshot had a refreshed
  camera chip beside a stale tool row saying "unavailable" next to its own
  ticked checkbox.
- `src/jarvis/ui/status_console_ui/strings.js`, the `en` and `ru` tables:
  both must stay key-identical, and a test asserts that.

## Boundary

- Wording, state derivation, and the state push after a toggle. Moving
  rows between panels is the other card.
- No change to what `available` means on the engine side, and no change
  to who may toggle what. Cross-cutting rule 9 stands: privacy-relevant
  controls stay non-delegable.

## Requirements

- A row distinguishes three states: the provider can serve it and it is
  on; the provider can serve it and the user has it off; the provider
  cannot serve it. The third state overrides the second - a tool the user
  enabled but whose provider is down reads as unavailable, not as on.
- The new middle state gets its own string in both languages. "Off" is
  the user's own decision and must not borrow the vocabulary of failure.
- Toggling a tool refreshes the tool list, so a row's checkbox and its
  own label can never contradict each other. Whatever mechanism is used,
  the refresh must also cover a toggle that the engine rejects as stale
  (`set_tool_enabled` already logs that case) - the row must end up
  showing the engine's truth, not the click's optimism.
- Automated tests: the three states render their three distinct labels;
  an enabled-but-unavailable tool reads unavailable; a toggle produces a
  fresh tool-list payload; `en` and `ru` key sets stay identical.

## Acceptance criteria

- [x] A builtin tool that is simply switched off no longer reads as
      "unavailable" in either language.
- [x] After ticking or unticking a tool, its label matches its checkbox
      without a manual refresh.
- [x] `python -m pytest` and Ruff are green.
- [x] Owner-run visual check in both languages, since this is UI text.

## Outcome

The three-state wording this card asked for did not survive review, and
should not have: on/off duplicates the checkbox, and writing it out was
the original defect wearing a new hat - it is exactly what made an
available tool the owner had switched off share a word with a dead
provider. A row now states only unavailability, because that is the one
thing the checkbox cannot explain: it refuses to move and does not say
why. Two catalog strings were deleted rather than three added.

The refresh half landed as designed. `ToolEnablementChanged` carries no
payload deliberately: the UI re-reads the whole registry, so a row the
event did not happen to name cannot drift out of step. It is published
even when the engine rejects the toggle as stale, because the click has
already moved the checkbox in the browser either way.

Naming the rows in the user's language turned out to be its own question
and became `tasks/task-tool-rows-name-capabilities.md`.
