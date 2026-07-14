# Task: Model presentation layer

**Story:** `tasks/story-v1.4.0-mcp-integration.md`
**Status:** Planned. Prerequisite tasks 1 and 3 are completed.
**Release:** v1.4.0

## Summary

Wire the tool registry into the dialog path: present available tools to
the model using the strategy the spike selected, recognize tool requests in
responses, run the bounded tool round-trip loop through the task-3
interception point, and return the final answer to the normal response
path.

## Current Boundary

- Presentation strategy is behind an interface with two implementations
  (native `tools` field / prompt-based declaration); the spike-chosen
  default is set in config, the other remains selectable for future
  models. Implemented inside the dialog layer next to
  `src/jarvis/dialog/backend.py`; the backend adapter stays
  transport-only: `backend.py` may carry a prepared `tools` payload, but
  it never decides which tools exist, which are offered, or how a tool
  request is interpreted - those decisions live in this layer and the
  task-3 registry.
- When MCP is disabled or the registry is empty, the dialog path is
  byte-identical to today: no `tools` field, no prompt additions
  (asserted in tests).
- Tool round-trip loop:
  - a hard limit on tool calls per turn (config, small default);
  - each iteration goes through the interception point;
  - tool results enter the current turn context only;
  - on limit hit or tool failure the model gets an honest error/context
    and must produce a text answer - the turn always terminates.
- Streaming interplay: a tool-call response must not leak into TTS as
  spoken text; the existing sentence-buffering path only receives final
  answer tokens.
- Pure tests: declaration building per strategy, request-parsing (native
  and prompt-based), loop termination on limit, disabled-path identity.

## Acceptance Criteria

- [ ] Disabled path produces byte-identical requests to pre-v1.4.0
      behavior.
- [ ] Loop always terminates within the configured call budget.
- [ ] Tool requests and malformed tool outputs are handled without an
      unterminated turn (regression risk: the v1.2.3 stream-completion
      class of bugs).
- [ ] No tool-call artifacts reach TTS or the visible response text.
- [ ] `python -m pytest` passes with a fake backend and fake registry.

## Stop Conditions

- Stop if the turn-termination guarantee cannot be kept under any
  malformed model output - this is a design problem, not a retry problem.
- Stop if streaming and tool round-trips conflict in the orchestrator in a
  way that requires reworking turn lifecycle - that is a story-level
  decision.
