# Spike v2.1.0-11: text-only sanitize pass on INT4

Status: Open (rule frozen before the first run).

## Question

In the decided pipeline (Whisper -> Gemma check -> text-only sanitize pass ->
outbound gate) the sanitize pass sees only text. Spike 1 measured that pass on
`gemma4:12b-it-q8_0` at `num_ctx` 65536 over Gemma-transcribed input. Production
is `gemma4:12b` INT4 at `num_ctx` 8192 over Whisper text, optionally corrected by
the Gemma check. Is the pass good enough in that configuration?

## Boundary

Offline harness under `manual/` (`manual/manual_check_text_sanitize.py`,
`manual/personal_proxy/sanitize_scoring.py`). No production code. The prompts,
schema, parser and span scorer are those of spike 1, unchanged. Controls
(silence/noise) are out of scope: they need a guard before the engine
(story v2.1.0, Revisions). Human-run live part: the `run` command (agent run is
authorised by the owner for spikes, as in spikes 5-10); `score` is offline.

## Method

- Model `gemma4:12b` (INT4), `num_ctx` 8192, production options (temperature
  0.618, top_p 0.9, top_k 50, min_p 0.05, repeat_penalty 1.025),
  `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=Q8_0`, `num_predict` 2048,
  constrained output with `TEXT_SCHEMA` (spike 1's `use_format` was true),
  seeds 19210 and 4243 (spike 1's `SEEDS`).
- Inputs, per utterance of both corpora (v1: 44 utterances, v2: 30 recordings):
  - arm W: the Whisper text (`words/<id>.json`, `text`);
  - arm G: the checked text, i.e. the base sample of spike 8/9 (temperature
    0.618, seed 19210, Whisper text with `[?]` marks plus audio).
- 74 utterances x 2 arms x 2 seeds = 296 generations. Prompt-prefix cache reset
  before each call, one unrecorded warm-up, as in spike 1.

## Measurements

As spike 1, with one change that the new input forces. A span lost by the
engine (not recognisable in the input text) cannot leak, and counting it as "not
leaked" flatters the pass. So:

- **Recognisable spans**: spans of the utterance still recognisable in the input
  text (spike 1's `leaked_spans` applied to the input). Leak rate = recognisable
  spans that stay recognisable in `sanitized_text` / recognisable spans, over
  generations with verdict `send`.
- **Lost spans**: spans not recognisable in the input; listed, never in a rate.
- **Mapping error rate**: over recognisable spans that did not leak, as spike 1
  (the mapping must contain the original).
- **Meaning preservation**: spike 1's `meaning_preservation` (reference text,
  so STT errors cost preservation too; comparable with the baseline). The
  input-based variant (content words of the input) is reported next to it.
- **Validity**: output parses (spike 1's parser, `require_raw_transcript=False`).
- **False refusals** (verdict `refuse` where `send` is expected) and **missed
  refusals** (v1's 8 refuse-expected utterances sent).

Baseline (spike 1, arm t_plus_s, q8/65536, Gemma-transcribed input, 88
generations): validity 1.000, leak 7/80 = 0.087, mapping error 0.260,
preservation 0.633, false refusals 13/88, missed refusals 0. The inputs differ
from the new arms, so the comparison reads the pass plus its input, not the pass
alone; this is stated here, not hidden.

## Decision rule (FROZEN before the first run, 2026-10-19)

Primary arm: **G** (the production input), both corpora pooled, both seeds.
Go (the sanitize pass is kept as designed on INT4/8192) if all hold:

1. Validity at least 97% (baseline 1.000 minus 3 pp).
2. Leak rate of recognisable spans not above 0.107 (baseline 0.087 plus 2 pp).
3. Mapping error rate not above 0.29 (baseline 0.260 plus 3 pp).
4. Meaning preservation not below 0.603 (baseline 0.633 minus 3 pp).
5. False refusals not above 15% of generations of send-expected utterances
   (baseline 13/88 = 14.8%).
6. Missed refusals not above 1.

Close (the story re-plans the pass: a larger context, a different model, or a
different prompt) if validity is below 90% or the leak rate is above 0.15.

Anything else goes to the owner with the numbers. No extra runs without a named
hypothesis they would test.

Reported, never part of the rule: arm W (what skipping the Gemma check costs),
each corpus and each voice separately, leak by span type and class, lost spans,
how the leaks render, median and p90 time per call, the seed-to-seed
agreement of the leak set.

## Stop conditions

- Stop and report if the INT4 model digest differs from the one recorded for
  spikes 6-9 (`gemma4:12b`, 7.6 GB).
- Stop if the recorded inputs (`words/`, `samples/`) are missing or their
  corpus fingerprints differ from `run_meta.json`.
