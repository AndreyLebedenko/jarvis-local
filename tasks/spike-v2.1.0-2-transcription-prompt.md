# Spike v2.1.0-2: transcription instruction wording

Status: In progress. Rule frozen 2026-10-18, before any run.

Parent story: `tasks/story-v2.1.0-personal-proxy.md`. Follows
`tasks/spike-v2.1.0-1-combined-transcribe-sanitize.md`, whose main run found
that the production transcription step (the two-step baseline) fails on
24 of 88 generations (27.3%), mostly by answering the request instead of
transcribing it, dropping the words before a number, or refusing.

## Question

Does a stronger, differently worded transcription instruction reduce those
failures without making transcription worse elsewhere?

The change touches only the text of the user message. The request shape is
otherwise identical to production: one user message, the WAV in `images`, no
system message, no `format`, reasoning off, the production generation options.

## Variants

- **A (current):** the effective instruction of the main run, i.e.
  `[generation.transcription].prompt` or `DEFAULT_TRANSCRIPTION_INSTRUCTION`:
  `Transcribe this recording verbatim, word for word. Do not correct, complete, translate, or interpret anything. Output only the spoken text.`
- **B (owner's wording, English corrected 2026-10-18):**
  `I have attached an audio recording to this message. Your only task is to transcribe it verbatim, word for word. Do not correct, complete, translate, or interpret anything. Output only the spoken text, exactly as spoken.`

B changes two things at once (the "attached recording / only task" framing and
the closing phrase). This spike cannot say which one helps; it says whether
the wording as a whole does.

## Inputs

The same 44 recordings (`personal_proxy_corpus_wavs/`) and the 3 generated
controls as the main run, at both seeds (`SEEDS` in
`manual/personal_proxy/corpus.py`). Per variant: 88 scored generations plus 6
control generations. Before every call an unrecorded one-token request resets
Ollama's prompt cache; one unrecorded warm-up call precedes the run. Variants
alternate which goes first. Model, endpoint, and options come from the same
`config.toml` as the main run and are hashed into `run_meta.json`.

## Measurement

Reference text is the corpus script, with one correction: `id_birth_date` was
spoken as the 24th of March (owner confirmed 2026-10-18), while the script says
"двадцать третьего марта ...". The reference is replaced by `Я родился 24 марта
1985 года.` in digits, because the word-error-rate normalizer converts
cardinal number words only, not ordinal dates, and the model writes dates in
digits. The correction lives in `KNOWN_RECORDING_DEVIATIONS` in
`manual/personal_proxy/transcription_ab.py` and is applied to both variants
alike. The main-run report is not rewritten; its two `id_birth_date` failures
per arm are a recording mismatch plus this normalizer gap, not a model error.

- **Audio failure:** the main-run definition (`looks_like_audio_failure`): a
  refusal-pattern match, or word error rate above 0.5 against the reference.
- **Median WER** over the 88 scored generations, normalized as in the main
  run.
- Reported only: the failing generations with reference and transcript, the
  paired table (failed in A only / B only / both), the control outputs, and
  how many variant-A transcripts are byte-identical to the main run's
  baseline transcripts for the same recording and seed (determinism check).

## Decision rule (frozen)

Let `fA` and `fB` be the audio-failure counts out of 88 and `wA`, `wB` the
median WERs.

- **B better:** `fB <= fA - 4` and `wB <= wA + 0.02`.
- **B worse:** `fB >= fA + 4`.
- **Owner decides:** `fB <= fA - 4` but `wB > wA + 0.02`.
- **No difference:** everything else.

The threshold of 4 generations and the WER margin 0.02 are the agent's choice
under the owner's delegation, not statistics: at n=88 a difference of three or
fewer failures is within what a changed seed can move. The paired table is
there so the owner can judge borderline outcomes.

## Honest limits

- One model, one speaker, one room, 44 utterances x 2 seeds; the seeds repeat
  the same audio, so 88 is not 88 independent samples.
- The script-based WER counts a correct transliteration ("Майкл Браун" for
  "Michael Brown") as an error, for both variants alike.
- A win here is a hypothesis for the production prompt, not a proof: the
  closed request-shape bug reports show that wording of the current turn can
  shift audio attention in ways a 44-utterance corpus may not show.
- Not tested: the same wording together with a constrained JSON `format`, or
  a separate wording change inside the combined arms.

## Run

Authorized by the owner in chat on 2026-10-18 to be run by the agent (the
Testing protocol's default is a human-run handoff for live Ollama; this card
records the exception). The change is a prompt text only, no microphone and
no hotkeys are involved. Commands:

```
python -m manual.manual_check_transcription_prompt --out manual_check_transcription_prompt_out run --wavs personal_proxy_corpus_wavs
python -m manual.manual_check_transcription_prompt --out manual_check_transcription_prompt_out score --wavs personal_proxy_corpus_wavs
```

## Result

Pending.
