# Spike v2.1.0-1: combined transcribe-and-sanitize pass on Gemma

**Status:** In progress. Harness prepared (2026-10-18); next is the
human-run `tasks/spike-v2.1.0-1-handoff.md` (recording, then the runs).
The decision rule, thresholds, corpus size (44 utterances plus controls), and
the WAV production method (a recorder through the production capture path)
were confirmed and frozen by the owner on 2026-10-18. The corpus script
(texts, labeled spans), the test topics text, and the sanitize prompts were
reviewed and frozen by the owner on 2026-10-18 as well; do not edit any of it
after the first recording.
**Story:** `story-v2.1.0-personal-proxy.md`, task 1 (settled constraint 2).
**Type:** investigation spike. No change under `src/jarvis`. Model runs are
human-run (live Ollama); the parser and scorer are pure logic and CI-tested.
**Depends on:** nothing.

## Question

Can one Gemma request over the audio return the raw transcript, the sanitized
text, the placeholder mapping, and the verdict as reliably as the two-step
shape (bare transcription, then a text-only sanitize pass), and fast enough
to justify merging them?

## Why the prior favours two steps (stated before the run)

- Audio attention on this model is request-shape-sensitive. The closed study
  `2026-09-01-request-shape-suppresses-audio-attention.md` found that a system
  prompt, tool declarations, and the current-turn wording each degraded
  transcription of the same clips; only the bare request with the English
  verbatim instruction is the best measured shape, and it was still usable on
  3/5 clips for Q8_0. A combined call must carry sanitization rules, the topics
  text, and an output schema: the longest added instruction of any shape
  measured so far.
- The failure mode is a bluff, not an error: when the audio is not attended,
  the model answers from the text alone, so a combined call would return a
  plausible, fluent, wrong "sanitized text". Both shapes share that risk
  class; the question is whether the combined shape raises its probability.
  The outbound gate cannot see it (the text looks clean).
- Expected speed gain (an estimate made before measurement): the second call of
  the two-step shape is text-only over a short transcript, so the saving is
  likely well under a second. If that holds, the merge buys little and costs
  the one proven audio shape.

So this spike mostly tests whether the combined shape can be non-inferior. It
is not expected to win on quality.

## Fixed (do not re-open in this spike)

- Audio goes through the `images` field of `/api/chat`; no `audio` field.
- One model: the `[backend].model` of the run (`gemma4:12b` at the time of
  writing). Results are claims about that model and quant only; the closed
  study showed quant and variant change audio behaviour a lot.
- Reasoning off for every call (the production sanitize pass is latency
  sensitive). Reasoning levels are out of scope.
- The story's two-step fallback is the baseline arm, so building the baseline
  is not wasted if the combined arm fails.
- Methodology lessons carried from the closed study, as hard rules:
  independent utterances rather than repeats of one clip; scoring declared
  before the run; record the Ollama version, the model digest (`/api/show`),
  explicit `num_gpu`, and the effective options of every call; verify that no
  config override (for example `config.ui.toml`) changed the model; keep raw
  requests, raw responses, and WAV SHA-256 values in a gitignored artifact
  directory; report n for every figure.
- **No real personal data.** The corpus is a script of invented identities.
  The owner reads fictional names, numbers, and addresses aloud.

## Arms

All arms: audio attached via `images`, no tools, `think: false`, a fixed seed,
the same WAV bytes (after the production short-clip padding, so the arms see
what production would send).

- **T+S (two-step baseline).** Step T is the production transcription shape:
  bare request (no system message), the English verbatim instruction
  (`DEFAULT_TRANSCRIPTION_INSTRUCTION` in `journal/transcription.py`),
  `[generation.transcription]` options. Step S is text-only: a system prompt
  with the sanitization rules, the test topics text, and the output schema;
  the user message is T's transcript. No audio in step S.
- **C-user (combined, instruction in the user turn).** One request, no system
  message; the user message holds the sanitization rules, the topics text, and
  the schema, with the audio attached.
- **C-system (combined, instruction in a system message).** The rules,
  topics, and schema in a system message; a short user instruction; audio
  attached. Exists to test whether the closed study's system-prompt
  degradation reproduces here.

Output schema (all arms' sanitize step): `verdict` (`send` or `refuse`),
`reason` (for refuse), `raw_transcript`, `sanitized_text`, `mapping`
(placeholder to original). In T+S, `raw_transcript` is step T's output copied
in by the harness.

**Stage 0 (feasibility probe, no decision).** Before the main run, on 12
corpus utterances, C-user is run with and without Ollama's constrained
`format` (JSON schema). Whether `format` works together with `images` on this
model is unknown, and it is itself a request-shape factor. The mode with the
higher validity rate (ties: unconstrained) is fixed for all arms before the
main run and recorded. Stage 0 outputs are not part of the main data.

**Controls** (all arms): digital silence (2 s), room noise without speech
(3 s), and a no-media request. The model must not return a `send` verdict
with invented text. Per the closed study, no-media controls refused 15/15 on
the bare shape; the combined shapes are not assumed to.

## Corpus (proposal; frozen by the owner before any recording)

44 scripted utterances, Russian unless stated, each with a reference text (the
script), labeled sensitive spans, and an expected verdict. A span carries a
type (`PERSON`, `ORG`, `PHONE`, `EMAIL`, `ADDRESS`, `CARD`, `ACCOUNT` (an IBAN
or a national account number), `DATE`, `AMOUNT`, `SECRET`, `GOV_ID`, `OTHER`) and a class (`direct` identifier or `quasi`
identifier, such as employer plus city plus role).

- 18 identifier-rich: names in several cases and with patronymics, phone
  numbers, dictated emails, addresses, organizations, card and IBAN numbers,
  dates, amounts. Numbers are dictated in more than one way (digit by digit,
  in groups, as numbers) on purpose: how each arm renders them (digits or
  words) decides what the gate's patterns must catch (story task 3).
- 6 quasi-identifier utterances (reported separately; not a gate criterion).
- 6 mixed Russian/English names and technical terms.
- 8 utterances touching a test topics file (a neutral file written for the
  spike: for example a medical condition, a legal dispute, a debt); expected
  verdict `refuse`.
- 6 utterances with no sensitive content (meaning-preservation and
  false-refusal controls).
- Length strata across the categories: at least 8 clips of 2 s or less (the
  fragile stratum) and at least 6 clips of 15 s or more (the limit is 30 s).

Runs: 44 utterances x 2 seeds x 3 arms = 264 end-to-end generations, plus
controls (3 inputs x 2 seeds x 3 arms). The first call after model load is
recorded separately as cold. Stage 0 adds 12 x 2 generations.

## Measurements (automated scorer, pure logic, CI-tested on fixtures)

Normalization (as in the closed study): casefold, `e` for `yo`, strip
punctuation, collapse whitespace.

1. **Output validity.** Parseable output with every required field and a
   legal verdict; failures counted by class (no JSON, missing field, wrong
   type, extra prose, truncated by `done_reason = length`).
2. **Transcript fidelity.** WER of `raw_transcript` against the script. An
   **audio failure** is an output that matches the "nothing in this audio"
   refusal wording, or has WER above 0.5 (a bluff). Count per arm.
3. **Span leak.** A labeled sensitive span is leaked if its normalized
   surface, or a Russian-declension-tolerant stem of it, appears in
   `sanitized_text`. Reported as spans leaked over spans labeled, per span
   type and class, plus the share of utterances with at least one leak. For
   numeric spans, also record whether the sanitized or raw text rendered them
   as digits or as words.
4. **Mapping correctness.** For every replaced span, `mapping[placeholder]`
   equals the span surface up to normalization. Needed for restoration. Error
   rate reported.
5. **Meaning preservation.** The fraction of non-sensitive reference content
   tokens retained in `sanitized_text` (order-insensitive); over-redaction
   shows as a low value. The owner skims 12 sampled pairs as a sanity check;
   this is reported, not a gate.
6. **Verdict.** Refuse-expected utterances refused; send-expected utterances
   falsely refused.
7. **Fabrication on controls.** Any `send` with non-empty `sanitized_text` on
   a control input.
8. **Latency.** Wall time from request start to the last token, per stage and
   end to end per utterance; median and p90, warm calls only. The harness
   warms the model first.

## Restoration block R (text-only, independent of the arms)

Restoration does not involve audio, so it is not subject to the audio
request-shape problem and is measured on its own. A set of 30 synthetic Russian
sentences written as an external model's answer, each with 1-3 placeholders
in varied grammatical cases and a mapping whose originals are in the
nominative (invented identities; drafted by the agent, frozen by the owner).
The restoration pass runs with reasoning off. Measured:

- **Validation pass rate:** no placeholder text left; every original present.
- **Alteration rate:** sentences in which tokens outside the restored spans
  changed.
- **Case correctness:** the owner, blind, marks each restored sentence
  grammatically correct or not; compared with the deterministic substitution
  fallback (original in nominative) on the same items.

Decision for R, proposed: keep restoration through Gemma if the validation
pass rate is at least 90%, the alteration rate is at most 5%, and its case
correctness is higher than the fallback's on at least 80% of the items where
the fallback is wrong. Otherwise the story keeps only the deterministic
fallback and loses the grammar benefit; that is reported to the owner, not
decided here.

## Decision rule for the combined shape (FROZEN by the owner, 2026-10-18)

Primary comparison: each combined arm against T+S over its 88 generations
(44 x 2). Controls are scored separately.

A combined arm is **Go** (the story keeps one pass; settled constraint 2
stands) if all hold:

1. Validity at least 95%, and not more than 3 percentage points below T+S.
2. Audio failures not more than 2 above T+S's count.
3. Median WER of `raw_transcript` not more than 0.02 (absolute) above T+S's.
4. Span leak rate not more than 2 percentage points (absolute) above T+S's.
5. Mapping error rate not more than 3 percentage points above T+S's.
6. Meaning preservation not more than 3 percentage points below T+S's.
7. Fabrications on controls not more than T+S's.
8. Speed: the median end-to-end gain (T+S minus the combined arm) is at
   least 1.0 s.

If both combined arms are Go, the one with the lower leak rate is chosen;
a tie goes to C-user (simpler).

**Close** (the story re-plans to the two-step shape; the story and task cards
are updated) if, for every combined arm, either:

- quality closure: validity below 90%, or audio failures more than 5 above
  T+S, or leak rate more than 5 percentage points above T+S; or
- speed closure: the median gain is below 1.0 s (the merge then has nothing to
  offer, whatever its quality; same logic as the mode 3b spike).

**Anything else** goes to the owner with the numbers. No additional runs
without a named hypothesis they would test.

The following are reported, never part of the rule above: T+S's absolute leak
rate and absolute audio-failure rate, the number-rendering finding, the
quasi-identifier leak rate, and block R. They are inputs to the story's
remaining design (the gate's patterns, the restoration decision, and the
product question of whether the achievable recall is acceptable).

## Stop conditions

- Stop and report if T alone (the baseline's transcription step) has an audio
  failure rate above 10% of generations. Then transcription itself is not
  reliable enough for this feature, whatever the merge decision, and the
  roadmap's dedicated-STT-engine question is back on the table (owner
  decision, 0.4).
- Stop if the harness cannot reproduce the production transcription request
  shape byte for byte (the baseline must be the real thing, not an
  approximation).
- Stop if Ollama's constrained `format` changes the audio behaviour in Stage
  0 in a way that cannot be told apart from noise at that sample size; record
  it and run unconstrained.

## Deliverables

- Frozen corpus (script, labeled spans, expected verdicts), the test topics
  file, and the frozen sanitize prompt and schema, reviewed by the owner
  before any recording.
- A way to produce the WAVs. Proposal: a small recorder under `manual/` that
  reads the script line by line, captures through the production capture and
  padding path, and writes WAVs plus a manifest with SHA-256 values.
  Alternative: the owner supplies 16 kHz mono WAVs from any tool and the
  harness applies the production padding.
- Harness under `manual/` (live Ollama, human-run) writing raw requests and
  responses to a gitignored directory.
- Parser and scorer with CI tests under `manual/tests/` on hand-written
  fixtures covering every validity class, stem matching, number rendering,
  WER normalization, audio-failure classification, and timing.
- A self-sufficient human-run handoff per `CLAUDE.md` Testing protocol item 4,
  checked with `tools/check_handoff_self_sufficiency.py`.
- Results note; on completion the verified facts go into `PROJECT.md` and the
  raw study into `docs/experiments/personal-proxy-spike/`.

## Out of scope

- Any change under `src/jarvis`.
- Reasoning levels, other models or quants, constrained decoding beyond
  Stage 0.
- Calling an external model; the outbound gate; the topics editor.
- Real personal data of any kind.

## Owner decisions (2026-10-18)

1. Thresholds in the decision rule, the restoration rule, and the stop
   condition: confirmed as written (including the 1.0 s speed gate and the 2
   and 5 percentage-point leak margins).
2. Corpus: 44 utterances plus controls: confirmed.
3. WAVs are produced by a recorder through the production capture path.

## Implementation notes (2026-10-18)

Definitions the card left open, fixed while writing the scorer; none changes a
frozen threshold.

- **Where the code lives:** `manual/personal_proxy/` (corpus, prompts,
  parser, scorer, decision rule, report, runner, recorder flow, restoration),
  `manual/manual_check_personal_proxy_spike.py` (stage0 / run / score),
  `manual/manual_check_personal_proxy_restoration.py` (block R),
  `manual/manual_record_personal_proxy_corpus.py` (recorder), tests in
  `manual/tests/`. Review the corpus with
  `python -m manual.personal_proxy.corpus`.
- **Leak** is counted over the spans of generations that are valid and carry
  the `send` verdict (what would leave the machine). A refusal sends nothing;
  an invalid output is counted by the validity criterion, not here. A text span
  leaks when a stem of one of its forms matches a token of the sanitized text
  (stem: drop two letters, keep at least three, so a declined form matches).
  A numeric span leaks when one of its digit keys is a substring of a digit run
  of the sanitized text, where number words are first converted to digits
  (so a phone left as words is caught, and reported as "words" not "digits").
- **Audio failure** is evaluated on the raw transcript only: it matches the
  documented "nothing in this audio" refusal wording, or its word error rate
  against the script is above 0.5. WER normalizes number words to digits on
  both sides.
- **Mapping error** is counted over spans that did not leak: the mapping must
  contain a value that matches the span (by form stem or digit key).
- **Meaning preservation** is computed on send-expected, valid, `send`
  generations: the share of the script's non-sensitive words of four or more
  letters that survive in the sanitized text by stem.
- **Fabrication** (controls) is a valid `send` verdict with non-empty
  sanitized text. In the two-step arm that includes a refusal sentence of the
  transcription step that the text-only step passes on as a request.
- **Latency** is the sum of the arm's calls, warm generations only (a call
  with a model load over 1.0 s makes its generation cold).
- **Production shape:** the transcription step builds its payload with
  `OllamaBackend.build_payload` and `build_transcription_messages`, exactly as
  `OllamaTranscriptionBackend` does; `test_transcription_payload_matches_the_production_builder_exactly`
  asserts the payload equality. It differs from production only by the
  per-run `seed` and `num_predict` (the runaway cap) and reasoning being
  fixed off.
- **Not sent:** `options.num_gpu` (production does not send it). GPU placement
  is read from `/api/ps` after the run and reported instead, so the variable
  the closed study found uncontrolled is at least visible.
- **WER digit grouping** (2026-10-18, before the main run): each run of digit
  tokens, whether read as words or written as digits, is merged into one token
  before the edit distance, so "4276 1234" and the same number read in
  groups of words compare equal; a wrong digit string costs one error.
  Applies to every arm alike. The thresholds are untouched.
- **Stage 0 result** (2026-10-18, model digest `41c402fd...`, C-user, 12
  utterances x 2 seeds): unconstrained output was valid on 2 of 24 (13 wrapped
  in a ```json fence, 9 other non-JSON, both counted invalid by the strict
  parser); constrained `format` was valid on 24 of 24. Ollama accepted
  `format` together with an audio attachment. By the frozen Stage 0 rule the
  main run uses constrained output for every arm.
