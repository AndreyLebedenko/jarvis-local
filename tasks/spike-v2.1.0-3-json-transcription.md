# Spike v2.1.0-3: transcription through constrained JSON

Status: In progress. Rule frozen 2026-10-18, before any run.

Parent story: `tasks/story-v2.1.0-personal-proxy.md`. Follows
`tasks/spike-v2.1.0-1-combined-transcribe-sanitize.md` (the two-step baseline
fails on 24 of 88 generations; the combined C-user arm, which asked for a
constrained JSON object, had 8) and
`tasks/spike-v2.1.0-2-transcription-prompt.md` (rewording the instruction made
it worse: 26 of 88 against 22).

## Question

Is it the constrained JSON output, rather than the instruction wording, that
keeps the model from answering the request, refusing, or dropping words, when
the only task is transcription?

## Variants

- **A (current):** the effective instruction of the main run, plain output:
  `Transcribe this recording verbatim, word for word. Do not correct, complete, translate, or interpret anything. Output only the spoken text.`
  Same request as spike 1's baseline transcription step and spike 2's variant A.
- **C (constrained JSON):** the same instruction text, byte for byte, and the
  same request in every other respect, plus Ollama's `format` set to
  `{"type": "object", "properties": {"raw_transcript": {"type": "string"}}, "required": ["raw_transcript"]}`.
  The transcript is the value of `raw_transcript`.

The instruction in C does not mention JSON (owner's specification: the prompt
is as in A). Constrained decoding forces the shape; the model is not told about
it. Spike 1 told it, so C measures the constraint alone and may under-estimate
a prompt that also names the field.

## Inputs

The same 44 recordings (`personal_proxy_corpus_wavs/`), 3 controls, and 2 seeds
as the earlier spikes. Variant A is run again in the same session (it was
byte-identical to the main run in spike 2, so this is also a determinism
check). Before every call an unrecorded one-token request resets Ollama's
prompt cache; one unrecorded warm-up call precedes the run; variants alternate
which goes first. Model, endpoint, and options come from `config.toml` and are
hashed into `run_meta.json`.

## Measurement

Same as spike 2: reference text is the corpus script with the `id_birth_date`
correction (`KNOWN_RECORDING_DEVIATIONS` in
`manual/personal_proxy/transcription_ab.py`); **audio failure** is a
refusal-pattern match or word error rate above 0.5; **median WER** over the 88
scored generations.

For C, the transcript is `raw_transcript` of a response that parses as a JSON
object with exactly that one string field. A response that does not parse, or
lacks the field, counts as an audio failure with WER 1.0 and is also reported
as invalid.

Reported only, never part of the rule: valid-output share of C, the failing
generations with expected and actual text, the paired table, median seconds
per variant, how many A transcripts are byte-identical to the main run's, the
control outputs, and whether C reaches the 10% level (8 or fewer failures of
88).

## Decision rule (frozen)

Let `fA` and `fC` be the audio-failure counts out of 88 and `wA`, `wC` the
median WERs.

- **Candidate better:** `fC <= fA - 4` and `wC <= wA + 0.02`.
- **Candidate worse:** `fC >= fA + 4`.
- **Owner decides:** `fC <= fA - 4` but `wC > wA + 0.02`.
- **No difference:** everything else.

Same thresholds as spike 2, for comparability; the agent's choice under the
owner's delegation, not statistics. The seeds are reproducible (spike 2: 88 of
88 identical), so differences are properties of the request, but 44 utterances
from one speaker remain a small sample.

## Honest limits

- One model, one speaker, one room; the two seeds repeat the same audio.
- The script-based WER counts a correct transliteration ("Майкл Браун" for
  "Michael Brown") as an error, for both variants alike.
- A win says the constraint helps transcription in isolation. It does not say
  that the constraint is safe inside the final chain (text-only sanitization
  still follows) or that it survives the production request shape changes.
- Not tested: a prompt that names the JSON field, other schemas, or the
  constraint combined with a changed instruction.

## Run

Authorized by the owner in chat on 2026-10-18 to be run by the agent (the
Testing protocol's default is a human-run handoff for live Ollama; this card
records the exception, as in spike 2). No microphone or hotkeys are involved.

```
python -m manual.manual_check_transcription_prompt --out manual_check_transcription_json_out run --candidate c --wavs personal_proxy_corpus_wavs
python -m manual.manual_check_transcription_prompt --out manual_check_transcription_json_out score --wavs personal_proxy_corpus_wavs
```

## Result (2026-10-19, run by the agent, 188 generations, no errors, GPU share 1.0, 8.5 min)

Verdict by the frozen rule: **candidate (C) better**.

| | A (current) | C (constrained JSON) |
|---|---|---|
| audio failures of 88 | 22 | 16 |
| median WER | 0.165 | 0.111 |
| invalid JSON | 0 | 0 |
| median seconds per call | 0.88 | 1.25 |

- Paired: failed in A only 7, in C only 1, in both 15. C is 6 failures better,
  the threshold was 4.
- Neither variant reaches the 10% level (8 or fewer failures of 88): C has 16.
- Determinism: 77 of 88 variant-A transcripts are byte-identical to the main
  run's baseline, not 88 of 88 as in spike 2; A still has the same 22
  failures. Some drift between sessions exists, so a 4-to-6 failure margin is
  modest.
- What C fixed (A only): `id_email` s4243 (refusal), `id_sms_code` both seeds
  (now keeps the words before the code), `m_short_english` s4243 (refusal),
  `n_training_plan` both seeds (answer instead of transcription),
  `t_divorce_court` s19210 (refusal).
- What C broke (C only): `id_short_write` s19210 returned the expected
  "Напиши Олегу Жукову." followed by the Russian translation of the
  transcription instruction itself.
- Still failing in both: `id_card` both seeds ("Политическая карта и номер ..."
  in C where the speech is "Оплати картой, номер ..."), `id_phone_words` both
  seeds (digits only, the words before them are lost), `m_short_call`
  ("Майкл Браун" for "Michael Brown", scorer artifact), `m_trade_house`
  both seeds (C invents a monologue at s4243 and refuses at s19210),
  `n_borscht` and `n_cpu_cache` both seeds (the model still answers the
  question inside `raw_transcript`), `n_short_translate` both seeds (only
  "яблоко" remains).
- Controls: A mostly refuses or comments on the missing audio. C always puts
  invented speech into `raw_transcript` for silence, noise, and no media, for
  example "Oh, I'm just going to be home tonight, so I'm going to stay in and
  just relax". The schema has no way to say "no speech", so C fabricates a
  transcript on all 6 control generations. Reported only, not part of the
  rule, but a real risk for the privacy chain (a silent recording would reach
  the sanitization step as a request).
- Cost: median call time 1.25 s against 0.88 s.

Reading: the constraint helps (fewer refusals, fewer answers in place of
transcription) but is far from solving it, and it removes the model's only
way to say that there is no speech. The 8 failures of the combined C-user arm
in spike 1 are therefore not explained by the constraint alone; the longer
prompt with the rules and the verdict field (which includes a "no speech"
branch) also contributes, which this spike does not isolate.
