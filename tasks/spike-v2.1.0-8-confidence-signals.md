# Spike v2.1.0-8: confidence signals for the speech-to-text step

Status: In progress. Rule frozen 2026-10-19, before any run.

Parent story: `tasks/story-v2.1.0-personal-proxy.md`. Follows spike 7
(`tasks/spike-v2.1.0-7-stt-audio-check.md`): Gemma with the recording repairs
spoken e-mail addresses, but it also invents content (a second address that was
never spoken, a Russian request turned into English) and does not repair digits;
temperature does not remove this. The owner's requirement (2026-10-19): the
system must be able to say "I could not recognize the request with enough
confidence, nothing is sent outside, rephrase or type it", so we need a signal
of confidence, not only a better transcript.

## Question

Which signals tell reliably that the transcript that would go on to
sanitization is wrong in a sensitive place, without refusing on most good
requests?

## Pipeline under test

1. **Whisper** (spike 5 configuration) with word timestamps, so that every
   word has a probability, every segment `avg_logprob`, `no_speech_prob`, and
   `compression_ratio`. Its text must equal spike 5's transcript (checked).
2. **Samples:** `gemma4:12b`, `num_ctx` 8192, the recording in `images`, the
   Whisper transcript with every word of probability below 0.5 followed by
   `[?]`, the error hint of spike 7, and a sentence that `[?]` words were
   uncertain for the engine and are to be checked, not assumed wrong; the output
   is the corrected transcript without marks. Six samples per recording: the
   temperatures 0.418, 0.618, 0.818 (the base 0.618, minus and plus 0.2), each at
   the two corpus seeds. Other options as in spike 7. The **base sample**
   (temperature 0.618, seed 19210) is the text that would go on.
3. **Judge:** `gemma4:12b` at temperature 0, seed 1, with the recording, the
   Whisper transcript, and one sample. It lists the fragments it is unsure of
   (numbers, addresses, names; quoted exactly) and gives one overall confidence
   from 0.0 (critical failure) to 1.0 (full confidence), as constrained JSON
   (`format`). It is run on every sample.

## Signals (each scored per recording; higher means more suspicious)

- **S1 agreement:** size of the symmetric difference between the sensitive
  projections of the Whisper text and the base sample. The projection is the
  set of: digit runs (digit groups separated by spaces or hyphens joined; at
  least 4 digits), the count of address markers (`@`, `собак`, `sobak`), Latin
  words of 3 or more letters, and the 4-letter stems of capitalized Cyrillic
  words that are not the first word of a sentence.
- **S2 instability:** mean pairwise symmetric difference between the projections
  of the six samples; the projection here also contains each literal address
  (a token with `@`, lowercased, trailing punctuation removed).
- **S3 engine confidence:** three scores. S3a: 1 minus the lowest probability
  among Whisper words that contain a digit or Latin letter or are capitalized and
  not sentence-initial (0 when there are none). S3b: maximum `no_speech_prob`
  over segments. S3c: minus the lowest `avg_logprob` over segments.
- **S5 validators:** count of invalid items in the base sample: an address token
  that does not match `local@domain.tld` (tld of 2 or more letters), and a
  digit run of 7 or more digits whose length is not 10, 11, 12, 16, or 20.
- **J judge:** J1: 1 minus the base sample's confidence. J2: 1 minus the lowest
  confidence over the six samples. J3: the number of fragments the base sample's
  judgment lists.
- **Trivial baseline T:** 1 if the base sample's projection is not empty, else 0
  (refuse on everything that looks sensitive).

## Labels

A recording is **bad** when the base sample has, in a sensitive place: a
labeled span that is not recognizable (the `leaked_spans` stem and digit-key
match of spike 5), or an address in excess of the markers in the Whisper text
(`invented_address` of spike 7), or a language switch (the share of Cyrillic
among letters falls below half of the Whisper text's share). Otherwise it is
**good**. The reference text and spans are those of spikes 2-5 (the
`id_birth_date` correction included). This is the owner's variant B (2026-10-19):
a wrong or invented sensitive fragment counts, not only a missing one.

The two silence and noise controls are scored apart: a signal that claims them
must flag both.

## Decision rule (frozen)

For each signal (and each of S3a-c, J1-J3 separately), over the 44 recordings, a
threshold is a rule "flag when the score is at least t". Let recall be the
share of bad recordings flagged and false refusals the share of good recordings
flagged. A signal **discriminates** when some t gives recall of at least 0.8
and false refusals of at most 0.2, and its false refusals at that t are lower
than those of T at its own recall. For S3b and S3c the controls must also be
flagged at that t. The number of bad recordings is reported first: with fewer than
5, nothing is concluded. For every signal the best operating point (largest
recall minus false refusals) is reported even when it does not discriminate.
Also reported: pairwise agreement of the discriminating signals (which bad
recordings each catches), the judge's confidence in bad and in good recordings,
the share of uncertain fragments that sit on a bad fragment, and the effect of
the `[?]` marks on the samples against spike 7's X variant (spans fixed,
broken; invented addresses; rewritten generations).

The thresholds (0.8, 0.2, 0.5 for the marks, the pair of temperatures) are the
owner's and the agent's choice, not statistics.

## Honest limits

- 44 recordings, one speaker, invented identities. Bad recordings are expected to
  number about 6-12; the six samples of one recording and its seeds are not
  independent evidence, and Whisper's transcript and probabilities are
  deterministic.
- A threshold chosen on the same data that judge it is optimistic. A result reads
  "discriminates" or "does not", never "use t".
- The projection is a heuristic: it is lenient on names (4-letter stems) and
  blind to a wrongly assembled domain unless two samples disagree on it.
- The judge is the same model that wrote the samples and hears the same audio.
- The validators know only lengths, not context (a wrong phone number of the
  right length passes); no Luhn check is used because the corpus card numbers are
  invented.
- Latency: one Whisper pass, six samples, six judge calls per request, roughly
  3 to 5 seconds on this GPU; whether that is acceptable is a story decision.

## Run

Human-run by default (live Ollama and GPU); the owner's instruction to run it
here is recorded in the Result. Preconditions as in spike 7, and
`.venv-stt-whisper` with `faster-whisper` 1.2.1. Commands:

```
.venv-stt-whisper\Scripts\python.exe -m manual.manual_check_confidence_signals --out manual_check_confidence_out words --wavs personal_proxy_corpus_wavs
python -m manual.manual_check_confidence_signals --out manual_check_confidence_out run --wavs personal_proxy_corpus_wavs
python -m manual.manual_check_confidence_signals --out manual_check_confidence_out score --wavs personal_proxy_corpus_wavs
```

`words` stops with an error if a word-level transcript differs from spike 5's
text. `run` resumes: existing call files are skipped.
