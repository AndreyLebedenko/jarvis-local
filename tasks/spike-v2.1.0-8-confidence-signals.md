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

## Result (2026-10-19, run by the agent on the owner's instruction)

Whisper word data: 46 recordings, text identical to spike 5's in all 46. Then
276 samples and 276 judge calls (`gemma4:12b`, `num_ctx` 8192, no unparsable
judge answer). Report: `manual_check_confidence_out/report.md` (gitignored).

**Verdict by the frozen rule: no signal discriminates.** 7 of 44 recordings are
bad, 37 good; the trivial baseline T refuses on every bad one and on 65% of
the good ones.

| signal | best threshold | recall | false refusals |
|---|---|---|---|
| S1 Whisper vs sample | 4 | 0.29 | 0.03 |
| S2 instability | 0.6 | 0.43 | 0.05 |
| S3a weakest sensitive word | 0.135 | 0.57 | 0.35 |
| S3b `no_speech_prob` | 0 | 1.00 | 1.00 |
| S3c worst `avg_logprob` | 0.106 | 1.00 | 0.59 |
| S5 validators | 0 | 1.00 | 1.00 |
| J1 judge confidence | 0.05 | 0.43 | 0.11 |
| J2 lowest confidence of six | 0.1 | 0.43 | 0.11 |
| J3 listed uncertain fragments | 1 | 0.43 | 0.11 |

Signals that are precise (S1, S2, J) catch at most 3 of 7; signals that catch
all (S3b, S3c, S5) do so only at thresholds that refuse nearly everyone.

What the 7 bad recordings are (expected / actual):

- **Real errors (4):** `n_short_translate` (Russian request became English;
  caught by S1, S2, S5); `m_trade_house` (a second address invented, the domain
  wrong; S1, S2, J1-J3); `id_two_people_phone` (spoken 8 912 345 67 89, got
  "60 78 9"; S3a, J1-J3); `id_letter_long` (organization "Альфатрейд" heard as
  "Альфтеррейт"; S2, S3a, J1-J3).
- **Label artifacts of the frozen rule (3):** `id_email` (output
  `ivan.petrov@primer.com` is correct, but its Cyrillic share fell below half
  of the Whisper text's, so the language-switch test marked it bad);
  `m_short_call` and `m_northwind_long` (English names spoken, written in
  Cyrillic by Whisper and kept by Gemma, so the Latin forms of the labeled
  spans are not found, while the names are intact for a sanitizer). These three
  are the ones no precise signal catches.

Per signal:

- **Judge confidence is not informative:** mean 0.95 on bad and 0.99 on good
  recordings; it says "fully confident" on the silence control. The listed
  fragments (J3) carry the little signal there is: listed on 3 of 7 bad (3 of
  the 4 real) and on 4 of 37 good (`m_github`, `q_accountant`,
  `q_pathologist_long`, `t_hypertension_long`, all places where Whisper really
  had an unrepaired mistake).
- **`no_speech_prob` is 0.000 on every recording, including the silence and noise
  controls**, with `language="ru"` forced and no VAD; S3b is useless as
  configured. The controls separate on no signal: S3c is 0.075 (silence) and 0.180
  (noise), within the range of speech (0.05 to 0.56); the judge's confidence is 1.0.
- **Whisper word probabilities (S3a) catch the digit and name errors**
  (`id_two_people_phone` 0.18, `id_letter_long` 0.69, `m_short_call` 0.13) but
  flag 35% of the good recordings, many for ordinary names with weak probability.
- **Validators (S5)** flag nothing in the corpus at the base sample: the
  broken-length and broken-address checks never fire, because the errors that
  matter are wrong digits of the right length and a plausible address.
- **Effect of the `[?]` marks:** against spike 7's X (no marks) at the same
  temperature: 6 failures of 88 (5), fidelity 0.875 (0.896), spans fixed 2 (4),
  broken 0. The marks did not help the samples; if anything they helped less.

Post hoc, not part of the rule (read as a hypothesis, 4 real bad recordings is
fewer than the 5 the card requires): the union "S1 >= 4 or J3 >= 1" flags all 4
real errors and 4 of the 37 good recordings (0.11: `m_github`,
`q_accountant`, `q_pathologist_long`, `t_hypertension_long`). It was chosen after looking at the
data and is not evidence.

Deviation from the card: "the share of uncertain fragments that sit on a bad
fragment" was replaced by the count of recordings where the judge listed
anything (above); the pairwise agreement is the "caught by" list in the report.

Reading: with Whisper plus a Gemma checker, none of the cheap signals alone
gives a usable "not sure enough, type it" decision on this corpus; the judge's
list of doubtful fragments and the disagreement between Whisper and the sample
are the two that point at real errors and have few false refusals, and they
catch different recordings. Silence and noise need a gate before the engine
(speech detection or energy), not a confidence signal. The frozen label rule
produced three artifacts and should be revised (a Latin transliteration of a
spoken address is not a language switch; a name written in Cyrillic is not
lost) before any further spike reuses it.

## Relabeling (post hoc, 2026-10-19, same data, owner's remark)

The owner's remark: a spoken e-mail address is always written in Latin, so it
must not count as a language switch; the check is about how plausible the
combination of texts is given the audio, not about comparing texts. The labels
were recomputed with two revised rules (`score --label-rule`; nothing is run
again, the samples and judge answers are the recorded ones):

- `addresses_are_latin`: tokens with `@` are ignored in the Cyrillic-share test.
- `names_in_any_alphabet`: also, person spans whose labeled forms are Latin only
  (English-spoken names) are not scored, because Whisper writes them in Cyrillic.
  This second rule is the agent's choice, not the owner's.

| label rule | bad | good | best of S1 / S2 / J1-J3 (recall at false refusals) | discriminates |
|---|---|---|---|---|
| frozen | 7 | 37 | 0.29 / 0.43 / 0.43 at 0.03-0.11 | none |
| addresses_are_latin | 6 | 38 | 0.33 / 0.50 / 0.50 at 0.03-0.11 | none |
| names_in_any_alphabet | 4 | 40 | 0.50 / 0.75 / 0.75 at 0.03-0.10 | none (4 bad: nothing concluded) |

With the corrected labels the four real errors (`n_short_translate`,
`m_trade_house`, `id_two_people_phone`, `id_letter_long`) are caught by S2
(instability) and by the judge's list of doubtful fragments (J3) at 3 of 4, with
5% and 10% false refusals; S1 catches 2 of 4. They catch different recordings:
S2 and S1 miss `id_two_people_phone` (Whisper and every sample agree on the same
wrong digits), the judge catches it. S3a, S3c, S3b and S5 stay useless as
configured. The frozen rule still says "does not", since 3 of 4 is 0.75 against
the 0.8 required and the four is below the 5 the card requires.
