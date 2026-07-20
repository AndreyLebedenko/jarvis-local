# Task v1.6.1-2: set_reasoning_level builtin tool

**Status:** Completed.
**Story:** `tasks/done/story-v1.6.1-builtin-tools-delegated-control.md`
**Depends on:** task-v1.6.1-1 (builtin provider core).

## Summary

The first builtin tool: `set_reasoning_level` mutates the existing
reasoning-level state through the audited tool path. The change applies
from the next accepted turn; the confirming reply is an ordinary tool
round trip.

## Context you need

- `src/jarvis/dialog/thinking_mode.py`: `ReasoningLevelState` is the
  single state owner; `set_level(level, source=...)` publishes
  `ReasoningLevelChanged` with a required source tag (the 2026-07-13
  stale-tag bug is why the tag is required - do not default it).
- `src/jarvis/app.py`: where the reasoning level is sampled at
  turn-construction time ("sampled at turn start" contract) and where
  the builtin provider from task 1 is built - the tool needs the state
  object injected.
- Story design decision: hotkey, UI, and tool paths all converge on the
  same state owner; UI honesty comes from the existing event, no new
  wiring.
- Roadmap cross-cutting rule 9: reasoning level is on the allowlist;
  nothing else is. Do not generalize the tool into a settings setter.

## Boundary

- One tool, one setting. No generic "set setting" schema, no reading
  back other engine state, no changes to hotkey or UI paths.
- The "sampled at turn start" contract is untouched: no attempt to
  apply the new level to the in-flight turn.
- self.md content about this capability is data, owner-authored; not
  part of this card's code change.

## Requirements

- Tool schema: a single required argument accepting exactly the
  existing levels (`off`/`low`/`medium`/`high`); invalid values fail
  schema-side or as a clear tool error, never by guessing.
- The tool calls `ReasoningLevelState.set_level` with a distinct source
  tag (working name `TOOL`); setting the current level again is a
  success (state owner already no-ops the event) and the tool result
  says the level is already active.
- The tool result text gives the model enough to confirm naturally:
  new level, and that it applies from the next turn.
- The audit trail shows the requested level in the outbound summary
  (`ToolCallStarted.arguments`), so the events panel answers "what did
  the model change and when".

## Acceptance criteria

- [x] Tests cover: a dispatched tool call changes
      `ReasoningLevelState.level` and publishes `ReasoningLevelChanged`
      with the tool source tag; the in-flight turn's sampled level is
      unaffected (next-turn semantics); invalid level values produce a
      failed tool result and no state change; setting the already-active
      level succeeds without a spurious event.
- [x] A human-run handoff scenario exists for the voice path: ask
      Jarvis by voice to raise the reasoning level, confirm the reply,
      the Control Center indicator, and that the next turn actually
      reasons at the new level.
- [x] `python -m pytest` and Ruff checks are green.

## Implementation outcome

`set_reasoning_level` accepts `off`, `low`, `medium`, or `high` and calls
`ReasoningLevelState.set_level(..., source="TOOL")`. Its result states that
the level applies from the next accepted turn.

Automated verification: `python -m ruff format --check .`,
`python -m ruff check .`, and `python -m pytest` are green.
