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

## Result

Pending.
