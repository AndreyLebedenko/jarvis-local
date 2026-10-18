# Spike v2.1.0-4: constrained JSON with a speech-present flag

Status: In progress. Rule frozen 2026-10-19, before any run.

Parent story: `tasks/story-v2.1.0-personal-proxy.md`. Follows
`tasks/spike-v2.1.0-3-json-transcription.md`: a constrained JSON with one field
`raw_transcript` cut audio failures from 22 to 16 of 88 and the median WER from
0.165 to 0.111, but it left the model no way to say that there is no speech, and
on silence, noise, and no media it invented a transcript in all 6 control
generations.

## Question

If the JSON also carries a boolean `speech_present`, does the model (a) keep the
gain of spike 3 on real utterances and (b) report no speech, with an empty
transcript, on the controls?

## Variants

- **A (current):** the effective instruction of the main run, plain output:
  `Transcribe this recording verbatim, word for word. Do not correct, complete, translate, or interpret anything. Output only the spoken text.`
- **D (constrained JSON, two fields):** the same instruction, byte for byte, and
  the same request in every other respect, plus Ollama's `format` set to
  `{"type": "object", "properties": {"speech_present": {"type": "boolean"}, "raw_transcript": {"type": "string"}}, "required": ["speech_present", "raw_transcript"]}`.
  `speech_present` comes first, so the flag is decided before the transcript.

The instruction does not mention JSON or either field (owner's specification:
the instruction is as in A). Ollama turns `format` into constrained decoding;
the model does not see the schema, only the key names that it is forced to
emit. So `speech_present` is judged from its name alone. A prompt that names
and explains the fields is a separate, untested variant.

## Inputs

The same 44 recordings (`personal_proxy_corpus_wavs/`), 3 controls (digital
silence, low-level noise, no media at all), and 2 seeds as the earlier spikes.
Variant A is run again in the same session. Before every call an unrecorded
one-token request resets Ollama's prompt cache; one unrecorded warm-up call
precedes the run; variants alternate which goes first. Model, endpoint, and
options come from `config.toml` and are hashed into `run_meta.json`.

## Measurement

**Utterances** (88 generations per variant): same as spikes 2 and 3. Reference
text is the corpus script with the `id_birth_date` correction
(`KNOWN_RECORDING_DEVIATIONS` in `manual/personal_proxy/transcription_ab.py`);
**audio failure** is a refusal-pattern match or word error rate above 0.5. For D
two more things count as an audio failure: output that is not exactly one JSON
object with a boolean `speech_present` and a string `raw_transcript` (counted
also as invalid, WER 1.0), and `speech_present` equal to `false` on a real
utterance (the transcript is still scored, so the WER is reported).
**Median WER** over the 88.

**Controls** (6 generations per variant: 3 controls x 2 seeds): speech must not
be reported. A control generation is **clean** when
- for D: the output is a valid object with `speech_present` false and a
  `raw_transcript` that is empty after stripping whitespace;
- for A: the output is empty after stripping, or matches the audio-refusal
  patterns of `manual/personal_proxy/scoring.py` (`matches_audio_refusal`: the
  model says it cannot hear or process audio, or asks for the audio). Any other
  text is an invented transcript.

Reported only, never part of the rule: valid-output share of D, the failing
generations with expected and actual text, the paired table, median seconds per
variant, how many A transcripts are byte-identical to the main run's, every
control output, and whether D reaches the 10% level (8 or fewer failures of 88).

## Decision rule (frozen)

Let `fA` and `fD` be the audio-failure counts out of 88 and `wA`, `wD` the
median WERs.

**Utterance verdict** (identical to spike 3):
- *Candidate better:* `fD <= fA - 4` and `wD <= wA + 0.02`.
- *Candidate worse:* `fD >= fA + 4`.
- *Owner decides:* `fD <= fA - 4` but `wD > wA + 0.02`.
- *No difference:* everything else.

**Control criterion** (separate, applies to D): passes only if all 6 control
generations are clean; any invented transcript or invalid output fails it. With
6 generations there is no room for a tolerance.

**Overall:**
- *Advance:* utterance verdict is *candidate better* and the control criterion
  passes.
- *Do not advance:* utterance verdict is *candidate worse*, or the control
  criterion fails.
- *Owner decides:* everything else (no difference, or the owner-decides
  utterance verdict, with the control criterion passing).

The thresholds are the agent's choice under the owner's delegation, not
statistics. A fresh sampling difference exists: spike 3 saw 77 of 88 variant-A
transcripts identical to the main run, spike 2 saw 88 of 88.

## Honest limits

- One model, one speaker, one room; the two seeds repeat the same audio. Three
  controls, six generations: the control criterion is a smoke test.
- The model is not told what `speech_present` means. A pass is evidence about
  the behaviour of this schema with this instruction, not about a better prompt.
- The script-based WER counts a correct transliteration ("Майкл Браун" for
  "Michael Brown") as an error, for every variant alike.
- A win says the format helps transcription in isolation, not that it is safe in
  the final chain.
- Not tested: instruction text that names the fields, other schemas, or the
  combined sanitization arms.

## Run

Authorized by the owner in chat on 2026-10-19 to be run by the agent (the
Testing protocol's default is a human-run handoff for live Ollama; this card
records the exception, as in spikes 2 and 3). No microphone or hotkeys are
involved.

```
python -m manual.manual_check_transcription_prompt --out manual_check_transcription_speech_out run --candidate d --wavs personal_proxy_corpus_wavs
python -m manual.manual_check_transcription_prompt --out manual_check_transcription_speech_out score --wavs personal_proxy_corpus_wavs
```

## Result (2026-10-19, run by the agent, 188 generations, no errors, GPU share 1.0)

Overall by the frozen rule: **do not advance**.

- Utterance verdict: **no difference** (22 audio failures for A, 25 for D; the
  threshold was a difference of 4).
- Control criterion: **fail**. D was clean on 0 of 6 control generations; A on
  3 of 6.

| | A (current) | D (JSON, two fields) |
|---|---|---|
| audio failures of 88 | 22 | 25 |
| median WER | 0.165 | 0.101 |
| invalid JSON | 0 | 1 |
| median seconds per call | 0.73 | 1.43 |

- Paired: failed in A only 9, in D only 12, in both 13. Neither reaches the 10%
  level. Determinism: 77 of 88 variant-A transcripts are byte-identical to the
  main run's baseline.
- **The flag does not discriminate.** On the 87 valid utterance outputs
  `speech_present` was `false` for 13, all of them at seed 19210 and none at
  seed 4243. Twelve of those 13 have a good transcript (for example
  `id_phone_digits` WER 0.00, `n_git_long` 0.02, `t_hypertension_long` 0.02,
  `q_pathologist_long` 0.04); they are counted as failures only because the flag
  says there is no speech. On the controls `speech_present` was `true` in all 5
  valid outputs (the sixth, `ctl_silence` s19210, is invalid JSON whose
  `speech_present` is also `true`), with invented text each time, for example
  "Yeah, I'm thinking about going to a concert" for no media at all and "I think
  it's a good idea to go out and get some food" for digital silence.
  `ctl_noise` s4243 wrote "The recording is silent." with the flag `true`.
- **Exploratory, not part of the frozen rule:** if the flag is ignored, D has 12
  failures by the main-run definition plus 1 invalid output, against 22 for A
  and 16 for C (spike 3). The transcript field alone carries the gain of the
  constraint; the flag adds nothing and costs 12 false failures.
- What D still fails with a bad transcript: `id_card` s4243, `id_phone_words`
  s19210, `id_sms_code` s4243, `m_short_call` s4243 (an invented English
  paragraph) and s19210 (transliteration artifact), `m_short_english` s4243,
  `m_trade_house` both seeds (invented monologues; one is invalid JSON),
  `n_borscht` both seeds (an answer at s4243; the instruction echoed back at
  s19210), `n_cpu_cache` s19210 (an answer), `n_short_translate` both seeds.
- Cost: median call time 1.43 s against 0.73 s.

Reading: the model, which is shown the key names only through its own forced
output, does not use `speech_present` as the instruction intended. The flag
tracks the seed rather than the audio. The constraint alone is the useful part
(spike 3). Whether a prompt that names and explains the fields would make the
flag meaningful is untested. The control criterion is a smoke test of six
generations; the production capture feeds the model only chunks that the voice
activity detector accepted, so silence normally never reaches it (an inference
from the architecture, not measured here).
