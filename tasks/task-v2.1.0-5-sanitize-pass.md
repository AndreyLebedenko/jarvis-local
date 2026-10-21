# Task v2.1.0-5: sanitize pass (text only)

Status: Open.

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

- [ ] The stage returns a validated `SanitizeResult` or a typed fail-closed failure;
      nothing malformed is ever returned as a `send`.
- [ ] A topics-file match is a `refuse`; the topics text never leaves the sanitize
      prompt (no log, repr, result, or error).
- [ ] No new HTTP client, no new config key, no generation profile; the options equal
      spike 11's.
- [ ] The production prompt and schema match the spike's frozen text (a test says so).
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green.
