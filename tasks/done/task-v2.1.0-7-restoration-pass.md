# Task v2.1.0-7: restoration pass

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 7 (Size: M) and the design decision
"Restoration pass". Facts: block R of spike v2.1.0-1
(`tasks/done/spike-v2.1.0-1-combined-transcribe-sanitize.md`, "Restoration block R";
the harness is `manual/personal_proxy/restoration.py` and
`manual/manual_check_personal_proxy_restoration.py`). Follows task 5 (the sanitize
`mapping`, placeholders `<TYPE_N>`), task 6 (the streamed answer as text deltas) and
the `CheckBackend` seam of task 4.

## Summary

The external answer streams back with placeholders (`<PERSON_1>`). This stage puts the
original values back, locally, one sentence at a time: sentences without a placeholder
pass straight through, sentences with one go to the local model to be restored in the
right grammatical case, a deterministic check validates the result, and a plain
substitution of the original is the fallback. The restored text never leaves the machine.

## Boundary

New code in `src/jarvis/personal_proxy/`. Reuse the `CheckBackend` seam, `ChatRequest`,
`OllamaCheckBackend` and the sentence buffer (`SentenceBuffer`, `audio/tts.py`; if
importing it drags in a hardware dependency that breaks tests or CI, say so and propose
the smallest alternative, do not copy-paste it silently). No external client call, no
gate, no pipeline, no journal, no UI or speech, no live Ollama call by the agent in the
automated tests.

## Owner decision (2026-10-21)

Build the stage with the model branch as the story says; block R was run on q8/65536
but never scored (the blind review sheet is empty). The rule of block R is measured on
the production configuration (INT4 `gemma4:12b`, `num_ctx` 8192) with the stage's own
function as part of this task's handoff; if the rule fails, the model branch is removed
before task 9 and only the substitution stays.

## Required behavior

1. **Stage function.** An async iterator transform: input an async iterator of text
   deltas (the task 6 output) and the sanitize `mapping`; output an async iterator of
   `RestoredSentence` in the original order. A `RestoredSentence` is frozen, its text
   hidden from `repr`/`str`, and carries a `method` enum: `PASSTHROUGH` (no
   placeholder), `MODEL` (restored by the model, validated), `SUBSTITUTED` (fallback),
   plus `unresolved_placeholders: bool` (a placeholder of the sentence is not in the
   mapping).
2. **Buffering.** Deltas are buffered to sentence boundaries, so a placeholder split
   across chunks (`<PER`, `SON_1>`) is never examined half-formed, and the remainder at
   the end of the stream is flushed as the last sentence. If the input iterator raises
   (a task 6 error), the half-built sentence is discarded, already emitted sentences
   stay, and the error propagates unchanged (the consumer treats the answer as
   incomplete).
3. **Placeholders** are found with the same pattern the gate and the sanitize parser use
   (`<TYPE_N>`, the type list of the sanitize prompt). A sentence with none is passed
   through with no model call and no change.
4. **Model request.** Per sentence with at least one known placeholder: the rules of
   block R (`RESTORE_RULES`: restore every placeholder in the required Russian case,
   change nothing else, output only the sentence), the sentence, and only the mapping
   entries whose placeholder occurs in it. System plus user message, text only (no
   `images`), no `format`, reasoning off, the `check_*` options of `[personal_proxy]`
   (model, `num_ctx`, sampling), `num_predict` a constant sized for one sentence. Sentences
   are restored one at a time, in order. No new settings.
5. **Deterministic validation** (promote block R's `validation_passes` and
   `outside_text_unchanged`, using the package's own text helpers): no placeholder text
   left; every original value present (stem match for words, exact tokens for digits);
   every word outside the restored values unchanged from the sentence. All three must
   hold for `MODEL`.
6. **Fallback.** Any validation failure, backend error, timeout, empty or non-string
   reply: plain substitution of the base-form originals into the sentence
   (`SUBSTITUTED`). A sentence is never dropped and never blocks the stream, never
   retried. Placeholders not in the mapping stay in the text and set
   `unresolved_placeholders`.
7. Nothing derived from the answer, the mapping, or the restored text is logged or put in
   an exception, a `repr`, or a failure value.
8. Tests with a fake backend (pure logic): pass-through with no model call; a placeholder
   split across deltas; several sentences and order; model success; each validation rule
   failing (placeholder left, original missing, outside word changed) falling back to
   substitution; backend error; empty reply; unknown placeholder; two placeholders in one
   sentence (both entries sent, only those); the mapping entries of other sentences not in
   the request; abbreviation and "1." style boundaries do not split a placeholder
   sentence; the input iterator raising mid-sentence; empty stream; text hidden in repr.

Out of scope: speech or chat presentation, the journal, the confirmation exchange,
retries, choosing among model variants.

## Human-run handoff (the agent runs it on the owner's request)

A script under `manual/` that runs the stage's own function over the 30 items of block R
(`manual/personal_proxy/restoration.py`, `ITEMS`) on the production configuration
(`gemma4:12b` INT4, `num_ctx` 8192, the `[personal_proxy]` `check_*` options,
`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=Q8_0` as the spikes), twice per item;
it prints per item the sentence, the stage output, `method`, and the timing, scores
automatically the validation pass rate and the alteration rate (both over the model
branch: the share of items where `method` is `MODEL`, and for the rest why it fell
back), and writes the same blind review sheet as the spike (restored vs substitution,
x/y order randomized with the spike's seed) for the owner. It states the card's rule
(validation at least 90%, alteration at most 5%, case correctness better than the
fallback on at least 80% of items where the fallback is wrong) and which parts are
measured automatically and which need the sheet. Self-sufficient per CLAUDE.md Testing
protocol 4; check it with `tools/check_handoff_self_sufficiency.py`. Preparing it must not
run it.

## Acceptance criteria

- [x] Sentences without a placeholder pass through with no model call; a placeholder
      split across chunks is handled.
- [x] Every restored sentence passes the three deterministic checks or is the plain
      substitution; nothing is dropped, blocked, or retried.
- [x] No text from the answer, mapping, or restored sentences in logs, reprs, or errors;
      the input error propagates unchanged with the partial sentence discarded.
- [x] No new setting, no new client; the options are the `check_*` ones.
- [x] The block R handoff exists, is self-sufficient, and the automatic part of its rule
      is measured on the production configuration (the blind case review is the owner's).
- [x] `python -m pytest`, `ruff check`, and `ruff format --check` are green.

## Outcome (2026-10-22)

Accepted by the owner. Developer subagent; two independent review rounds.

Round 1 found the first validator too weak (it dropped digits and value words from the
outside-text comparison and checked phone and e-mail tokens as an unordered bag), which
let a model alter the answer: changed digits, duplicated or moved values, swapped
values, reordered phones, markdown, quotes. The validator became template alignment:
the sentence is cut at its known placeholders, the reply must equal the remaining text
exactly, and each slot must hold a form of that placeholder's original. Also from round
1: the reader is decoupled from restoration (a producer task and an in-order queue), the
backend call has a 15 s limit that falls back to substitution, the sentence buffer is
bounded (a newline or 4000 pending characters ends a sentence), and the unresolved flag
uses the gate's broad placeholder pattern. Round 2 found: a stem match accepting other
words (`Anna` -> `Annotatsiya`, truncated e-mails), a hang when the input raised
`CancelledError`, a placeholder cut at the cap inside a long unspaced token, a
behaviour change in the shared TTS `SentenceBuffer`, and twelve surviving mutants. All
fixed test first. Suite: 4740 passed, 1 skipped; ruff clean.

Change outside the card: `src/jarvis/audio/tts.py` `SentenceBuffer` was rescanning its
whole buffer on every `feed` (180000 characters of abbreviations took about 110 s).
`feed` now resumes from `_scanned_to` and `_word_before` scans one word backwards. The
behaviour is unchanged, including the old newline quirk, proved by regression tests and
a differential run against the old class (150000 random chunkings, no difference).

Block R measured on the production configuration (2026-10-22, `gemma4:12b` Q4_K_M,
`num_ctx` 8192, flash attention and q8_0 KV cache from `[backend]`, 30 items x 2 seeds,
the stage's own function; handoff `manual/restoration-stage-handoff.md`, run by the
agent on the owner's request): validation pass rate 56/60 = 0.933 (rule: at least 0.90);
alteration rate 0.000 (rule: at most 0.05); case correctness 17 of 18 items where the
plain substitution was not ok are restored ok and validated by the model = 0.944 (rule:
at least 0.80). Decision: KEEP the model branch. Median 0.88 s per sentence, maximum
6.8 s. The four fallbacks are the two English names (`Michael Brown`, `Sophie Laurent`)
in both seeds: the model transliterated them into Cyrillic, the stage requires Latin
words verbatim, the substitution keeps them intact.

Owner decisions on the review scale (2026-10-22): the blind sheet uses three levels:
`bad` the case is critically wrong, `ok` fully right, empty or `mid` the meaning comes
through but worse than ok. A substitution counts as wrong when it is not `ok`; the model
beats it when its output is `ok` and the stage validated it. This replaces the spike's
two-level ok/bad for this run. Item r26 (a copy of `<PERSON_1>` and `<PERSON_2>`) is
ambiguous (a copy of them, genitive, or a copy to them, dative; the spike named it
dative); it was marked bad for the nominative and mid for the genitive.

Documented limits:
- A different name that shares the stem and fits the length cap can pass (Oleg ->
  Olesya); a name whose declension changes its first letters (Lev -> Lva, Yan -> Yanu)
  always falls back to substitution; so do Latin names written in Cyrillic and any
  reshaped phone, card or e-mail.
- Only sentences containing a known placeholder are examined; every other sentence of
  the answer passes unchanged. The stage does not proofread the external answer.
- A sentence over 8 placeholders or 1000 characters is substituted without the model.

Notes for later tasks:
- Task 9: the first model call after a cold load at `num_ctx` 8192 took 52 s on this
  machine against the stage's 15 s limit, so the first restoration would silently fall
  back to substitution. The pipeline needs a warm-up before the first call, or a longer
  limit for it. The stage reads the external stream independently of restoration, so a
  slow restoration no longer starves the external client's deadline, but the queue is
  bounded by the answer cap only.
- Task 9: any exception from the stage means the answer is incomplete; sentences
  already yielded stay valid.
- The opt-in debug transcript records the restoration prompts (the sentence and the
  original values), as for the other local stages.
