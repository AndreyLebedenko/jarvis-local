# Task: Compare short-audio level and padding interventions

**Status:** Completed.

## Summary

Extend the existing human-run audio request-shape harness so the same fixture
samples can be measured raw, safely peak-amplified, padded with leading and
trailing silence, or both. The study isolates whether low signal level and
sub-2.5-second duration contribute to the short Gemma 4 audio failures.

## Boundary

This is a harness-only causal study. It records signal statistics and prepares
variant media bytes for live Ollama runs. It does not change production
microphone capture, VAD, journal WAV encoding, or request composition.

## Acceptance criteria

1. The default harness run preserves current raw audio bytes and behavior.
2. `--peak-target 0.89` amplifies decoded samples up to the requested peak
   without clipping and records the applied gain.
3. `--min-duration-seconds 2.5` pads shorter clips with symmetric silence and
   records the added leading and trailing duration.
4. JSONL metadata records source and encoded peak, RMS, DC offset, requested
   peak target, applied gain, padding, duration, hashes, and payload media
   hashes.
5. Pure automated tests verify raw byte preservation, gain, padding, metadata,
   and the injected live gateway path without calling Ollama.
6. A human runs the raw, gain-only, padding-only, and gain-plus-padding
   conditions against the same model digests and Ollama version before any
   production conclusion is drawn.

## Human-run results

The owner authorized live Ollama test-script execution on 2026-09-04. An
initial four-process run was contaminated by concurrent requests against the
same live Ollama endpoint and is not primary evidence. Those artifacts use the
`results-level-*.jsonl` names without the `sequential` marker and must not be
used for causal interpretation.

The corrected sequential run completed on 2026-09-04 with Ollama 0.33.3. The
four primary artifacts are:

- `manual_check_audio_request_shape_out/results-level-sequential-raw-20260904T000000Z.jsonl`,
  SHA-256
  `73921ae0ad17078556453cc71d9ffa1ad63a36b11f9b093b332b2c526c16aa37`.
- `manual_check_audio_request_shape_out/results-level-sequential-peak089-20260904T000000Z.jsonl`,
  SHA-256
  `c45ccb19fa3a7aa5d036fed7222493acdc5acff5cb3035b6e5e2077462c3c22c`.
- `manual_check_audio_request_shape_out/results-level-sequential-pad25-20260904T000000Z.jsonl`,
  SHA-256
  `38681fe2896bdd036660e1055635fbdb4315be4b6a1f55b31fc3e461e7933b8a`.
- `manual_check_audio_request_shape_out/results-level-sequential-peak089-pad25-20260904T000000Z.jsonl`,
  SHA-256
  `cec7321eca20d07ce2f372cd4edec0634a44d83e35203f7c89dd1e34e161e8e3`.

Each primary artifact has 1 metadata record, 126 trial records, and 1 summary
record. Using the same operational WER <= 0.10 "usable" boundary as the
request-shape study, across audio-bearing scored trials:

| variant | all exact | all usable | short exact | short usable | longer exact | longer usable |
|---|---:|---:|---:|---:|---:|---:|
| raw | 44/90 | 56/90 | 6/36 | 6/36 | 38/54 | 50/54 |
| peak 0.89 | 47/90 | 56/90 | 7/36 | 7/36 | 40/54 | 49/54 |
| pad 2.5 s | 56/90 | 68/90 | 18/36 | 18/36 | 38/54 | 50/54 |
| peak 0.89 + pad 2.5 s | 58/90 | 67/90 | 18/36 | 18/36 | 40/54 | 49/54 |

The short fixtures' raw signal levels were materially different but neither was
near full scale: `short_1_1s` peak 0.2368, RMS 0.0327, DC offset 0.000222;
`short_1_3s` peak 0.6244, RMS 0.1234, DC offset 0.000028.

Temporary interpretation: in this fixture set, padding short clips to 2.5 s is
the stronger candidate intervention. Peak amplification to 0.89 alone barely
changed short-clip usability and did not improve the aggregate usable count.
The combined variant did not beat padding alone on short clips. This supports a
duration/boundary hypothesis more than a simple quiet-audio hypothesis, but it
still does not justify production behavior without a task-carded production
design choice and focused acceptance tests.

### White-noise padding follow-up

The harness was extended with explicit `--padding-mode white-noise` and
`--padding-noise-rms`; the default remains silence. White-noise padding is
deterministic from fixture bytes and padding parameters so result media hashes
are reproducible.

The owner authorized a sequential live follow-up on 2026-09-04. The two primary
artifacts are:

- `manual_check_audio_request_shape_out/results-level-sequential-pad25-noise0001-20260904T000000Z.jsonl`,
  SHA-256
  `a0683eebe10eadab64e8d0e3d966afed73691d9cf8b31cbbfd1275e7ebc4bfc8`.
- `manual_check_audio_request_shape_out/results-level-sequential-pad25-noise0002-20260904T000000Z.jsonl`,
  SHA-256
  `b6a2d9529160c4b659ea6f2fe56125ff8faf20daeeb8368e9c0d70d83774377e`.

Each artifact has 1 metadata record, 126 trial records, and 1 summary record.
Compared with silence padding:

| variant | all exact | all usable | short exact | short usable | longer exact | longer usable |
|---|---:|---:|---:|---:|---:|---:|
| pad 2.5 s silence | 56/90 | 68/90 | 18/36 | 18/36 | 38/54 | 50/54 |
| pad 2.5 s white-noise RMS 0.001 | 65/90 | 77/90 | 27/36 | 27/36 | 38/54 | 50/54 |
| pad 2.5 s white-noise RMS 0.002 | 67/90 | 79/90 | 29/36 | 29/36 | 38/54 | 50/54 |

Temporary interpretation: in this fixture set, a very low deterministic
white-noise floor in the added padding improved short-clip transcription more
than digital silence, while not changing the longer scored aggregate. RMS
0.002 beat RMS 0.001 by 2 short usable cells, but this is still one trial per
cell and not a tuned production constant.

### Temperature 0.7 follow-up

The harness was extended with `--temperature` so deterministic profile runs can
explicitly vary Ollama `options.temperature` while keeping the same seed and
payload shape. A sequential repeat of the strongest previous variant
(`--min-duration-seconds 2.5 --padding-mode white-noise --padding-noise-rms
0.002`) completed on 2026-09-04 with `--temperature 0.7`.

Artifact:

- `manual_check_audio_request_shape_out/results-level-sequential-pad25-noise0002-temp07-20260904T000000Z.jsonl`,
  SHA-256
  `325f64073526bf1a9fe179506eabe0ef0254662c66ff484805298762c39b0606`.

The artifact has 1 metadata record, 126 trial records, and 1 summary record.
Its metadata records `requested_temperature=0.7`, and the effective payload
options record `temperature=0.7`.

Compared with the same white-noise padding at temperature 0.0:

| variant | all exact | all usable | short exact | short usable | longer exact | longer usable |
|---|---:|---:|---:|---:|---:|---:|
| temp 0.0 | 67/90 | 79/90 | 29/36 | 29/36 | 38/54 | 50/54 |
| temp 0.7 | 67/90 | 80/90 | 29/36 | 29/36 | 38/54 | 51/54 |

Temporary interpretation: raising temperature to 0.7 did not change the
short-clip result for this variant. The single additional usable longer cell is
not enough to treat temperature as a production lever for this issue.

### Duration and noise-level follow-up

The owner requested three more sequential runs with temperature restored
explicitly to 0.0:

1. total duration at least 3.0 s, white-noise padding RMS 0.002;
2. total duration at least 2.5 s, white-noise padding RMS 0.003;
3. total duration at least 3.0 s, white-noise padding RMS 0.003.

Artifacts:

- `manual_check_audio_request_shape_out/results-level-sequential-pad30-noise0002-temp00-20260904T000000Z.jsonl`,
  SHA-256
  `01814a8d33fefce99b74948e2ee300de703adab37665220a3fc7a6962110ed1e`.
- `manual_check_audio_request_shape_out/results-level-sequential-pad25-noise0003-temp00-20260904T000000Z.jsonl`,
  SHA-256
  `9986d07f59aac39afb4c53b78f31b61322ee88a90d72ed95fa60454d2a8b50b5`.
- `manual_check_audio_request_shape_out/results-level-sequential-pad30-noise0003-temp00-20260904T000000Z.jsonl`,
  SHA-256
  `e71d5f264da3c46f4be4eb852063310974946014ab012e1bf06dec7b35d1a1c8`.

Each artifact has 1 metadata record, 126 trial records, and 1 summary record.
Compared with the previous 2.5 s / RMS 0.002 baseline:

| variant | all exact | all usable | short exact | short usable | longer exact | longer usable |
|---|---:|---:|---:|---:|---:|---:|
| 2.5 s, RMS 0.002 | 67/90 | 79/90 | 29/36 | 29/36 | 38/54 | 50/54 |
| 3.0 s, RMS 0.002 | 72/90 | 84/90 | 34/36 | 34/36 | 38/54 | 50/54 |
| 2.5 s, RMS 0.003 | 71/90 | 83/90 | 33/36 | 33/36 | 38/54 | 50/54 |
| 3.0 s, RMS 0.003 | 72/90 | 84/90 | 34/36 | 34/36 | 38/54 | 50/54 |

Temporary interpretation: increasing padded duration from 2.5 s to 3.0 s
helped more than increasing the white-noise RMS from 0.002 to 0.003. At 3.0 s,
RMS 0.002 and 0.003 tied on scored usability in this one-trial-per-cell matrix,
so 0.002 is the simpler lower-noise production candidate if this approach moves
to an implementation task.
