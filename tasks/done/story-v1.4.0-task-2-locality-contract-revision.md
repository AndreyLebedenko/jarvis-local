# Task: Locality contract revision

**Story:** `tasks/story-v1.4.0-mcp-integration.md`
**Status:** Completed. Human reviewed and accepted the two-tier wording
(2026-07-14). Scope was extended beyond the three named documents to also
cover `CLAUDE.md`/`AGENTS.md` (identical files carrying the same
unconditional wording, found during implementation and confirmed in
scope by the human before proceeding).
**Release:** v1.4.0

## Summary

Revise the runtime locality contract explicitly before any code can make an
external call: core and inference stay local unconditionally; external
network access becomes a per-component capability that is off by default,
enabled explicitly by the user, and visible in the data-source axis. This
changes a settled project fact and therefore happens only by this explicit
human decision, recorded in the docs, not as an implementation side effect.

## Current Boundary

- Update in one change:
  - `PROJECT.md`: replace the unconditional "no network beyond the
    configured local Ollama endpoint" guarantee with the two-tier
    contract (unconditional core locality; per-component, user-enabled,
    user-visible external capability). Record the decision date and
    rationale.
  - `VISION.md`: align the "Local-first by default" principle and the
    component model section with the two-tier contract.
  - `tasks/roadmap-v1.2-v1.4.md` cross-cutting rule 3: same alignment.
- Define the wording for the data-source axis semantics: a turn that used
  an external tool is labeled as such; inference locality and tool
  externality are reported independently.
- No code changes in this task.

## Acceptance Criteria

- [x] All three documents state the same two-tier contract with no
      contradicting leftover phrasing (grep for the old guarantee wording).
      Also applied to `CLAUDE.md`/`AGENTS.md` (see Status).
- [x] The contract explicitly states that MCP-off means no external
      capability exists at runtime.
- [x] Human has reviewed and accepted the wording before task 6 enables
      any real external tool.

## Stop Conditions

- Stop if the two-tier wording conflicts with any existing "do not
  re-litigate" fact other than the one being deliberately revised.
