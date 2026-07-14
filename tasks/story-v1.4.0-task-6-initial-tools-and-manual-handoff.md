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
  explicitly, visible in the data-source axis.
  **Provider choice, resolved (human decision, 2026-07-14): no API key,
  minimal external identification.** Default: DuckDuckGo via an
  unofficial keyless client (the `duckduckgo-search`/`ddgs` pattern),
  run as a local subprocess - no billing account, no key outside the
  repo, and it satisfies this task's own subprocess requirement
  natively. Documented fallback if DuckDuckGo's unofficial contract
  breaks: a self-hosted SearXNG instance (also keyless from Jarvis's
  side, aggregates multiple engines) - closer to the database tool's
  LAN-perimeter shape than to a zero-setup subprocess, since it needs
  its own local/LAN service running.
  Provider swap must stay cheap: the MCP layer already gives
  config-level swappability (which stdio command to launch is
  component config, not hardcoded, per this task's own acceptance
  criterion), but different search MCP servers will not necessarily
  agree on tool/argument names. This task must expose one canonical
  `web_search` tool name/schema to the model and adapt the underlying
  provider's actual tool call under it, so replacing or patching the
  provider later never touches the model-presentation layer (task 4)
  or the interception point (task 3).
- Database: an MCP server over a local or LAN database (read-only
  queries). Stays inside the LAN perimeter; exercises the multi-tool
  registry and tool-choice behavior without external network.
- Provider configuration must declare `data_boundary` explicitly for both
  initial providers: `internet` for web search and `local` or `lan` for the
  database according to the selected deployment. If a provider exposes
  tools with different reach, use the per-tool `tool_boundaries` overrides.
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
- [ ] Both servers declare truthful data boundaries, and the manual
      checklist confirms the data-source axis distinguishes local, LAN,
      and internet calls.
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
