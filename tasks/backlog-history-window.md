# Backlog: Read-only history window

Status: Backlog.

## Summary

A future pop-up window showing the dialog log in real time. It should be a
read-only mirror of the voice interaction, not a replacement input surface.

This is deferred out of v1.1.

## Why deferred

The current v1.0 architecture does not have a real transcript of spoken user
utterances. `main.py` records a placeholder user turn for voice input, while
the actual user audio is sent to the model as media for the current request.

A useful history window therefore needs a prior design decision:

- add a separate local ASR/transcription path;
- ask the multimodal model to emit a transcript in a structured way;
- accept placeholder user turns in the first window version;
- or make clipboard/text input the first source of exact user text.

These choices affect latency, dependencies, prompt design, event schemas,
history semantics, and possibly model licensing. They should not be pulled
into v1.1 silently.

## Future candidate scope

- Global hotkey to show/hide the window.
- Read-only rendering of user and assistant turns.
- Assistant tokens update as streamed.
- Thinking status indication if thinking mode exists and has been verified.
- Optional always-on-top behavior.
- Must not steal focus from the active app.
- Implemented as a bus subscriber; if existing events are insufficient,
  event-schema changes belong to that story and must be reflected in
  `PROJECT.md`.

## Open questions

- What is the authoritative transcript source for spoken user utterances?
- Should clipboard input appear in the same history as voice turns?
- Should TTS be suppressible for text/clipboard turns once a history window
  exists?
- Is this a v1.2 feature after clipboard input, or a v2.0 phase with a
  larger interaction-model change?
