# Microphone capture is very quiet, and the device could not be changed

**Status:** Resolved 2026-07-22. Symptom 2 was a CSS defect, fixed in the
same change with a regression test. Symptom 1 was the wrong input device
and was resolved by the human selecting the correct one once the selector
became reachable; capture and settings were both confirmed working. The
observability gap under "Future considerations" stays open and still
needs an owner decision.

**Detected at commit:** `1049bf7` (branch `codex/v1.6.4-docs-and-close`,
during the combined v1.6.3 + v1.6.4 verification run, 2026-07-22).

## Symptoms visible to the user

Reported as two separate problems. They turned out to be one problem and
its blocked remedy.

1. "Jarvis does not receive sound from the microphone." Jarvis answers,
   but as if it had not heard the request.
2. "I cannot find the microphone selection setting."

## What the evidence actually says

The engine did receive audio. The session log records two accepted turns:

```
22:49:23 [LLM] Model request: inputs=audio count=1 audio_duration=1.0s
22:49:42 [LLM] Model request: inputs=audio count=1 audio_duration=1.6s
```

Both reached Ollama and both produced spoken answers, so capture, VAD,
and the request path all worked. The problem is the level. Measured from
the journal's own recordings for that session
(`journal/20260722-224923-f854b4/`):

| file | duration | peak | RMS |
| --- | --- | --- | --- |
| `utterance-...-0001.wav` | 1.00 s | -26.8 dBFS | 0.0047 (~-46 dBFS) |
| `utterance-...-0002.wav` | 1.60 s | -19.5 dBFS | 0.0113 (~-39 dBFS) |

Speech recorded at a normal working level sits far above this. At this
level the model receives a faint signal and answers as though it
misheard - which is exactly what the user saw.

The short durations are a consequence, not a second fault: VAD only
crosses its threshold on the loudest fragments of a quiet signal, so a
several-second request is clipped down to the one second that was loud
enough.

`[microphone].device` is `""` in both `config.toml` and `config.ui.toml`,
so Jarvis is using whatever Windows currently has as the default input
device. It has never been chosen deliberately.

## Suspected cause

The Windows default input device is not the microphone the user is
speaking into, or is one with very low input gain (a laptop array or
webcam microphone rather than a headset). This is a configuration and
hardware-level condition, not an engine defect - the engine faithfully
captured, segmented, and transmitted what the device gave it.

## Symptom 2 - the cause, and it is fixed

Symptom 2 is not a separate inconvenience. It is why symptom 1 could not
be self-diagnosed: the obvious remedy, choosing a different input device,
was unreachable in the UI.

`.config-panel` carried `align-self: center` from the pre-v1.6.3 layout,
where the panel was an inline form inside `.main` - a column flex, so the
cross axis was horizontal and the declaration meant "center it
horizontally". Task v1.6.3-2 moved the panel into `.settings`, a row
flex, where the identical, untouched declaration silently changed meaning
to "center it vertically" and overrode the container's `align-items:
flex-start`.

A flex item centered on the axis it overflows spills past the container's
start edge into space no scrollbar can reach. On any window shorter than
roughly 720 px of client height, the top of the Settings form - Model and
Microphone, the first two fields - was cut off with no way to scroll back
to it. Measured before the fix at a 620 px viewport: 23 px unreachable
above the container, growing as the window shrinks.

**Fixed in this change** by removing the declaration; horizontal
centering already comes from the container's `justify-content: center`.
Regression test:
`tests/test_ui_qa.py::test_the_settings_form_is_not_centered_on_the_axis_it_overflows`.

The v1.6.3 review would not have caught this, and the checklist as
written would not either: the console window is created at 960x900, and
at 900 px the form fits exactly, so nothing is clipped. It only appears
on a shorter client area - a smaller window, or display scaling that
shrinks the CSS viewport. This is a checklist gap as much as a CSS bug.

## Temporary decision

Symptom 1 is left unfixed and reported rather than chased, because the
evidence points outside the code: the engine's behavior is correct for
the signal it was given. The correct next step is for the human to pick
the right input device now that the selector is reachable, and to confirm
whether the level rises.

This was chosen over the nearby alternatives:

- **Adding automatic gain or normalization to the capture path** would
  hide the real condition, raise noise along with speech, and change what
  the journal stores as a bit-identical near-log recording (v1.7.0 relies
  on that fidelity). Not a fix for a wrong device.
- **Lowering the VAD threshold** would treat the symptom - the short
  segments - while leaving the faint signal reaching the model unchanged,
  and would make false triggers more likely for every correctly
  configured user.
- **Defaulting `[microphone].device` to something other than the system
  default** would be guessing on the user's behalf, and the system
  default is the right default.

## Future considerations and boundaries

- **The system log cannot answer "which microphone, and how loud".** This
  is a real observability gap and it belongs to story v1.6.4's subject
  matter: the whole diagnosis above had to be reconstructed from journal
  wav files, because the log records neither the opened device name nor
  any capture level. A device-name line at startup and a periodic or
  per-utterance level figure would have made this a one-look diagnosis.
  Both are candidates for a follow-up card, and both need an owner
  decision first: a device name is payload-adjacent under the story's
  content rule, and a level figure is a new log call site that
  task-v1.6.4-1's boundary deliberately excluded. **Do not add either
  without that decision.**
- **The verification checklist needs a short-window case.** Section B item
  4 checks Status for a scrollbar at the default size; nothing checks any
  tab below the default. Add a pass at a deliberately short client height
  to sections B-D.
- Related existing reports, none of which explain this one but which
  share the microphone surface:
  `2026-07-18-microphone-post-mute-first-capture-degraded.md`,
  `stale-audio-buffer-replay-after-mic-stall.md`,
  `2026-07-17-distorted-voice-in-journal-recording.md`.
- Out of scope here: whether gemma4's transcription quality degrades
  gracefully or sharply with input level. That is a model-behavior
  question, not a capture-path one.
