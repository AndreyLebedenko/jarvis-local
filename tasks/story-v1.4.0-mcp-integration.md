# Story v1.4.0: MCP Integration

**Status:** In progress. Tasks 1-3 are completed; tasks 4-6 remain planned.
**Release gate (human decision, 2026-07-14): the
human will not approve shipping v1.4.0 without
`tasks/backlog/mcp-egress-watchdog.md` landing first** - see the Release
Gate section below.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.4.0
**Vision:** `VISION.md` - component model, capability-bounded adapters,
no silent high-impact actions.

## User-facing goal

Jarvis gains its first tool-use capabilities through MCP - initially web
search and a local/LAN database - so it can answer questions it is
fundamentally unable to answer today. The MCP module is off by default,
switchable from the Control Center with clear state indication, and every
external call is visible to the user.

## Architecture position

- Jarvis is the MCP host. It connects to MCP servers as registered
  tool-provider components and decides how their tools are presented to
  the model. Ollama sees only per-request tool declarations; MCP servers
  never talk to Ollama.
- How tools are presented to the model (native `tools` field versus
  prompt-based declaration) is a swappable layer; the task-1 spike decides
  the default with measured facts.
- All tool calls flow through a single interception point between "model
  requested" and "executed". Policy lives there: per-tool enablement,
  visibility events, audit logging, and - later, outside this story - a
  watchdog/policy component.

## Boundaries

- MCP module off by default. When off, no MCP server connection is opened
  and no tool declaration reaches the model - equivalent to the capability
  not existing. The state persists across restart via the layered config.
- Core and inference remain local unconditionally. External network access
  is a per-component capability, enabled explicitly by the user, and
  reflected honestly in the data-source axis.
- Tool results are current-turn context. No background or autonomous tool
  loops; a bounded number of tool round-trips per turn.
- No silent high-impact actions; the first tool set is read-only
  (search, database queries), not action-taking.
- Jarvis-as-MCP-server (exposing Jarvis's capabilities outward) is out of
  scope.
- Watchdog logic beyond the interception seam itself is out of scope; the
  seam is in scope.

## Release Gate

**Human decision, 2026-07-14: v1.4.0 introduces Jarvis's first outbound-
network capability, and the human will not approve the release without an
egress watchdog/policy component in place** - a process that can inspect
and cut off a suspicious outbound MCP tool call before it leaves the
machine. This is deliberately **not** one of this story's task cards
(tasks 1-6 build the interception point and the data it needs, not the
policy layer on top) - it is tracked as its own backlog story,
`tasks/backlog/mcp-egress-watchdog.md`, which attaches at task 3's single
interception point without rewiring it. Concrete cutoff rules are not yet
written; that happens in a separate planning pass closer to
implementation. Do not treat this story's own Acceptance Criteria as
sufficient for a release decision - they cover the MCP host/tooling
mechanism, not the release-gate condition recorded here.

## Prerequisites

- [x] Task-1 spike facts recorded in `PROJECT.md` (hard gate for tasks 3+):
      native `tools` chosen as the default presentation strategy
      (2026-07-14).
- [x] Task-2 locality contract revision accepted (gate for tasks 3+ as
      well: no real MCP server may be configured under the old contract).
      Two-tier contract recorded in `PROJECT.md`, `VISION.md`, roadmap
      rule 3, and `CLAUDE.md`/`AGENTS.md` (2026-07-14).
- [x] v1.3.0 Control Center exists (gate for tasks 5-6 only).
- [x] Search provider choice accepted by the human (2026-07-14): no API
      key, minimal external identification. DuckDuckGo (unofficial,
      keyless client) is the default provider; self-hosted SearXNG is
      the documented fallback if DuckDuckGo's unofficial contract
      breaks. Task-6 must add a provider-abstraction seam (canonical
      `web_search` tool name/schema, adapter underneath) so swapping or
      patching the provider does not touch tasks 3/4. See task-6's
      Current Boundary for the resolved detail.

## Acceptance Criteria

- [ ] With MCP disabled, runtime behavior and network posture are
      byte-identical to pre-v1.4.0: no connections, no declarations, no
      new prompts to the model.
- [ ] With MCP enabled, at least web search and one database tool work
      end-to-end through the interception point.
- [ ] Control Center shows an MCP toggle with truthful current state; the
      data-source axis reflects turns whose tool calls left the machine.
- [ ] Every tool call and its outcome appear in system events.
- [ ] Locality contract revision is recorded in `PROJECT.md`, `VISION.md`,
      and roadmap rule 3 before the first external call is possible.
- [ ] `python -m pytest` passes; all pure logic (declaration building,
      interception, dispatch, config) covered without live servers.

## Task Card Sequence

1. `story-v1.4.0-task-1-tool-calling-spike.md`
   Measure native `tools` vs prompt-based contract on the local model.
   Hard gate: no implementation before facts land in `PROJECT.md`.
2. `story-v1.4.0-task-2-locality-contract-revision.md`
   Revise the locality contract explicitly across project docs.
3. `done/story-v1.4.0-task-3-mcp-host-core.md`
   MCP client, tool registry, single interception point, switchable
   module state.
4. `story-v1.4.0-task-4-model-presentation-layer.md`
   Present tools to the model per the spike decision; parse tool requests;
   bounded tool round-trip loop.
5. `story-v1.4.0-task-5-control-center-mcp-surface.md`
   MCP toggle with state indication; data-source axis wiring; optional
   read-only tool list.
6. `story-v1.4.0-task-6-initial-tools-and-manual-handoff.md`
   Web search and database tools; consolidated human-run verification.

## Stop Conditions

- Stop if the spike shows tool calling on the local model is too
  unreliable for either presentation strategy - re-plan the release.
- Stop if any implementation path would bypass the single interception
  point.
- Stop if disabling MCP cannot be made equivalent to the capability not
  existing.
- Stop if locality, data-source presentation, and tool network behavior
  conflict in any concrete state.
