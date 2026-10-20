# Spike v2.1.0-9: the confidence hypothesis on a fresh corpus

Status: Result recorded 2026-10-19 (rule frozen before the owner's recordings and
before any measurement on this corpus). Closed 2026-10-20.

Parent story: `tasks/story-v2.1.0-personal-proxy.md`. Follows spike 8
(`tasks/done/spike-v2.1.0-8-confidence-signals.md`): on the first corpus no signal
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

## Result (2026-10-19, run by the agent on the owner's instruction)

The owner recorded the ten phrases (the directory verified as 30 recordings).
Whisper with word data on all 30, then 180 samples and 180 judge calls; no
unparsable judge answer. Report: `manual_check_confidence_v2_out/report-*.md`
(gitignored). Scored with `--label-rule names_in_any_alphabet`.

**Verdict by the frozen rule: nothing concluded.** Only 1 of 30 recordings is
bad (`v2_email_underscore__owner`), against the 5 the card requires. The new
corpus was not hard enough for Whisper plus the Gemma check: the labeled
spans are recognized in 29 of 30.

What was measured anyway (read as description, not as a test of H):

- H (`S2 >= 0.6` or `J3 >= 1`) caught the one bad recording and flagged 9 of the
  29 good ones (0.31, above the 0.2 bound). S1 at 4 flagged only the bad one;
  S2 alone 5 of 29, J3 alone 6 of 29. By voice: owner 1 of 9 good flagged, `baya` 3
  of 10, `eugene` 5 of 10.
- Whisper alone against Gemma with the recording, base temperature, both seeds
  (60 generations): audio failures 6 against 4; span fidelity 0.944 against 0.986;
  spans fixed 3, broken 0. This repeats spike 7: Gemma with audio repairs and
  does not damage.

What the recordings show (reference / Whisper / base sample):

- **Digits Whisper got wrong and Gemma repaired from the audio:** the card
  number in the owner's and `eugene`'s voices (spoken 5200 4681 9000 7772; Whisper
  `5200-4681-900-7772`, 15 digits; the sample `...-9000-7772`); the tax number
  prefix ("Могин", "Мой ин" became "Мой ИНН"). On these the judge listed doubts
  (J3 = 1 for the card), so H flags a recording whose final text is right.
- **A systematic failure, in all three voices: the underscore address.**
  Spoken "алекс точка смирнов подчёркивание девяносто два собака почта точка ру"
  (the intended `alex.smirnov_92@pochta.ru`); Whisper wrote
  `alex.smirnov-92-sobacapochta.ru`, `...92sobakopochta.ru`,
  `...92sobakopochta.ru` with `.`; the samples
  `alex.smirnov@92.собака_почта.ru` (owner), `alex.smirnov@92sobakopochta.ru`
  (`eugene`), `alex.smirnov.92@sobakapochta.ru` (`baya`). None is correct. The label
  marks only the owner's as bad (`invented_address` does not fire; the span's
  stems "alex", "smirnov" are present in all three), so **2 of the 3 real
  errors are good by the label**. The spans check stems and digit keys, not the
  correctness of a domain.
- **Plain misses of the check:** `v2_phone_grouped__eugene`: Whisper `Плюс 7 916...`,
  the sample rewrote the digits back into words ("Плюс семь девятьсот
  шестнадцать..."): the span is still found, but the text was rewritten without
  need. `Slack` became "слаг" or "Слэк" in two voices.

Post hoc, same data, not a test (3 real address errors instead of 1): H flags
all three, and 7 of the other 27 (0.26). Of those seven, three (the card number in two
voices, the rare surname in the `baya` voice) are recordings where Whisper's text
was wrong and Gemma repaired it, so the flag was justified by the engine's
uncertainty although the final text was right; the other four are doubts or
rewrites on texts that were already right (`partner_company__eugene`,
`phone_grouped__eugene`, `slack_login__baya`, `slack_login__eugene`).

The owner's remark during recording: the end-of-take cut is very close to the
last sound and sometimes clips the last fractions of a second. In the ten
owner recordings every phrase's last word is present in Whisper's text, so no
damage is visible here; ten takes cannot show how often the last syllable is lost.

Reading: the second corpus does not test the hypothesis, because Whisper plus
the Gemma check rarely fail on it; the hard case that remains is the spelled-out
address with an underscore. A new spike for H needs phrases that make the
system fail, or a larger set of address-like phrases, and labels that check the
assembled address, not only stems.

## Stricter label (post hoc, 2026-10-19, owner's request; recorded data only)

The frozen verdict above stands ("nothing concluded": 1 bad of 30). The owner
asked to check the assembled address as a whole and to recompute both corpora.
New label rule `addresses_assembled` (`manual/personal_proxy/address_labels.py`):
on top of `names_in_any_alphabet`, a phrase that spells an address is bad when
its output carries neither a right assembled address nor the spoken form
unchanged, or carries a second address. The right addresses are listed per
phrase (`ivan.petrov@primer.com` or `...@example.com`, `info@trade-house.ru`,
`dvolkov@gmail.com`, `alex.smirnov_92@pochta.ru`), five phrases in all. The rule
replaces the `invented_address` heuristic for those phrases, because Whisper
writes the marker as "sobaca" or "sobako", which the heuristic did not know. It was
written after both corpora were measured; H and its thresholds are unchanged.

| corpus | bad | good | H: recall / false refusals | frozen rule verdict |
|---|---|---|---|---|
| first (44) | 5 | 39 | 5/5, 4/39 = 0.10 | H holds |
| second (30) | 3 | 27 | 3/3, 7/27 = 0.26 | nothing concluded (3 bad) |
| both (74) | 8 | 66 | 8/8, 11/66 = 0.17 | H holds |

Pooled, by signal: J1, J2, J3 discriminate (recall 0.88 at 0.11 false refusals);
S1 reaches 0.75 at 0.00 and S2 0.62 at 0.09 and do not; S3a, S3b, S3c, S5 do not.
H alone: S2 5/8 with 6 false, J3 7/8 with 7 false, S1 at 4 catches 4/8 with none
false. The five bad recordings of the first corpus are `id_letter_long`,
`id_two_people_phone`, `m_github` (its address `dvolkov.sobaka@...`, newly bad),
`m_trade_house`, `n_short_translate`; the three of the second are the underscore
address in the three voices.

Why "H holds" here is weak evidence:

- The first corpus is where H was chosen; its 5/5 is the fit, not a test.
- The second corpus is the test, and it has 3 bad recordings (below the 5 the card
  requires) that are one phrase in three voices, so it is one independent
  case; its false refusals (0.26) exceed the 0.2 bound.
- The label rule was changed after the data was seen. The pooled 8 are about 6
  distinct errors.

Where the false refusals come from (second corpus, 7 of 27): three are recordings
where Whisper was wrong and Gemma repaired it, four are doubts or rewrites on a
text that was already right. The flag is useful in the first three and a
nuisance in the other four.

Reading: the judge's list of doubtful fragments (J3) is the most useful single
signal on both corpora (7 of 8 at 7 false refusals); the instability of the samples
(S2) adds the one error the judge misses. Nothing here is a validated threshold.
A trustworthy test needs more address- and digit-heavy phrases on which Whisper
fails, a label fixed before the run, and the answer to a product question the data
cannot give: whether a flag should refuse, or ask the owner to confirm the
listed fragments by voice.
