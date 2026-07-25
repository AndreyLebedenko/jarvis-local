# Task: Separate local tools from external tools in the Status Console

**Status:** Completed.
**Verified:** owner-run visual check, 2026-07-25.
**Raised by:** owner, 2026-07-24: "MCP is marked as off, but after I
ticked the box the cameras became available - isn't that misleading?"
**Depends on:** `tasks/task-tool-row-states-and-refresh.md`, so this card
moves rows that already say the right thing.

## Summary

Local builtin tools live inside a card titled "External tools (MCP)"
whose own status line reads "Off". Nothing in the panel says that heading
and status do not apply to three of its rows. Split the card so the state
shown always describes the things shown under it.

## Context you need

- `src/jarvis/ui/status_console_ui/index.html:67-77`: one `mcp-card`
  holds the MCP heading, the MCP status line, the MCP enable button, and
  the list of every tool regardless of provider kind.
- `src/jarvis/ui/status_console.py:104`, `mcp_state_payload()`: one
  payload carries MCP module status and all tools together. Each tool
  already declares `provider_kind`, so the data needed to split exists;
  only the presentation conflates them.
- Builtin tools are not governed by the MCP switch at all. The observed
  sequence proves it: the card said "Off", the user ticked
  `capture_camera_image`, and the camera became ready.
- `src/jarvis/ui/status_console.py:583`: the `capture_camera_image` row is
  not an ordinary tool row. It routes to `_set_camera_enabled()`, which
  probes the sources and drives the module's privacy state. The camera
  privacy switch is currently presented as a checkbox in a list of tool
  availability toggles.
- PROJECT.md's v1.6.3 placement rule: placement is decided by the nature
  of the data. Local-and-always-present differs from
  external-and-switchable on exactly the axis this card is about.
- Cross-cutting rule 9 (roadmap): privacy-relevant controls are never
  delegable. This card is the display side of the same concern - a
  control the user cannot correctly read is a control they do not
  actually hold.

## Boundary

- Presentation and its payload shape. No change to what any switch does,
  to the MCP lifecycle, or to which tools exist.
- Status tab only. The Settings tab and the touchstrip are out of scope
  unless the payload change forces a mechanical edit there.
- Not a story: no new capability, no new control, no config.

## Requirements

- A status line and an enable button describe only the tools shown with
  them. Whatever the final layout, a user must not be able to read a
  disabled state as applying to a tool that is in fact running.
- Local builtin tools are presented as what they are: always present,
  independent of the MCP module, individually switchable.
- The camera's row is the privacy switch for the camera module, not a
  tool-availability checkbox among others. It should read as the same
  kind of control as microphone sleep - decide whether that means a
  distinct affordance or just distinct labelling, and record the choice.
  Do not silently leave it looking like its neighbours.
- Both UI languages stay key-identical and are both checked by eye; this
  is a card about wording as much as boxes.
- Automated tests cover the payload split and that a tool of each
  provider kind lands in the right group.

## Acceptance criteria

- [x] With MCP off, no part of the console suggests that the local
      builtin tools are off.
- [x] Enabling or disabling MCP visibly changes only the external group.
- [x] The camera control is distinguishable from an ordinary tool toggle.
- [x] `python -m pytest` and Ruff are green.
- [x] Owner-run visual check of the Status tab in both languages.

## Outcome

Two cards, as recommended. Grouping happens in `mcp_state_payload()`
rather than in markup, so the engine hands the UI `tools` and
`local_tools` separately and a status line cannot be rendered over
something it does not govern.

The camera row is marked `is_privacy_switch` and says so in words. A
violet tint was tried first and rejected on review: a tinted row reads as
decoration or as a state, and it cannot tell anyone what makes that row
different - which was the entire purpose of marking it. The label carries
the meaning; that lesson is what
`tasks/task-tool-rows-name-capabilities.md` builds on.

Vertical cost was paid back rather than absorbed: the local card has no
button and a shorter list bound (108 px), since the builtin provider's
tool count grows far more slowly than an MCP server's.

Noted and not acted on: `demo.html` duplicates `index.html`'s markup and
has never carried the tool panel at all, so this surface cannot be
reviewed without a live engine. Left alone rather than deepening the
duplication silently; it wants its own decision - either the harness
loads the real markup, or it honestly declares that it covers the orb and
chips only.

## Open question for the owner (answered: two cards)

Two shapes are plausible and the choice is yours, because it is about
what the console is for rather than about code:

- **Two cards on Status.** Simple, honest, and it makes the local tools
  visible as a first-class thing. Costs vertical space on a tab that
  v1.6.3 already fought to fit into 900 px.
- **One card, two labelled groups.** Cheaper vertically, but it keeps a
  single heading over both kinds and needs careful wording so the MCP
  status line clearly binds to its own group only.

I lean to two cards: the v1.6.3 density work was about fitting what
belongs on Status, not about merging things that differ in kind, and this
particular conflation has already misled the person who built it.
