# Task v2.0-7: Refactoring and optimization sweep

**Status:** Not started.
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

- [ ] Every cleanup candidate from tasks 1-6 is resolved or explicitly
      carried forward with a reason.
- [ ] No concept introduced by this story is defined twice.
- [ ] The suite stays green with no acceptance-criterion regression;
      `python -m pytest`, `ruff check`, `ruff format --check` green.
