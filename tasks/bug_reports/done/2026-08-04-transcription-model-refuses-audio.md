# Transcription: model refuses instead of transcribing (framing-dependent)

**Detected at commit:** 9248a9f (task-v1.8.0-19 merged into main).
**Component:** `src/jarvis/journal/transcription.py` (historical transcription
service), model `gemma4:12b-it-qat` via local Ollama.
**Status:** Resolved (owner-run, 2026-08-04). The English verbatim framing
default produced a real transcript instead of a refusal; see "Resolved" at
the end of this report. The refusal-detection gap listed under "Future
considerations" is a separate concern and was never part of this symptom.

## Symptoms

Running the manual handoff against real recorded voice audio:

```
python -m manual.manual_check_transcription_service --latest
python -m manual.manual_check_transcription_service --session <id> --position 0
```

The service completes with `outcome=transcribed` and writes a GENERATED
overlay, but the "transcript" is not a transcript - it is a refusal:

- "Пожалуйста, предоставьте аудиофайл или ссылку на него, чтобы я мог
  выполнить вашу просьбу."
- "К сожалению, я не могу прослушивать или обрабатывать аудиофайлы напрямую.
  Я работаю только с текстовыми сообщениями и изображениями."

The plumbing works end to end (media resolved, `images` attached, options and
model reported, overlay written and read back). The defect is that the model
does not transcribe: it answers as if there were no audio.

## Suspected cause

The refusal wording is exactly what `manual_check_audio_comprehension.py`
documents as the model's response to digital silence / "nothing in the audio",
i.e. the audio pathway was not engaged for this request framing - not that the
transport is broken.

The audio transport itself is fine: `manual_check_audio_comprehension.py` sends
the same journal wavs through the same `OllamaBackend.build_payload` +
`images` path (full generation options, `think: false`) and the model answers
the spoken content substantively. So audio reaches the model with the app's
framing.

The difference is the instruction framing on a bare single-user-turn request:

| path | system msg | user content | options | result |
| --- | --- | --- | --- | --- |
| day-0 fidelity (PROJECT.md) | none | EN "Transcribe this recording verbatim, word for word..." | num_ctx only | verbatim transcript |
| audio comprehension check | yes | RU voice placeholder | full + think:false | answers content |
| task-19 default (this bug) | none | RU "Расшифруй ... этой аудиозаписи ..." | full + think:false | refusal ("no audio") |

The only combination that produced verbatim transcription is the day-0
English wording. A plain Russian "transcribe this audio recording" instruction
triggers the instruction-tuned refusal persona. This is consistent with
PROJECT.md's later note (owner, 2026-07-25) that the model tokenizes audio
directly and does not have a clean transcribe-on-command mode; whether it
transcribes vs refuses is framing-sensitive.

## Temporary decision

Change the default `DEFAULT_TRANSCRIPTION_INSTRUCTION` to the exact English
wording day-0 verified for verbatim transcription, and keep the instruction
configurable. Add a `--instruction` override to the manual check so the exact
framing can be tuned against the live model without a code change.

Chosen over the nearby alternatives because:

- it is the single change most directly backed by a recorded verified fact
  (day-0), rather than an untested new prompt;
- restructuring the request to mirror the comprehension path (add a system
  prompt + voice-placeholder user turn) is a larger, unverified change and
  couples transcription to dialog framing; deferred until the simple wording
  fix is live-tested;
- it does not touch the transport, options, or `think` handling, none of which
  are implicated (comprehension works with them).

**Resolved (owner-run, 2026-08-04).** With the English verbatim default the
manual handoff (`--latest`, session `20260803-225905-3aec72` #2,
`gemma4:12b-it-qat`, `think: false`, full generation options) returned an
actual verbatim Russian transcript instead of a refusal. The framing wording
was the whole cause; transport, options, and `think` were never implicated.

## Future considerations / boundaries

- If the English verbatim wording still refuses or transcribes unreliably,
  the next step is to reproduce the comprehension path's framing (system
  prompt establishing an audio-transcription role + the audio on a
  short-content user turn) and measure it. That belongs in this service's
  request construction, behind the same configurable seam.
- A refusal is currently recorded as a successful `TRANSCRIBED` overlay
  because the service cannot tell a refusal sentence from a real transcript.
  Detecting/quarantining refusals (or a confidence/quality gate) is out of
  scope here and should be considered when transcript quality feeds retrieval
  (task-v1.8.0-20 and the retrieval-quality regression, task-v1.8.0-26).
- Do not treat the "audio via images" transport as suspect on the strength of
  this bug; it is verified working. The open question is prompt framing and
  this model's transcription reliability, not transport.
