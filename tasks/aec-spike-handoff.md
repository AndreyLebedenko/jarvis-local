# AEC spike handoff

Task: `tasks/task-v1.7.0-1-aec-spike.md`.

This is hardware-dependent. The human runs these commands and reports the
filled result table. No new package install is required - the candidate
tried here is a pure-numpy NLMS adaptive filter (see the script's
docstring for why that is the first candidate to try).

## Round 1 result (2026-07-26): BT headphones, informational only

The first 8 runs played back through Bluetooth headphones - the normal,
everyday way Jarvis is used here. Independent analysis of the saved
far-end/near-end WAVs found near-zero cross-correlation between them in
every run (peaks in the 0.01-0.05 range, no stable lag) - the microphone
essentially did not pick up the TTS output at all through headphones.
Real finding, worth keeping: **headphone playback already looks safe
from self-hearing, with no AEC of any kind.** It does not, on its own,
test the acoustic-coupling problem PROJECT.md documents ("from the
speakers"), which desktop speakers are also available for - hence round
2.

## Round 2 result (2026-07-26): desktop speakers via MME, no-go so far

Round 2 played through desktop speakers (Windows default output switched
to them, MME host API - device 9, `Speakers (Yeti X)`). This surfaced a
real bug in the check script, since fixed: cross-correlation on the
recordings showed a consistent **+310 to +335 ms** far-end/near-end
delay across all four conditions - MME's round-trip buffering latency,
not acoustic travel time - while the NLMS filter's original 1024-tap
window only covered 64 ms, so it could not see the actual echo at all
and produced negative "suppression" (adapting to the wrong signal). The
script now estimates this delay by cross-correlation first and aligns
the filter's window to it (`estimate_delay_samples()` in
`manual/manual_check_aec_spike.py`); rerunning is not required since the
far-end/near-end WAVs from these runs were reprocessed offline with the
fix:

| Condition | Delay (ms) | Suppression (dB), taps=1024/mu=0.5 | Self-heard false positive? |
| --- | ---: | ---: | --- |
| quiet-close | 312 | 6.57 | yes |
| quiet-far | 326 | -5.21 | yes |
| reverb-close | 310 | 8.37 | yes |
| reverb-far | 335 | -11.29 | yes |

A tuning sweep (taps up to 8192, mu down to 0.1) improved suppression
somewhat (e.g. quiet-far reached -1.64 dB) but **every condition still
produced a false positive** - VAD still fired on residual self-heard
TTS regardless of tuning. As things stand, this candidate is a no-go
through MME.

**Leading suspect: MME itself, not the algorithm or the acoustic
problem.** PROJECT.md already ties MME to other latency/behavior quirks
on this project (the wake-recovery fix, the post-mute degraded-capture
finding) - "host API choice is not cosmetic on Windows." 300+ ms of
buffering latency is a lot for any adaptive filter to track cleanly, and
WASAPI is normally far lower-latency. Round 3 tests that hypothesis
before concluding the candidate itself (or acoustic AEC in general) is
the problem.

## What each run does

`manual/manual_check_aec_spike.py`:

1. Synthesizes a real ~15 s Russian TTS response through the production
   Silero engine.
2. Plays it through the given output device while recording the given
   input device at the same time (`sounddevice.playrec`), so the
   "far-end" reference is exactly the array requested for playback and
   the "near-end" recording is time-aligned to it.
3. Estimates the far-end/near-end delay by cross-correlation, then runs
   an offline NLMS echo canceller aligned to that delay.
4. Feeds the residual through the project's real Silero VAD at your
   configured `config.vad.threshold`.
5. Prints the estimated delay, suppression in dB, whether VAD fired on
   the residual (and where), and an estimate of the processing cost per
   20 ms block.
6. Saves the far-end/near-end/residual WAVs under
   `manual_check_aec_spike_out/` so you can listen back if a result looks
   wrong.

## Round 3: WASAPI instead of MME

Same physical mic and speakers, different host API. On this machine:

```
22 Speakers (Yeti X), Windows WASAPI (0 in, 2 out)
25 Microphone (Yeti X), Windows WASAPI (2 in, 0 out)
```

```powershell
python -m manual.manual_check_aec_spike --label quiet-close-wasapi --scenario silent --output-device 22 --input-device 25
python -m manual.manual_check_aec_spike --label quiet-close-wasapi --scenario interrupt --output-device 22 --input-device 25
python -m manual.manual_check_aec_spike --label quiet-far-wasapi --scenario silent --output-device 22 --input-device 25
python -m manual.manual_check_aec_spike --label quiet-far-wasapi --scenario interrupt --output-device 22 --input-device 25
python -m manual.manual_check_aec_spike --label reverb-close-wasapi --scenario silent --output-device 22 --input-device 25
python -m manual.manual_check_aec_spike --label reverb-close-wasapi --scenario interrupt --output-device 22 --input-device 25
python -m manual.manual_check_aec_spike --label reverb-far-wasapi --scenario silent --output-device 22 --input-device 25
python -m manual.manual_check_aec_spike --label reverb-far-wasapi --scenario interrupt --output-device 22 --input-device 25
```

Same conditions as round 2 (desk position for "close"/"far", room
surfaces for "quiet"/"reverb"). For `silent` runs stay quiet; for
`interrupt` runs speak over Jarvis partway through.

Watch the printed `estimated_delay_ms` first - if it drops from
~300+ ms to something in the tens of ms, that confirms MME was the
bottleneck and the default (untuned) taps=1024 filter should have a real
chance. If the delay stays large even on WASAPI, that points at
something else (e.g. this specific USB interface's own buffering) and
the candidate is more likely a genuine no-go regardless of host API.

## Result table (round 3, WASAPI)

| Condition | Delay (ms) | Suppression (dB) | Self-heard false positive? | Real interrupt detected? | Est. ms/20ms block | Notes |
| --- | ---: | ---: | --- | --- | ---: | --- |
| quiet-close-wasapi |  |  |  |  |  |  |
| quiet-far-wasapi |  |  |  |  |  |  |
| reverb-close-wasapi |  |  |  |  |  |  |
| reverb-far-wasapi |  |  |  |  |  |  |

## Go/no-go notes

Report, for round 3 (WASAPI):

- `estimated_delay_ms` for each run, compared to round 2's ~310-335 ms;
- whether any `silent` run still produces a false positive;
- whether every `interrupt` run's real interruption is detected, and
  roughly how promptly;
- the suppression dB range;
- whether `aec_estimated_ms_per_20ms_block` stays comfortably under
  20 ms.

If round 3 still comes back no-go: round 1 (headphones) stays valid
context that self-hearing is already a non-issue for that output path,
so a fallback worth considering in the story's re-plan is scoping
barge-in to headphone playback only, or trying a native AEC library
(speexdsp, WebRTC audio processing) instead of the pure-numpy candidate
- both are real dependency/packaging-cost decisions for the owner, not
something to default into silently.
