# Spike v2.1.0-9: the confidence hypothesis on a fresh corpus

Status: In progress. Rule frozen 2026-10-19, before the owner's recordings and
before any measurement on this corpus.

Parent story: `tasks/story-v2.1.0-personal-proxy.md`. Follows spike 8
(`tasks/spike-v2.1.0-8-confidence-signals.md`): on the first corpus no signal
met the rule, but after the labels were corrected the instability of the
Gemma samples (S2) and the judge's list of doubtful fragments (J3) each caught
3 of the 4 real errors at 5% and 10% false refusals, and together all 4 at 11%.
That was chosen after looking at the data, and 4 errors are too few. The
owner asked (2026-10-19) for more critical and harder recordings, in the owner's
voice and in the two Silero voices `eugene` and `baya`.

## Question

Does the hypothesis H, frozen below from spike 8, hold on recordings it has
not seen?

## New corpus

Ten phrases (`PHRASES` in `manual/personal_proxy/corpus_v2.py`) with critical or
hard content: an irregularly grouped phone number, an address with an underscore
and digits spelled letter by letter, passport series and number, a 16-digit card
number, an English name and brand inside Russian speech, a rare surname with a
patronymic, a composite address (building, section, apartment), a 12-digit tax
number with a date, an SMS code, and a mixed-alphabet login. Every identity is
invented; numbers are written as words and read as written.

Each phrase exists in three voices: the owner's (read through the production
capture path, `config.toml`), and the Silero voices `eugene` and `baya`
(`v3_1_ru`, the production TTS engine with its number and Latin preprocessing,
24 kHz resampled to 16 kHz mono and padded as the `[vad]` section of
`config.toml` says). 30 recordings, utterance ids `<phrase>__<voice>`. Labeled
spans (`forms`, `digit_keys`) are in the same module and are frozen by
`corpus_v2_fingerprint()` and the manifest of the recording directory.

## Pipeline

As in spike 8, unchanged: Whisper (`language="ru"`, beam 5, word timestamps), six
Gemma samples (`gemma4:12b`, `num_ctx` 8192, temperatures 0.418, 0.618, 0.818 at
the two corpus seeds, `[?]` marks under 0.5, the error hint), and the judge
(temperature 0, with the recording, on every sample). The base sample is
temperature 0.618, seed 19210.

## Labels

A recording is bad by the revised rule `names_in_any_alphabet` of spike 8:
a labeled span not recognizable in the base sample (the English-spoken person
spans with Latin-only forms are not scored), an address in excess of the
markers in the Whisper text, or a language switch in which tokens with `@` are
ignored.

## Hypothesis H (frozen from spike 8)

A recording is flagged ("not sure enough, nothing leaves, rephrase or type it")
when `S2 >= 0.6` or `J3 >= 1`, where S2 is the mean pairwise symmetric
difference between the sensitive projections (with literal addresses) of the six
samples, and J3 is the number of uncertain fragments the judge lists for the
base sample. These are the thresholds of spike 8, not refit.

## Decision rule (frozen)

Over the 30 new recordings (and, reported separately, per voice):

- **H holds** if its recall of bad recordings is at least 0.8 and its false
  refusals (good recordings flagged) at most 0.2, and its false refusals are lower
  than those of the trivial baseline T (refuse when the base sample contains
  digits, Latin words, name stems, or an address; the definition of spike 8).
- **H fails** if recall is below 0.6 or false refusals exceed 0.35.
- Otherwise **inconclusive**.
- With fewer than 5 bad recordings nothing is concluded; the numbers are still
  reported.

Also reported, not decisive: S1 at 4, S2 and J3 alone at the same thresholds, J1
(judge confidence), S3a, S3c, S5 with their spike 8 best thresholds; which bad
recordings each catches; the bad recordings by voice and by phrase; the 74
recordings of both corpora pooled (the first corpus is not independent of the
thresholds).

The thresholds (0.8, 0.2, 0.6, 0.35) are the agent's choice under the owner's
delegation, not statistics.

## Honest limits

- 30 recordings, 10 distinct texts: the three voices of a phrase share its
  content, so they are not 30 independent texts, and a phrase that is hard in
  one voice is likely hard in all.
- TTS voices are clean and read exactly as written; Whisper may be near-perfect on
  them, leaving few bad recordings. The owner's voice is the realistic part.
- One run, one model, one GPU, one owner.
- Spans' `forms` and `digit_keys` are written by the agent and check the surface
  of a recognized value, not its correctness in context (a wrong digit string of
  the same length is lost only if the key differs).
- The first corpus was measured and the thresholds taken from it: H is checked
  here against a rule it did not see, but the phrases were written knowing which
  kinds of error it caught.

## Run

Human step first: the owner's ten recordings. The TTS voices are already in
`personal_proxy_corpus_v2_wavs/` (generated by
`python -m manual.manual_generate_tts_corpus`, which uses only the local Silero
model and no microphone).

Recording (microphone; run by the owner). The microphone and host API are
read from `[microphone].device` and `[microphone].host_api` in `config.toml`; the
voice-activity thresholds from `[vad]` there (`request_end_pause_seconds` 1.5 at
the time of writing: pause for less than that inside a phrase, and stay silent
after the last word). The recorder shows each phrase; keys: Enter starts, then
Enter accepts, `r` records again, `p` plays back, `q` quits. It resumes where it
stopped, so it can be started again at any time, and it records only the owner's
ten phrases:

```
python -m manual.manual_record_personal_proxy_corpus --corpus v2
```

Check, expected output `30 recordings verified`:

```
python -c "from pathlib import Path; from manual.personal_proxy.audio import WavDirectory; from manual.personal_proxy.corpus_v2 import CORPUS_V2, corpus_v2_fingerprint; WavDirectory(Path('personal_proxy_corpus_v2_wavs'), CORPUS_V2, corpus_v2_fingerprint()); print('30 recordings verified')"
```

Measurement (run by the agent after the owner confirms, GPU and Ollama, as in
spike 8):

```
.venv-stt-whisper\Scripts\python.exe -m manual.manual_check_confidence_signals --corpus v2 --out manual_check_confidence_v2_out words --wavs personal_proxy_corpus_v2_wavs
python -m manual.manual_check_confidence_signals --corpus v2 --out manual_check_confidence_v2_out run --wavs personal_proxy_corpus_v2_wavs
python -m manual.manual_check_confidence_signals --corpus v2 --out manual_check_confidence_v2_out score --wavs personal_proxy_corpus_v2_wavs --label-rule names_in_any_alphabet
```
