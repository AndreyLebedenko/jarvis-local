# Semantic hot-path timeout still leaves the in-process cosine scan unbounded

**Detected at commit:** `f63e961` (`codex/v1.8.0-task17-automatic-retrieval-wiring`).
**Status:** Rejected (will not fix), 2026-08-11. Measured and reconfirmed by
task v1.8.0-29 (2026-08-09).
Owner decision: accept as a known, documented limit for the personal-journal
scale this project targets; not fixed by card 29 (out of its no-backend-
change boundary). See the task v1.8.0-29 entry in `PROJECT.md` for the
measured numbers (500/2,000/8,000/20,000-event sweep, ~10.3-10.9
microseconds/row, near-linear) and `tests/test_history_core_scale_recovery_e2e.py::test_semantic_scan_latency_stays_within_a_generous_regression_guard`
for the regression guard that now watches for a *worse* (not merely linear)
regression.

## Symptoms

`HistorySemanticSettings.timeout_seconds` is now applied to the query embedder
on the automatic-retrieval hot path, so a slow or stalled embedding request can
fall back to lexical-only retrieval without waiting for the model.

The deadline does not cover the full semantic path, though. After the query
embedding returns, `SemanticPassageIndex.query()` still performs an
in-process brute-force cosine scan across the candidate rows in Python. That
scan has no independent deadline or cancellation point, so a larger semantic
projection can still spend unbounded CPU time after the HTTP timeout budget
has already been honored.

On the current small corpus this is not measurable, but it weakens the
wording "including query embedding" if a reader assumes the whole semantic
path is covered by the same budget.

## Suspected cause

The timeout is currently enforced at the embedding HTTP call in
`src/jarvis/journal/semantic.py`, while the cosine ranking loop runs
afterward in the same thread:

- `OllamaEmbeddingProvider.embed()` uses the semantic timeout for the query
  request.
- `SemanticPassageIndex.query()` then reads all filtered rows and ranks them
  synchronously in Python with `_cosine(...)`.

There is no separate wall-clock guard around the scan itself.

## Temporary decision

Leave this unfixed in task v1.8.0-17 and document it as a known limitation.
The current task boundary is automatic retrieval wiring and telemetry, and the
observed corpus size keeps the scan cheap enough that the missing deadline is
not a release blocker.

## Future considerations and boundaries

- Measured by the scale/recovery/e2e work in task v1.8.0-29 (this story's
  release phasing later split the original single card 27 into 29/30/27;
  the measurement landed in 29, the v1.8.0 core release-verification card).
  The actual fix - a bounded candidate prefilter, an ANN index, or a real
  whole-path deadline around the scan itself - remains open and unscheduled.
- If the scan ever becomes visible in turn latency, the fix should be a real
  whole-path budget or a smaller bounded scan, not an artificial sleep-based
  guard.
- Until then, the current task 17 acceptance should be read as "query
  embedding is budgeted and the turn degrades without waiting on the HTTP
  path", not as a claim that the entire cosine scan is separately timed.
