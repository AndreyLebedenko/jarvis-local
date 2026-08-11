# Gemma4 speech-markup contract instability

Detected at commit: `ec4afd0`.

## Symptoms

Human-run `python manual_check_speech_markup_contract.py` on 2026-07-09 showed
that `gemma4:12b-it-qat` does not keep the v1.2.8 speech-markup contract stable
under normal Jarvis prompts.

Run context:

- Ollama endpoint: `http://localhost:11434`
- Ollama version: `0.31.2`
- model: `gemma4:12b-it-qat`
- `think: false`
- `num_ctx: 65536`
- `flash_attention: True`
- `kv_cache_type: q8_0`
- all other configured generation knobs unset (`None`)

Observed failures:

- `russian_only` passed all structural checks.
- `english_only` nested `<lang xml:lang="en">WebSocket</lang>` inside an
  outer English `<lang>` span.
- `mixed_identifiers` nested English identifier spans inside an outer Russian
  `<lang>` span.
- `quotes_and_slashes` kept non-nested tags but failed to close the final
  Russian `<lang>` before `</speak>`, leaving speakable text outside a complete
  `<lang>` span.
- `punctuation_heavy` kept non-nested tags but put `HTTP/2` in a Russian span
  and left later Russian prose outside a complete final `<lang>` span.
- `long_nuanced_pressure` nested multiple English term spans inside an outer
  Russian `<lang>` span.

## Suspected current cause

The system prompt asks for non-nested language spans, but the model naturally
uses inline nested spans when an English identifier appears inside Russian prose.
That shape is intuitive XML/HTML behavior, but it violates Jarvis's v1 parser
and streaming contract: `</lang>` is a flush boundary and `TtsOutput` expects
language spans to be adjacent, not nested.

The missing final `</lang>` cases suggest the model also treats the markup as a
loose formatting hint under punctuation-heavy mixed text rather than as a
strict output grammar.

## Temporary decision

Stop task-4 per its stop condition: live results show Gemma4 cannot keep the
markup contract stable under normal Jarvis prompts. Do not silently work around
this inside task-4.

This was chosen over immediate prompt tweaking because generation-parameter or
prompt-shape changes have non-obvious trade-offs for latency, factual behavior,
and markup stability. It was also chosen over changing the parser to support
nested tags because that changes the task-1 parser contract and the task-2
streaming flush semantics.

## Future considerations

- Try a stricter flat-output prompt that explicitly says to close the current
  Russian span before each English term and reopen Russian afterward, with a
  concrete flat example.
- Consider post-processing nested same-language and inline mixed-language spans
  into flat adjacent spans, but only as a deliberate parser-contract change
with tests for streaming flush behavior.

Update: the chosen follow-up direction is to stop asking the model for language
tags at all. Runtime language routing now uses deterministic charset
segmentation for the supported `ru`/`en` pair: Cyrillic routes to `ru`, Latin
routes to `en`, and neutral punctuation/digits attach to neighboring segments.
The manual script was repurposed to check plain model output and the derived
charset segments.

Follow-up manual run on 2026-07-09 passed the new plain-text +
charset-segmentation contract with the same Ollama/model/options context. This
does not make the XML-like speech-markup contract viable; it records that the
runtime no longer depends on that failed contract.
- Consider an output-constrained wrapper or retry/repair pass if local latency
  remains acceptable.
- Re-run the same manual script after any prompt, parser, model, or generation
  option change and record the exact model/Ollama/options used.
