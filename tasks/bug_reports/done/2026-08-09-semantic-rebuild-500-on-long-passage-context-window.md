# Semantic projection rebuild fails whole-session on one oversized passage

**Detected at commit:** `6c4be3b` (`main`), uncommitted working tree on
branch `task-v1.8.0-29-core-release-verification`, during the task v1.8.0-29
manual handoff (owner-run, 2026-08-09), item 2 (real-scale semantic latency
sanity check against the owner's real Journal).

## Symptoms

Starting `python -m jarvis --status-console` against the real local journal
(274 real user/assistant events across many sessions) failed the startup
semantic projection rebuild:

```
semantic projection rebuild failed
Traceback (most recent call last):
  File ".../semantic.py", line 294, in rebuild
    vectors = self._embedder.embed(...)
  File ".../semantic.py", line 105, in _embed_with_client
    response.raise_for_status()
httpx.HTTPStatusError: Server error '500 Internal Server Error' for url
'http://localhost:11434/api/embeddings'
```

`SemanticPassageIndex._mark_unavailable()` caught the exception and marked the
projection `UNAVAILABLE` for the rest of the session (a startup rebuild only
runs once). The app itself did not crash: the subsequent ordinary turn's
automatic retrieval correctly degraded -
`mode=lexical-by-unavailable`, `elapsed=387ms`, `accepted=0` - and the turn
completed and dispatched generation normally. This is the intended
degradation contract (story decision 10/11) working correctly in the wild,
but it also means the manual handoff's item 2 (real per-turn semantic
latency, at the real 1024-dimension model) could not be exercised this
session: the semantic path never came up.

## Suspected cause

`SemanticPassageIndex.rebuild()` (`src/jarvis/journal/semantic.py:284-304`)
embeds every eligible passage's **full, uncapped** text in one batch call:

```python
vectors = self._embedder.embed(
    [self._settings.passage_prefix + passage.text for passage in passages]
)
```

`_passage_from_corpus_event()` (`:566-576`) and `_passage_from_record()`
(`:535-551`) apply no length cap - unlike the annotation generator
(`AnnotationGenerationService`), which explicitly bounds `max_source_chars`
before any model call. `OllamaEmbeddingProvider._embed_with_client()`
(`:96-118`) then posts one request per passage to `/api/embeddings` with no
`options.num_ctx` override, so each request runs at whatever context the
resolved model tag was pulled/loaded with.

A structural scan of the owner's real journal (lengths only, not content)
found a 15,997-character `source="text"` user passage (session
`20260718-114714-5bfe2d`, position 4) - and separately, `ollama ps` during
this same session reported the loaded
`blaifa/multilingual-e5-large-instruct:latest` at `CONTEXT 512` (tokens). A
~16,000-character passage is far beyond what a 512-token context can hold
once tokenized, which is a plausible and sufficient cause for Ollama's
embedding endpoint to fail server-side on that specific request. This is the
leading hypothesis, not a confirmed root cause - the owner did not capture
Ollama's own server-side console output for the failing request, which would
show the actual crash reason.

Because `rebuild()` embeds the whole passage list in one try/except with no
per-passage isolation, **one oversized passage anywhere in the journal takes
down the entire semantic projection for the session**, not just that one
passage - lexical/exact retrieval keeps working (confirmed:
`mode=lexical-by-unavailable`), but semantic/paraphrase retrieval is
unavailable everywhere until a successful rebuild.

## Status update (2026-08-13, branch `fix/semantic-rebuild-passage-resilience`)

Resilience half fixed; root-cause 500 still open. `rebuild()` on both the
event and annotation index now embeds the batch optimistically and, on any
backend failure, falls back to per-passage embedding: the rejected passage is
skipped, survivors are kept, and only a total failure degrades the index to
`UNAVAILABLE`. A partial index reports `ENABLED` but persists a `complete=0`
marker so a normal restart re-runs `rebuild()` and retries the skipped
passages; failed live single-item updates withhold the same marker. Skips are
logged content-free (label, `text_length`, error type name only). Regression
tests: `tests/test_semantic_projection.py`,
`tests/test_annotation_semantic_projection.py`.

Root cause resolved (2026-08-13, same branch). A live-Ollama sweep pinned the
cause exactly: `HTTP 500 {"error":"the input length exceeds the context
length"}` from the legacy `/api/embeddings` endpoint, which has no truncation
option and rejects any prompt over the model's context. For the configured
`multilingual-e5-large-instruct` (512-token context) the ceiling is about
3,000 chars of dense text; on the owner's real journal 17 of 189 passages
(9%) exceeded it. Raising `num_ctx` on `/api/embeddings` was tested and does
not help - the endpoint ignores it for this model.

Fix: `OllamaEmbeddingProvider._embed_with_client` now calls the newer
`/api/embed` endpoint with `truncate: true`, so an over-context passage is
embedded from its leading tokens instead of 500ing. Verified end to end
against live Ollama: a 24,000-char passage that previously 500ed now returns a
1024-dim vector. The resilience fix above stays as the safety net for any
other embedding failure. Model choice was benchmarked (see PROJECT.md, task
v1.8.0-29 item 2): `e5-large` retained (best recall 0.562, fastest query
latency ~120 ms); `bge-m3` rejected as a working alternative - its per-query
p95 latency (~2,000 ms) breaks the 1 s semantic budget and it scored a 1.0
distractor false-positive rate under the shared relative gate.

## Temporary decision

Not fixed here. This is real production behavior surfaced by the task
v1.8.0-29 manual handoff, but a fix (capping passage text length before
embedding, and/or making `rebuild()` resilient to a single passage's
embedding failure instead of aborting the whole index) is a backend/behavior
change outside card 29's boundary ("no backend/feature change"; scale/e2e
verification only). Recorded here per the project's "how to report an issue"
protocol instead of being folded into the current task.

## Future considerations and boundaries

- Confirm the root cause precisely: capture Ollama's own server log for the
  failing `/api/embeddings` request (the client only has "500 Internal
  Server Error" with no response body detail), and/or reproduce narrowly by
  embedding the single suspect passage in isolation.
- If confirmed context-window-related, the fix likely belongs with
  `SemanticPassageIndex`/task v1.8.0-10's owner: either cap embedded passage
  text (mirroring the annotation generator's `max_source_chars` pattern,
  possibly truncating rather than rejecting since embeddings do not need to
  be lossless) and/or request a larger `num_ctx` via `options` on the
  embedding call, with a measured tradeoff against latency/VRAM.
- Independently of the exact cap, `rebuild()` aborting the *entire* index on
  *one* passage failure is a robustness gap worth its own fix: a single
  passage should be skippable (logged, excluded, retried later) without
  taking every other passage's semantic retrievability down with it.
- Until fixed, a real journal containing a very long single turn (attachment
  text can reach 20,000 model-facing characters by design, `README.md`
  Features) can silently and durably disable semantic retrieval for that
  installation after every restart, with only the `UNAVAILABLE` projection
  state and this degradation telemetry as the visible symptom.
