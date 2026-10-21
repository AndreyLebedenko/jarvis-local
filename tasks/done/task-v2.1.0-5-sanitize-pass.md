# Task v2.1.0-5: sanitize pass (text only)

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 5 (Size: M). Facts: spike
v2.1.0-11 (`tasks/done/spike-v2.1.0-11-text-sanitize.md`, the prompts, schema, parser
and options it froze) and `PROJECT.md` "v2.1.0 speech recognition and confidence
spikes". Follows tasks 1-4 (`src/jarvis/personal_proxy/`: settings, the gate and its
`mapping` check, the guarded speech-to-text stage, the transcript check stage with
its `CheckBackend` seam).

## Summary

The local model turns the checked transcript into a request that can go out: each
sensitive item becomes a typed placeholder (`<PERSON_1>`), a mapping keeps the
originals, and a whole-request sensitive topic becomes a refusal. Output is
structured and validated; anything malformed sends nothing.

## Boundary

New package code only, in `src/jarvis/personal_proxy/`. Reuse, do not rewrite: the
`CheckBackend` seam, `ChatRequest`, `OllamaCheckBackend` (text-only requests have an
empty `audio_base64`; if the seam needs a change to carry a text-only request, make
the smallest change and say so in the report), `GenerationOptions`. No external
client, no restoration, no gate call, no pipeline, no UI, no live Ollama call by the
agent.

## Decisions already taken (owner, 2026-10-21)

- Settings: no new generation profile and no new keys. The pass uses `check_model`,
  `check_num_ctx`, `check_temperature`, `check_top_p`, `check_top_k`, `check_min_p`,
  `check_repeat_penalty` (equal to the spike 11 options), `num_predict` 2048 as a
  constant, no seed in production. `config.example.toml` comments on those keys say
  they serve both stages.
- Topics file: `[personal_proxy].topics_file`. If it equals the code default
  (`personal_proxy_topics.txt`) and the file does not exist, there are no topics. If
  the path was set to anything else and the file is missing, unreadable, or not valid
  UTF-8, loading raises a typed error and nothing is sent. The file is local-only: its
  text goes into the sanitize prompt and nowhere else (logs, results, reprs, errors).

## Required behavior

1. **Prompt and schema.** Promote spike 1/11's `RULES`, `TEXT_FORMAT`, `TEXT_SCHEMA`
   and `TEXT_USER_PREFIX` to `src/` unchanged in substance (model-facing text stays
   English; the sanitized text stays in the language of the request). Request: system
   message (rules with the topics, then the format), user message (prefix plus the
   checked transcript), constrained output with the schema, as in the spike.
2. **Result.** A frozen `SanitizeResult`: verdict (`send` or `refuse`), a bounded
   `reason`, `sanitized_text`, `mapping` (placeholder to original). Its `repr` and
   any exception hide the transcript, the sanitized text, the mapping and the topics.
3. **Strict parser** (from spike 1's `parse_sanitize_output`, no salvage): truncated
   (`done_reason` length), empty, no JSON, extra prose, missing field, wrong type, bad
   verdict. Plus deterministic validation: verdict `send` needs a non-empty
   `sanitized_text`; verdict `refuse` ignores any text and mapping (they are dropped,
   never returned); mapping keys match `<TYPE_N>` with a type from the prompt's list;
   mapping values are non-empty. Any failure is a typed fail-closed result (an enum of
   failure classes, no model text in it): nothing is sent, no retry.
4. **Stage function.** `sanitize(checked_transcript, topics, backend, settings)`: an
   empty transcript is not sent to the model and returns a refusal ("no speech"); a
   backend error or timeout is a fail-closed failure of its own class.
5. **Topics loader** as decided above, plus a refusal-by-topic case documented in the
   result (`refuse` with the reason the model named, bounded in length).
6. Tests with a fake backend (pure logic): payload shape (system/user messages, the
   schema in `response_format`, options from settings, no `images`), the topics text
   present in the prompt and absent from every result/repr/exception, each parse
   failure class, each deterministic validation rule (positive and negative), refuse
   drops text and mapping, empty transcript, backend failure, loader cases (default
   path missing, explicit path missing, unreadable, bad UTF-8, normal, empty file).
   Fixtures may reuse spike 11 recorded outputs if present; do not depend on gitignored
   files.

Out of scope: any call of the gate (task 9 composes), the external client, restoration,
the confirmation exchange, a generation profile, new config keys.

## Human-run handoff

Not required to exist as a new live script if the spike 11 harness already covers the
production prompt; instead add a unit test that fails when the production prompt/schema
text drifts from the frozen spike hash, and say in the report how the spike harness
relates to the production code. If the owner wants a live check of the production
function on the recorded transcripts, prepare it under `manual/`, self-sufficient per
CLAUDE.md Testing protocol 4, and check it with
`tools/check_handoff_self_sufficiency.py`. Preparing it must not run it.

## Acceptance criteria

- [x] The stage returns a validated `SanitizeResult` or a typed fail-closed failure;
      nothing malformed is ever returned as a `send`.
- [x] A topics-file match is a `refuse`; the topics text never leaves the sanitize
      prompt (no log, repr, result, or error).
- [x] No new HTTP client, no new config key, no generation profile; the options equal
      spike 11's.
- [x] The production prompt and schema match the spike's frozen text (a test says so).
- [x] `python -m pytest`, `ruff check`, and `ruff format --check` are green.

## Outcome (2026-10-21)

Accepted by the owner. Developer subagent; an independent reviewer found no path
from malformed model output to a `send`, and these defects, all fixed test first:
untyped `RecursionError` and `ValueError` (int digit limit) from the JSON decoder,
text of only zero-width characters accepted as a request, a BOM before the JSON
read as prose, duplicate JSON keys (last won), a mutable `mapping`, no size cap on
the topics file, an untyped error for a NUL in the path. Suite: 4433 passed, 1
skipped; ruff clean.

Seam change: `ChatRequest` has an optional `system` message; an empty
`audio_base64` means a text-only request and the Ollama adapter then sends no
`images`. A truncated reply never reaches the parser in production: the adapter
raises on `done_reason` length, so it surfaces as `backend_failed`.

Decisions and limits:
- The stage does not check that a `send` replaced anything (no mapping value in the
  sanitized text, every key present in it). The outbound gate (task 2, mapping
  check) owns that; duplicating it here would only add false failures. A `send` with
  no replacements is accepted by this stage and stopped by the gate.
- The topics file is capped at 8000 characters (Ollama silently truncates at
  `num_ctx` 8192). The default path is relative to the working directory: started
  from another folder, an existing default file is not found and there are no topics,
  without a signal. Anchoring it to the config directory is a later change.
- The opt-in debug transcript would record the sanitize prompt with the topics text,
  as it records the check-stage prompts; known exception, in `PROJECT.md`.
- No live handoff for the production function: spike 11's harness runs the spike
  copies of the prompts, and a test keeps the production text equal to them. A live
  check on recorded transcripts needs a new `manual/` script.
- A refusal's `reason` is model text (bounded to 200 characters, hidden from `repr`);
  it can echo a topic line.
