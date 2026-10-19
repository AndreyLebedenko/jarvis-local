# Spike v2.1.0-7: Gemma checks a Whisper transcript against the recording

Status: Result recorded 2026-10-19 (rule frozen before any run).

Parent story: `tasks/story-v2.1.0-personal-proxy.md`. Follows spike 5
(Whisper large-v3-turbo wins as the first step) and spike 6 (it runs on the GPU
next to `gemma4:12b` INT4 at `num_ctx` 8192 without a swap penalty). Whisper's
weak spots are the ones that matter for privacy: spelled-out e-mail addresses,
digit strings, and foreign names (span fidelity 0.854). The owner proposed on
2026-10-19 giving Gemma the transcript and the recording together, with a hint
about Whisper's typical mistakes, so that Gemma checks the transcript.

## Question

Does Gemma, given a Whisper transcript, the recording, and a hint about the
engine's error kinds, return a transcript with higher span fidelity than Whisper
alone, without new failures? And is the gain due to the recording or only to
Gemma's text-level knowledge?

## Variants

Both use the production request shape for audio (the WAV in the `images` field)
where audio is present, `gemma4:12b`, `num_ctx` 8192, reasoning off, the
production generation options, `num_predict` 2048, the two seeds of the corpus.

- **X (text + audio):** the Whisper transcript, the recording, and the hint.
- **Z (text only):** the same prompt without the recording and without the
  sentence asking to listen. Control: shows what Gemma can fix by knowing the
  error kinds alone.
- **W (Whisper alone):** the transcripts of spike 5 (`whisper_ru`, language `ru`);
  no Gemma call. Reference for the decision.

The hint is generic by design: it names error kinds (letter-by-letter
addresses glued or mangled, digits dropped or merged, names respelled including
Latin names in Cyrillic, invented text on silence) and no corpus utterance. The
exact text is `ERROR_HINT` in `manual/personal_proxy/verification.py`, recorded in
`run_meta.json`. The instruction tells Gemma to fix only what is evidently wrong,
to output only the corrected transcript, and to output nothing when there is no
speech. The hint was written after reading spike 5's failures, so it is informed
by this corpus; a gain here is an upper estimate.

## Inputs

The same 44 recordings plus the silence and noise controls as spike 5, run at
both seeds (`SEEDS`): 88 scored generations per variant plus the controls. The
Whisper transcript fed to Gemma at seed index i is spike 5's pass i (identical
text; decoding is deterministic). Spike 5's `manual_check_stt_engines_out/calls`
is the input.

## Measurement

Reference text and definitions are those of spike 5, scored by the same
functions: audio failure (refusal pattern or WER above 0.5), median WER, span
fidelity overall and by group (numeric, email, person, other). Added:

- **Paired spans:** spans missing in W's transcript and found in X's (fixed), and
  spans found in W's and lost in X's (broken), per variant.
- **Controls** (reported only): whether the output is empty; Whisper invents
  text on all four silence and noise generations.
- **Cost** (reported): median seconds per call, maximum prompt tokens against
  `num_ctx` 8192, calls that did not stop normally.

## Decision rule (frozen)

Let `fW`, `fX` be audio-failure counts out of 88 and `qW`, `qX`, `qZ` overall span
fidelities.

- **Worse:** `qX <= qW - 0.02`, or `fX >= fW + 4`.
- **Better:** not worse, `qX >= qW + 0.03`, and `fX <= fW + 2`. If also
  `qZ >= qX - 0.02`, the verdict is **better without audio**: the gain comes
  from the hint and Gemma's text knowledge, and the recording is not needed.
- **No difference:** everything else.

The thresholds are the agent's choice under the owner's delegation, not
statistics. The paired spans are there for borderline outcomes.

## Honest limits

- One speaker, one room, 44 utterances, invented identities. The corpus has 48
  labeled spans per pass, 96 over two seeds. One span is about 0.010 of fidelity,
  so the 0.03 gain is 3 spans. Whisper's transcript is deterministic, so the two
  seeds repeat the same input: they do not make the spans independent, and 4
  fixed spans are about 2 distinct fixes. (The first version of this card
  miscounted the spans as 192; corrected after the run.)
- INT4 Gemma's hearing may differ from the q8 model of spikes 1-4; this spike
  does not separate model quantization from the task change.
- Fidelity is lenient for names (stem match): a respelled name that keeps its
  first letters counts as found, so the metric cannot reward fixing it.
- Gemma may return a corrected text that matches the reference by stem but
  drifts elsewhere; WER and the changed-generations list show that.
- A result says nothing yet about the sanitization step that follows.

## Run

Human-run by default (live Ollama and GPU); the owner's instruction to run it
here, if given, is recorded in the Result. The runner checks: `ollama ps` is
empty, `ollama list` shows `gemma4:12b`, `manual_check_stt_engines_out/calls`
holds the spike 5 files, and the Ollama server runs with
`OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=Q8_0`.

```
python -m manual.manual_check_stt_verification --out manual_check_stt_verification_out run --wavs personal_proxy_corpus_wavs
python -m manual.manual_check_stt_verification --out manual_check_stt_verification_out score --wavs personal_proxy_corpus_wavs
```

`run` resumes: existing call files are skipped. `score` writes `report.md` in the
output directory.

## Result (2026-10-19, run by the agent on the owner's instruction)

`gemma4:12b`, `num_ctx` 8192; 184 generations; report in
`manual_check_stt_verification_out/report.md` (gitignored).

| | audio failures | median WER | span fidelity | numeric / email / person / other |
|---|---|---|---|---|
| W: Whisper alone | 4 of 88 | 0.000 | 0.854 (82/96) | 22/24, 4/6, 26/34, 30/32 |
| X: text + audio | 5 of 88 | 0.000 | 0.896 (86/96) | 22/24, 6/6, 28/34, 30/32 |
| Z: text only | 4 of 88 | 0.000 | 0.854 (82/96) | 22/24, 4/6, 26/34, 30/32 |

Verdict by the frozen rule: **better** (gain 0.042 >= 0.03, failures 5 <= 6, and
Z equals W, so the gain comes from the recording, not from the hint). Paired
spans: X fixed 4, broke 0; Z fixed 0, broke 0. Cost: median 0.50 s per call
(Z 0.44 s); the largest prompt is 987 tokens of 8192, so the recording is cheap
in context; no call was cut off.

What the 4 fixed spans are: the spoken e-mail addresses ("иван точка петров
собака пример точка ком" came out as `ivan.petrov@primer.com`; `dvolkov
собака gmail точка com` as `dvolkov.sobaka@gmail.com`) and two person spans.
Other real fixes of Whisper's mistakes that the metric does not count: "Роттендам"
-> "Роттердам", "кубернетис" -> "Kubernetes", "если я с вами ищу лекарства" ->
"если я совмещаю лекарства", "То он должен" -> "Оно должно".

Deviations (expected / actual, severity):

- **Invented content.** `m_trade_house`: spoken "на адрес Marina Kuznetsova" (a
  name); X wrote `marina.kuznecova@mail.ru`, an address that was never spoken.
  The domain was also wrong at both seeds: `info@sobakatrade-house.ru` and
  `info@sabakotrade-house.ru` instead of `info@trade-house.ru` (the word
  "собака" glued into the domain). Severity: refuses nothing, adds a fabricated
  sensitive-looking span; safe for sanitization (more to mask), wrong for
  restoration and for the answer's meaning.
- **Changed meaning.** `n_short_translate` (seed 4243): Whisper right ("Переведи
  на английский слово яблоко."), X wrote `Translate the word "apple" into
  English.` Severity: one real new failure, and it violates "do not translate".
- **Damaged correct text.** `t_mother_medication`: "Мама принимает" -> "Мама
  принимают" (both seeds). `q_accountant`: Whisper's "Кенешма" (spoken Кинешма)
  became "Кин-Черма" / "Кин-Чермэнь", further from the truth (both lost by the
  metric). Severity: only noise in the metric, but it shows Gemma guesses a
  place name instead of leaving it.
- **Digits not fixed.** `id_two_people_phone`: spoken 8 912 345 67 89; Whisper
  "607 89", X "60 78 9"; both wrong, so the phone span stays lost. Severity:
  Gemma does not repair digits from the recording.
- **Silence hallucination not removed.** All four silence and noise controls
  (two seeds) stay "Продолжение следует..." in X and in Z, although X hears
  silence. Severity: the guard against Whisper's invented text must be
  elsewhere (VAD, `no_speech` probability, a length-of-audio check).
- **Metric artifact.** `id_email` counts as an audio failure for X at both seeds
  (WER 0.70) because the output is the canonical address and the reference
  spells "точка/собака". The output is semantically right. Failures 5 of 88 are
  therefore: `id_email` x2 (format artifact), `m_short_call` x2 (Whisper's
  transliteration, unchanged), `n_short_translate` x1 (real); X no longer
  fails `m_trade_house`.

Reading: the recording lets Gemma restore spoken e-mail addresses, which is
Whisper's weakest span type, at 0.5 s per call, and the control shows the gain is
audio-driven. It also lets Gemma rewrite: it fabricated one address and changed
one sentence in 88 generations, and "fix only what is evidently wrong" did not
stop it. The evidence is thin (about 2 distinct fixes). Untested levers: a
stricter instruction, a rule that rejects outputs whose word count or tokens
drift from the Whisper text beyond e-mail normalization, and a q8 Gemma.

## Temperature sweep (2026-10-19, run by the agent on the owner's request)

The run above used the production transcription temperature 0.618. The same
184 generations were repeated at 0, 0.1, 0.2, 0.8, 0.9, and 1 (`run
--temperature T`, one output directory each; `compare` builds the table). At
temperature 0 the seed has no effect, so the two seeds are one generation twice.
"Invented address" counts outputs with more `@` than the source has markers
(`собак`, `sobak`, `@`); "rewritten" counts outputs whose WER against the Whisper
text exceeds 0.3 (it includes the spoken-address to `a@b.c` conversions).

| temperature | variant | failures | fidelity | fixed | broken | invented address | rewritten | clean controls |
|---|---|---|---|---|---|---|---|---|
| 0 | X | 6 | 0.896 | 4 | 0 | 2 | 6 | 0/4 |
| 0.1 | X | 6 | 0.896 | 4 | 0 | 2 | 6 | 0/4 |
| 0.2 | X | 5 | 0.896 | 4 | 0 | 2 | 5 | 0/4 |
| 0.618 | X | 5 | 0.896 | 4 | 0 | 2 | 5 | 0/4 |
| 0.8 | X | 5 | 0.896 | 4 | 0 | 2 | 5 | 0/4 |
| 0.9 | X | 6 | 0.885 | 3 | 0 | 2 | 5 | 0/4 |
| 1 | X | 5 | 0.896 | 4 | 0 | 2 | 5 | 0/4 |
| any of the six | Z | 4 | 0.854 | 0 | 0 | 0 | 6 | 0/4 |

Reading:

- **Temperature is not the lever.** Fidelity and fixed spans are the same from 0
  to 1 except one lost span at 0.9; Z (text only) is identical at every
  temperature.
- **The harmful rewrites are not sampling noise.** At 0 and 0.1 the translation
  of `n_short_translate` ("Переведи на английский слово яблоко." becomes
  `Translate the word "apple" into English.`) happens at both seeds, so it is
  greedy behavior: it is the 6th failure at 0 and 0.1. From 0.2 up only seed 4243
  does it. `marina.kuznecova@mail.ru` is invented at every temperature (the
  second address after `info@...trade-house.ru`); the domain of the first address
  differs by seed (`sobakatrade-house`, `akatrade-house`, `kohouse`), never
  correct.
- **High temperature adds noise, not fixes:** at 0.8 and above mixed alphabets
  appear (`marina.kuzneцова@mail.ru`), at 1 a truncated address
  (`marina.kuznecova@.`), and at 0.9 `m_trade_house` becomes a failure at seed 4243.
- **Controls:** the silence and noise controls stay "Продолжение следует..."
  at every temperature, for X and Z.

Consequence: lowering the temperature does not remove the two harmful behaviors;
a stricter instruction or a mechanical filter (reject outputs that add
addresses or change language) is what remains to test.
