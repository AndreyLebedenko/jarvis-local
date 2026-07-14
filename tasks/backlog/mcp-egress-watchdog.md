# Backlog story: MCP egress watchdog

**Status:** Backlog. Not a v1.4.0 task card - see the Release Gate note in
`tasks/story-v1.4.0-mcp-integration.md`.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Target:** pre-release gate for v1.4.0 - must exist before the human
approves the v1.4.0 release, even though it ships as its own story after
(or alongside) `story-v1.4.0-mcp-integration.md`'s task cards.

## User-facing goal

A process that watches what Jarvis's MCP tool calls actually send outward
and can cut off a call before it leaves the machine if it looks
suspicious. Human decision (2026-07-14): v1.4.0 introduces Jarvis's first
outbound-network capability (MCP web search); the human will not approve
that release without this protection in place. Concrete cutoff rules are
out of scope for this card and will be specified separately, closer to
implementation, once real tool-call shapes exist to write rules against.

## Architecture position

- Attaches at the single interception point already required by
  `story-v1.4.0-task-3-mcp-host-core.md` ("All tool calls flow through a
  single interception point between 'model requested' and 'executed'...
  a later watchdog/policy component attaches there without rewiring").
  This card is that later component - no new interception seam needed,
  the seam is already a hard requirement of task 3.
- Consumes the outbound-data summary task 3 already produces on every
  call/outcome system event (tool name, provider, duration, user-readable
  summary of what is being sent and to which provider) - task 3's
  acceptance criteria explicitly call this out as existing "for ... later
  watchdog rules."
- Surfaces in the Control Center's reserved "dangerous capabilities"
  section (`tasks/done/story-v1.3.0-control-center.md`: "the section
  itself ships with the first release that has a real action-taking
  capability behind it (post-v1.4.0 actions/watchdog story)").

## Boundaries

- Not part of `story-v1.4.0-mcp-integration.md`'s task sequence (tasks
  1-6). Those tasks build the interception point and the data it needs;
  this story builds the policy layer on top.
- Rules are not defined here. This card is the placeholder for the
  architecture and the release-gate status; a follow-up planning pass
  writes the actual cutoff rules before implementation starts.
- Read-only visibility (system events, outbound-data summaries) already
  exists via task 3/5 regardless of this story landing. What this story
  adds is the ability to block a call before it executes, not just log
  it after the fact.

## Open Questions

- What counts as "suspicious": destination allowlist/denylist, payload
  content heuristics, size thresholds, rate limits, or some combination?
- Does a blocked call fail the turn silently-to-the-model (tool returns
  an error) or does it need a distinct user-visible signal beyond the
  existing system-events panel?
- Does this need to be synchronous (block before the packet leaves) or is
  a fast-follow kill-switch after the first bytes acceptable, given MCP
  tool calls are not streaming raw sockets?

## Stop Conditions

- Stop if enforcing a block cannot happen before the outbound call
  actually executes without restructuring task 3's interception point -
  that would mean task 3 built the wrong seam and needs revisiting first.
- Stop if the human has not yet specified concrete cutoff rules by the
  time this card would otherwise start implementation.
