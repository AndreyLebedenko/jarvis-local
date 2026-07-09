# Task: Manual language-routing handoff

**Story:** `tasks/story-v1.2.8-multilingual-speech-markup.md`
**Status:** Completed.
**Release:** v1.2.8
**Depends on:** `tasks/done/story-v1.2.8-task-3-system-prompt-language-routing-contract.md`

## Summary

Prepare a human-run manual check for the v1.2.8 language-routing behavior and
record verified behavior in `PROJECT.md`.

## Current Boundary

- Manual handoff and documentation only.
- The agent writes exact prompts and expected observations.
- The human runs live Ollama/Gemma4 checks.
- Do not tune generation defaults here; use configured values and record them.

## Acceptance Criteria

- [ ] Handoff includes the exact system prompt or points to the prompt under
      test.
- [ ] Handoff includes fixed prompts for:
      - Russian-only answer;
      - English-only answer;
      - mixed Russian/English with code identifiers;
      - quotes and slash-separated English examples;
      - punctuation-heavy short segments;
      - malformed-pressure case, such as asking for a long nuanced answer.
- [ ] Handoff asks the human to record model, Ollama version, `temperature`,
      `top_p`, `top_k`, `min_p`, `repeat_penalty`, and other configured
      generation options.
- [ ] Handoff records pass/fail observations:
      - model emits plain speakable text, not language tags;
      - no Markdown fences unless explicitly requested;
      - charset segmentation routes Cyrillic text to `ru`;
      - charset segmentation routes Latin identifiers/terms to `en`;
      - punctuation and numbers attach to usable neighboring segments.
- [ ] Human-confirmed results are recorded in `PROJECT.md`.
- [ ] Any unresolved behavior is documented as an open question or bug report,
      not silently worked around.

## Verification

- Read `PROJECT.md` with `Get-Content -Raw -Encoding UTF8 PROJECT.md`.
- Run `python -m pytest` unless the human agrees this is a docs-only handoff.

## Prepared Handoff

Run from the repository root:

```powershell
python manual_check_speech_markup_contract.py
```

By default, the script uses the exact runtime `main.SYSTEM_PROMPT`. For prompt
experiments, edit `SYSTEM_PROMPT_UNDER_TEST` near the top of
`manual_check_speech_markup_contract.py`; do not change `main.py` until a prompt
variant passes the manual check. The script sends requests to the configured
local Ollama endpoint with `think: false`, then prints the raw response and the
`language_segments.segment_by_charset()` result that the TTS path relies on.
It prints:

- Ollama endpoint and version;
- configured model;
- configured generation options: `num_ctx`, `flash_attention`,
  `kv_cache_type`, `temperature`, `top_p`, `top_k`, `min_p`,
  `repeat_penalty`, `repeat_last_n`, `seed`, `num_predict`, `stop`,
  and `draft_num_predict`;
- the runtime system prompt;
- six fixed prompt cases:
  - `russian_only`;
  - `english_only`;
  - `mixed_identifiers`;
  - `quotes_and_slashes`;
  - `punctuation_heavy`;
  - `long_nuanced_pressure`;
- raw model responses;
- plain-text observations for each response:
  - `no_language_tags`;
  - `no_markdown_fences`;
  - `has_speakable_text`;
- charset language segments for each response.

Manual pass criteria:

- model emits plain speakable text, not `<speak>`/`<lang>` tags;
- Markdown fences are absent unless explicitly requested;
- Cyrillic prose appears in `ru` segments;
- Latin identifiers, API names, and English phrases appear in `en` segments;
- punctuation-heavy examples create usable neighboring segments, not standalone
  punctuation noise.

After the human run, record the date, model, Ollama version, generation
options, and pass/fail observations in `PROJECT.md`. If one case fails in a way
that requires changing the charset segmentation contract, stop and file a
focused bug report instead of working around it silently.

## Human Run Result

Run reported by the human on 2026-07-09:

- Ollama endpoint: `http://localhost:11434`
- Ollama version: `0.31.2`
- model: `gemma4:12b-it-qat`
- `think: false`
- `num_ctx: 65536`
- `flash_attention: True`
- `kv_cache_type: q8_0`
- all other generation knobs unset (`None`)

Old XML-markup result: failed the markup-stability contract. `russian_only` passed, but
ordinary English-only and mixed-language prompts produced nested `<lang>` spans,
and punctuation/mixed examples sometimes left speakable text outside a complete
`<lang>` span. The exact issue is recorded in
`tasks/bug_reports/gemma4-speech-markup-contract-instability.md`.

Decision: pivot away from LLM-authored language tags. Runtime now uses plain
model text plus deterministic `ru`/`en` charset segmentation.

Second run reported by the human on 2026-07-09, after the charset-segmentation
pivot:

- Ollama endpoint: `http://localhost:11434`
- Ollama version: `0.31.2`
- model: `gemma4:12b-it-qat`
- `think: false`
- `num_ctx: 65536`
- `flash_attention: True`
- `kv_cache_type: q8_0`
- all other generation knobs unset (`None`)

Result: passed the new plain-text + charset-segmentation contract.
`russian_only`, `english_only`, `mixed_identifiers`, `quotes_and_slashes`,
`punctuation_heavy`, and `long_nuanced_pressure` all produced speakable plain
text with no language tags and no Markdown fences. Charset segmentation routed
Cyrillic prose to `ru` and Latin terms/identifiers to `en`; the mixed
`CRUD-операций` form split into `en: CRUD-` and `ru: операций`, which is
acceptable for the current two-language routing contract.

## Stop Conditions

- Stop if live results show Gemma4 emits unwanted language tags or Markdown
  fences under normal Jarvis prompts.
- Stop if generation-parameter choices have non-obvious trade-offs for
  factual quality, latency, or language-routing stability.
- Stop if observed failures require changing the charset segmentation contract.
