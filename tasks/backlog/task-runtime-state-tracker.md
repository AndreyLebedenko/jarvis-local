# Task: Single owner for Status Console runtime state

**Status:** Backlog.
**Origin:** Entropy-review of v1.2.4/v1.2.5 code (2026-07-09).

## Summary

RuntimeState transitions pushed to the Status Console are spread across
`main.py`'s `run()`, `wire()` closures, and `wire_status_console()`
handlers, with busy-guard logic duplicated from `Orchestrator`
(`not app.orchestrator.is_busy` in the `wire()` wrappers mirrors the
orchestrator's internal check). The already-fixed "orb stuck on SPEAKING"
bug was a direct consequence: no single place owns the state machine, so
every new transition must be hand-wired into the right closure.

The 2026-07-09 review added deduplication in `LiveStatusConsole`
(`_last_runtime_push`), which fixes the per-token push cost but not the
ownership problem.

## Proposed direction

Introduce a `RuntimeStateTracker` that subscribes to lifecycle bus events
(warm-up, utterance/clipboard accepted, first response token, response
complete, error) and publishes a `RuntimeStateChanged` event. UI wiring
renders `RuntimeStateChanged` only; no push logic in `wire()` closures.

## Acceptance criteria

- [ ] One module owns every RuntimeState transition.
- [ ] `wire()`/`wire_status_console()` contain no busy-guard duplication.
- [ ] Existing runtime-state regression tests still pass (stuck-orb test,
      dedup test).
- [ ] `python -m pytest` passes.
