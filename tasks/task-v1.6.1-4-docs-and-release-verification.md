# Task v1.6.1-4: Docs and release verification

**Status:** Planned.
**Story:** `tasks/story-v1.6.1-builtin-tools-delegated-control.md`
**Depends on:** tasks v1.6.1-1..3.

## Summary

Record the delegation allowlist boundary and the builtin provider
contract in `PROJECT.md`, update config documentation, and prepare the
human-run release verification checklist for v1.6.1.

## Context you need

- Roadmap cross-cutting rule 9 (the allowlist wording to record) and
  the v1.6.1 boundary (builtin tools never conflated with MCP on the
  data-source axis).
- Story design decisions: always-on availability with per-tool toggle,
  reserved provider name, `TOOL` source tag, memory write semantics.
- `PROJECT.md`: tool registry / MCP host sections that the builtin
  provider revises, and the memory files section from v1.5.3.
- Release verification precedent:
  `tasks/done/task-v1.5.3-7-docs-and-release-verification.md` and
  `tasks/done/task-v1.6.0-10-release-verification.md`.

## Boundary

- Documentation and checklist only; code changes limited to fixes the
  verification itself reveals as in-scope for this story (anything
  larger becomes a bug report per the project protocol).

## Requirements

- `PROJECT.md` records, as settled facts:
  - the builtin provider concept (in-process dispatch, same
    interception point, `data_boundary = local`, always-on with
    per-tool toggle, independence from the MCP module switch);
  - the delegation allowlist: reasoning level and the two memory
    files are delegable; microphone sleep, visibility mode, MCP
    module toggles, and MCP server enablement are never delegable;
  - the memory-write contract (audited tool path, caps, next-session
    injection).
- Config documentation (`config.example.toml` and any config docs)
  covers new settings introduced by tasks 1-3, if any.
- A human-run checklist covering: voice-delegated reasoning change
  (reply, indicator, next-turn effect), "remember this" end to end
  including next-session recall, over-cap refusal behavior, builtin
  tools visible and toggleable in the Control Center with MCP off and
  on, and no builtin regression when the MCP module is toggled during
  a session.

## Acceptance criteria

- [ ] `PROJECT.md` and config docs updated as above, in the same
      release as the delegation feature (rule 9's requirement).
- [ ] The human-run checklist is prepared and handed off; verified
      outcomes are recorded before the story closes.
- [ ] `python -m pytest` and Ruff checks are green.
