# Mode 3b spike - raw study

Archived evidence for closing `tasks/done/spike-single-pass-tts-block.md`
(2026-09-27). The verified facts are in `PROJECT.md`, section "Mode 3b (single
pass with a trailing `<tts>` block) closed". This directory holds what
produced them.

The harness that generated and scored this data is maintained code, not an
archived one-off: `manual/manual_check_single_pass_tts.py` with
`manual/single_pass_tts_*.py`, at the commit that closes the spike. The frozen
corpus and B contract are `manual/single_pass_tts_corpus.py`; their hash is
`corpus_sha256` in `run_meta.json`.

## Contents

- `records.jsonl.gz`: all 224 model calls, one `CallRecord.to_json()` per
  line (`manual/single_pass_tts_records.py`). The calls are 64 generations
  (2 levels x 16 prompts x 2 seeds): `a_pass1`, `a_prod_pass2`, `b` at both
  levels, plus `a_eq_pass2` at medium. Each line holds the streamed chunk
  timeline `[t, content, thinking]`, `done_reason`, `eval_count`,
  `prompt_eval_count` and the system prompt's SHA-256.
  The `request` field (the full payload) is removed. Its system prompt embeds
  the owner's private `memory/self.md` and `memory/memory.md`, so only the
  hash stays.
- `run_meta.json`: the model (`gemma4:12b`, `kv_cache_type` q8_0, `num_ctx`
  65536), sampling per profile, `NUM_PREDICT` 8192, seeds, the frozen turn
  time, and prompt hashes.
- `review-key.json` and `review-production-answers.toml`: the blind review
  key and the owner's answers for the production sitting, done on seed 19200.
  The equalized sitting was not reviewed; see the closure note for why it was
  not needed.
- `report.md`: the scorer's output, with decision CLOSE.

## Re-deriving the report

```
python -c "import gzip, json; from manual.single_pass_tts_records import CallRecord; from manual.single_pass_tts_grader import grade_generations; from manual.single_pass_tts_review import Sitting, load_key_json, parse_answers, render_report_markdown, score; D = 'docs/experiments/single-pass-tts-block-spike'; recs = [CallRecord.from_json(json.loads(l)) for l in gzip.open(D + '/records.jsonl.gz', 'rt', encoding='utf-8')]; key = load_key_json(open(D + '/review-key.json', encoding='utf-8').read()); ans = parse_answers(open(D + '/review-production-answers.toml', encoding='utf-8').read(), key, Sitting.PRODUCTION); print(render_report_markdown(score(grade_generations(recs), key, ans)))"
```

At the closing commit this prints the contents of `report.md` (plus one
trailing newline from `print`).
