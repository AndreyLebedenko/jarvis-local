# Task: Add configurable short-audio padding

**Status:** Completed.

## Summary

Production VAD chunks shorter than the configured minimum submitted duration
should be padded before WAV encoding. The padding level should be configurable
as a low deterministic white-noise RMS floor. The default production candidate
comes from the closed audio level/padding study: 3.0 s minimum duration and
0.002 RMS padding noise.

## Boundary

This task changes the production microphone/VAD audio path and configuration
surface only. It does not add peak/RMS/LUFS normalization, AGC, DC-offset
removal, filtering, prompt changes, request-shape changes, or attachment-audio
behavior.

## Acceptance criteria

1. `[vad].min_chunk_seconds` and `[vad].padding_noise_rms` are parsed, saved
   through the Status Console settings layer, exposed to the settings UI, and
   documented in `config.example.toml`.
2. Defaults are `min_chunk_seconds = 3.0` and `padding_noise_rms = 0.002`.
3. VAD chunks shorter than `min_chunk_seconds` are padded symmetrically before
   `samples_to_wav_bytes()`.
4. Padding is deterministic white noise when `padding_noise_rms > 0.0` and
   silence when it is `0.0`; speech samples are not gain-normalized or altered.
5. VAD `start_seconds` and `end_seconds` continue to report the speech segment
   boundaries, not the padded WAV duration.
6. Pure automated tests cover config parsing/saving, UI payload shape,
   validation, audio padding behavior, and VAD chunk WAV duration without live
   microphone, speakers, GPU, or Ollama.

## Owner validation

The owner completed end-to-end live checks on 2026-09-04 and reported that
`min_chunk_seconds = 3.0` with `padding_noise_rms = 0.001` is a practically
ideal combination for short voice messages on the current setup. The shipped
defaults remain the fixture-study candidate (`3.0` / `0.002`), but the lower
noise value is a useful first tuning hint if short utterances still need
adjustment.
