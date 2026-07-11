# Task: Initial tools and manual handoff

**Story:** `tasks/story-v1.4.0-mcp-integration.md`
**Status:** Planned. Blocked by tasks 2, 4, 5.
**Release:** v1.4.0

## Summary

Configure the first two real tool providers - web search and a local/LAN
database - and prepare the consolidated human-run verification of the whole
MCP path. The agent writes configs, scripts, and the checklist; the human
runs everything that needs network, a live model, or visual judgment.

## Current Boundary

- Web search: an existing MCP search server, run as a configured stdio
  subprocess. This is the first component with the external-network
  capability under the task-2 contract: disabled by default, enabled
  explicitly, visible in the data-source axis. Provider choice (which
  search backend, whether it needs an API key) is a blocking question for
  the human before implementation - keys, if any, live outside the repo.
- Database: an MCP server over a local or LAN database (read-only
  queries). Stays inside the LAN perimeter; exercises the multi-tool
  registry and tool-choice behavior without external network.
- Manual handoff checklist (exact commands prepared by the agent):
  - MCP off: no processes, no connections, no UI presence, dialog
    behavior unchanged;
  - toggle on from Control Center: servers connect, registry populates,
    state indication truthful;
  - a voice turn that triggers web search end-to-end, with the external
    label on the data-source axis and call/outcome events in the panel;
  - a turn that queries the database; a turn that must call no tool;
  - tool failure (kill a server mid-session): honest degraded state, turn
    still terminates with a text answer;
  - toggle off mid-session: clean disconnect, capability disappears.
- Update `README`/`README.ru` for setup of the two servers.
- After human confirmation, record verified end-to-end facts in
  `PROJECT.md`.

## Acceptance Criteria

- [ ] Both servers are configured through the standard component config;
      no hardcoded commands in engine code.
- [ ] Automated tests cover config parsing and the checklist script's
      wiring (no live servers in CI).
- [ ] `python -m pytest` passes.
- [ ] Human has run the full checklist; results and any bug reports
      recorded before the story closes.
- [ ] Story acceptance criteria checked off against these results.

## Stop Conditions

- Stop if the chosen search server cannot run as a local subprocess and
  would require a cloud relay - that violates the host-side architecture
  and needs a human decision.
- Stop if any checklist item can only pass by faking capability or
  hiding a failure.
