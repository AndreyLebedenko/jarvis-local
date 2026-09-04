# Task: Reproducible audio request-shape research harness

**Status:** Awaiting human review.

## Summary

Replace the one-clip, uncontrolled measurements in
`2026-09-01-request-shape-suppresses-audio-attention.md` with a reproducible
human-run experiment. The experiment compares transcription accuracy for the
same audio under isolated `/api/chat` request-shape changes and records enough
provenance to identify the model and payload that actually ran.

## Current boundary

This task adds a manual live-Ollama harness, pure automated tests for its
planning/scoring/payload logic, ignored local result storage, and corrected
project documentation after the human-run evidence exists. It does not change
production dialog behavior or choose a fix.

The requested model set is fixed to:

- `gemma4:12b-it-q4_K_M`
- `gemma4:12b-it-q8_0`
- `gemma4-12b-jarvis-free-mm:latest`

The fixture set uses independent existing WAV files. The two WAV files removed
from session `20260805-231334-6d4bee` are represented by existing PCM WAVs
chosen from the same journal by duration and byte size. The archive retains
only their combined size (`704088` bytes), so the replacement mapping is an
explicit approximation, not a claim that either substitute is the original.
The chosen 9.5 s and 12.5 s replacements sum to the archived byte count
exactly. Only fixtures with a human-supported reference transcript contribute
to WER/CER; the 12.5 s replacement has no such reference and is retained as an
unscored diagnostic case.

## Acceptance criteria

1. The default run targets exactly the three requested model names and fails
   before trials if any name is unavailable from the local Ollama endpoint.
2. Every scored fixture has a stated reference-text provenance. Missing or
   size-mismatched files fail explicitly. Unverified text is never scored.
3. Conditions hold the transcription task and audio bytes constant while
   independently varying an explicit system message and a no-op tool; a
   no-media negative control is included.
4. Trials are balanced and reproducibly shuffled within each model so repeated
   model loading is not a timing confound. Cross-model latency is not compared.
5. Raw JSONL output records the git commit, Ollama version, model tag metadata,
   `/api/show` system/template/parameters, explicitly requested GPU-layer
   count, effective options, fixture hashes,
   sanitized payloads, raw responses, WER/CER, and aggregate summaries.
6. Automated tests cover normalization and edit distance, payload shapes,
   fixture provenance, deterministic trial planning, media sanitization, and
   aggregation by independent fixture rather than by repetition count.
7. The automated suite and Ruff checks pass. The live endpoint remains a
   human-run handoff under the repository testing protocol.

## Human-run results

The owner completed all 126 cells on 2026-09-02. Legacy local artifact:
`manual_check_audio_request_shape_out/results-20260902T223154Z.jsonl`, SHA-256
`523543c2de7087d7f185917bc7e10391f4537f37f6f57040e09ddcd5b612b485`.
The run used Ollama 0.33.2 and commit
`de45ac8d3d93a489e29eb1c997f8b3f70a2bf7f2` with the task changes uncommitted.

That run predates the explicit `num_gpu` request option. Its custom model
declared `num_gpu 99` in its Modelfile, but the harness did not set that option
for all three models. It is therefore not controlled for cross-model GPU-layer
placement and must be rerun with the current harness before cross-model
findings are treated as final.

The owner completed the controlled rerun on 2026-09-03. Primary local artifact:
`manual_check_audio_request_shape_out/results-20260903T193753Z.jsonl`, SHA-256
`2c5e84ce4158b661dcce72390d06e8e5b89cbe797972a4c7ccc95453a02ef490`.
It used Ollama 0.33.3 and the same dirty commit, fixture hashes, and model
digests. Its schema-v2 metadata records `requested_num_gpu_layers=99`, and all
126 sanitized trial payloads include `options.num_gpu=99`.

The controlled evidence rejects the old universal-suppressor interpretation.
Using an operational <=0.10 WER boundary, the short 1.1/1.3 s fixtures were
usable in 6/36 audio-bearing cells, while the scored 4.8/6.8/9.5 s fixtures
were usable in 50/54. The unscored 12.5 s fixture yielded clearly
audio-derived content in all 18/18 audio-bearing cells. Tool and system changes
had interacting, model/clip-dependent effects rather than independently
suppressing audio. The bare transcription condition was usable on 5/5 scored
clips for Q4_K_M but only 3/5 for Q8_0 and the custom Q8_0 model, so it does
not establish a generally reliable first pass for the proposed two-pass design.

The legacy and controlled artifacts differ in 27/126 raw response strings, but
they also use different Ollama versions (0.33.2 versus 0.33.3). With one trial
per cell, that difference cannot be attributed to GPU layers or interpreted as
an estimate of repeat variance.
