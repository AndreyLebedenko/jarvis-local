# Task: Initial tools and manual handoff

**Story:** `tasks/story-v1.4.0-mcp-integration.md`
**Status:** In progress. Provider choice accepted 2026-07-14; prerequisite
tasks 2, 4, and 5 are completed.
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
  minimal external identification.** Default: DDGS's stdio MCP server,
  with its text-search backend fixed to `duckduckgo`; DDGS is an
  independent metasearch library, not an official DuckDuckGo API.
  Documented fallback if this unofficial contract breaks: a self-hosted
  SearXNG instance (also keyless from Jarvis's side, aggregates multiple
  engines) - closer to the database tool's LAN-perimeter shape than to a
  zero-setup subprocess, since it needs its own local/LAN service running.
  Provider swap must stay cheap: the MCP layer already gives
  config-level swappability (which stdio command to launch is
  component config, not hardcoded, per this task's own acceptance
  criterion), but different search MCP servers will not necessarily
  agree on tool/argument names. This task must expose one canonical
  `web_search` tool name/schema to the model and adapt DDGS's
  `search_text` call under it, fixing `backend = "duckduckgo"` and exposing
  only the bounded text-search arguments. DDGS's image/news/video/book and
  arbitrary URL-extraction tools are not registered. Replacing or patching
  the provider later must never touch the model-presentation layer (task 4)
  or the interception point (task 3).
- Database: the official Qdrant MCP server in read-only mode. The default
  example uses `QDRANT_LOCAL_PATH` and a separately seeded synthetic
  knowledge collection; an optional `QDRANT_URL` profile points to a LAN
  deployment with the same canonical tool surface. Only upstream
  `qdrant-find` is exposed, as `search_local_knowledge`; `qdrant-store` must
  be absent. This exercises local semantic retrieval, the multi-provider
  registry, and both local/LAN boundary declarations without granting a
  runtime write capability.
- Provider subprocesses live in isolated provider virtual environments,
  not Jarvis's core environment. In particular, Qdrant MCP 0.8.x pins an
  older Pydantic range than the current Jarvis environment; optional MCP
  components must not downgrade or otherwise constrain core dependencies.
- Generic task-6 provider-adapter seam:
  - per-server environment variables are passed through the existing stdio
    process boundary;
  - a non-empty adapter table is an allowlist of upstream tools;
  - each entry declares one canonical public name, optional description,
    allowed model arguments, and fixed provider arguments;
  - fixed arguments are hidden from model input, applied by the host, and
    appear in outbound audit data;
  - a missing or schema-incompatible upstream tool is an honest degraded
    provider state, not a silently empty healthy registry.
- Provider configuration must declare `data_boundary` explicitly for both
  initial providers: `internet` for web search and `local` or `lan` for the
  Qdrant profile according to the selected deployment. The consolidated
  checklist runs the local profile and the optional LAN profile separately
  so all three axis states are observed. If a provider exposes tools with
  different reach, use the per-tool `tool_boundaries` overrides.
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
- [ ] The model sees only canonical `web_search` and
      `search_local_knowledge`; upstream names and fixed provider arguments
      are handled below the model-presentation layer.
- [ ] Qdrant runtime configuration is read-only and the write tool is not
      registered; demo seeding is a separate, explicit setup action.
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
