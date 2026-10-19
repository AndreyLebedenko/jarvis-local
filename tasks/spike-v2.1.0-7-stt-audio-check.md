# Spike v2.1.0-7: Gemma checks a Whisper transcript against the recording

Status: In progress. Rule frozen 2026-10-19, before any run.

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

- One speaker, one room, 44 utterances, invented identities. The corpus has 96
  labeled spans per pass (192 over two seeds), so one span is about 0.005 of
  fidelity and the 0.03 gain is about 6 spans.
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
