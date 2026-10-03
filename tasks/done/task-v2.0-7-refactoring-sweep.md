# Task v2.0-7: Refactoring and optimization sweep

**Status:** Completed. (2026-10-03)
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Depends on:** tasks v2.0-1 through v2.0-6 completed and green.
**Executor:** the story's executor profile. Strictly behavior-preserving: no
new capability, no contract change, no acceptance-criterion regression. If
a change alters observable behavior or a test expectation (other than
removing a duplicate), you have left this card - stop.

## Summary

Consolidate this story's code and tests so the tails of tasks 1-6 do not
accumulate, mirroring `tasks/done/task-v1.9.1-5-refactoring-and-optimization-sweep.md`.

## What to do

1. **Collect the cleanup candidates** that tasks 1-6 listed in their
   completion notes, and resolve each one or record why it stays.
2. **One vocabulary per concept.** The `mcp_canvas` source string, the
   speech origin and status values, and the run mode each have exactly one
   definition that every producer and consumer imports. Grep for repeated
   literals across `src/jarvis/` and the UI JS.
3. **Provenance expressed once.** No consumer re-derives "is this external"
   from `source` when a descriptor is available. The source-to-kind mapping
   in `provenance.py` is the only place that reads it for that purpose.
4. **Tests.** Shared fixtures for the repeated setup (a recorded
   `mcp_canvas` event, a fake voice-guide service, a running test server),
   placed in `tests/conftest.py` or a local helper module following the
   repo's existing practice. Remove assertions that duplicate what a lower-
   level unit test already pins.
5. **Dependencies.** Confirm every package the story's code imports directly
   is in `requirements.txt`, and nothing added there is unused.

## Explicitly out of scope

- Code outside this story's changes, even if it is tempting.
- Performance work without a measured problem.

## Acceptance criteria

- [x] Every cleanup candidate from tasks 1-6 is resolved or explicitly
      carried forward with a reason.
- [x] No concept introduced by this story is defined twice.
- [x] The suite stays green with no acceptance-criterion regression;
      `python -m pytest`, `ruff check`, `ruff format --check` green.

## Completion notes (2026-10-03)

Executed through the Quoroom chat under
`tasks/done/plan-v2.0-7-chat-execution.md` (inventory first, then code and
tests), with an independent review.

- Resolved: the `# type: ignore[attr-defined]` markers on the Win32 ctypes
  calls (no type checker runs in this repo); the `spoken_derivative*`
  metadata keys, now constants in `journal/corpus.py` used by every Python
  writer and reader; `VoiceGuideQueueChanged.in_flight`, dropped for
  `phase`; the JS `mcp_canvas` and run-mode literals, now
  `MCP_CANVAS_SOURCE` and `RUN_MODE` in `status_console_ui/contract.js`,
  cross-checked against Python by a test; `canvas_speech` compared against
  `SpeechOrigin.VERBATIM`; `pydantic` as a declared dependency.
- Resolved in tests: one shared module `tests/_mcp_mode_support.py` for the
  recorded external answer, the fake speak queue, and the running server;
  two duplicated payload-shape assertions removed, pinned by the payload
  builder tests in `tests/test_status_console.py`.
- Carried forward, with reasons:
  - `SPOKEN_DERIVATIVE_METADATA_KEY` stays in `corpus.py` (v1.9.1 code;
    moving it buys little).
  - The token sentinel test repeats the two subscription lines of
    `_wire_voice_guide_blocks()` (the transport does not own that wiring;
    the wiring has its own test).
  - Guide sentence streaming (a capability; task 3 follow-up).
  - `search_history` vs `read_history` source-kind shape, and
    `skipped_ineligible_count` telemetry (a tool-result contract change and
    a new capability).
  - `MCP_MODE_CANVAS_SPEECH_VALUES` in `core/config.py` repeats two
    `SpeechOrigin` values: `core.config` must stay stdlib-only
    (`conftest.assert_stdlib_only_imports`). A test pins the two to the
    same set, so they cannot drift.
  - Client-side validation of speech origin, status, and phase (would throw
    on an unknown value: a behavior change).
  - Same words in `TurnOutcome` and `ModelRequestPassKind` (different
    concepts).
  - Source-based queries in `retrieval.py` and `fork.py` (purpose-built
    queries, not a provenance display decision); the client deciding
    "external" from `source` (no descriptor in the payload, by task 6's
    decision).
  - Same-named test fakes across unrelated test files (each shaped for its
    own assertions).
  - `anyio` imported directly in `tools/mcp_client.py` (v1.4 code, outside
    this story).
