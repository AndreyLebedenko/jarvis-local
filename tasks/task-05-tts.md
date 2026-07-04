# Task: Text-to-speech (tts.py)

Status: Not started.

Story: [story-jarvis-v1.0.md](story-jarvis-v1.0.md)

## Summary

Subscribes to the backend's streamed response tokens and speaks them as
Russian audio via Silero TTS, sentence by sentence, while generation is
still in progress. Sentence-level streaming is mandatory (PROJECT.md): buffer
tokens to a sentence boundary, synthesize, play, without waiting for the
full response. The end-to-end target (defined once in PROJECT.md's
Architecture v1.0 section and the story card) is first audio within ~3 s of
audio_in.py publishing the finished utterance (not from the literal
instant speech physically stopped - that has its own separate,
tunable cost via config.vad.request_end_pause_seconds), covering audio
prefill + first-sentence generation + TTS synthesis of that sentence.
This module owns only the synthesis-and-playback portion of that budget,
once a sentence is ready; the full end-to-end figure is verified in
task-07.

## Current boundary

In scope:

- Sentence-boundary buffering: given a stream of token fragments, emit a
  complete sentence as soon as a boundary is detected, and flush any
  trailing partial sentence when the stream ends.
- Silero TTS synthesis call per completed sentence (Russian voice).
- Playback queue that plays synthesized sentences in the correct order
  with no gaps or overlaps, even if synthesis of a later sentence finishes
  before an earlier one (if synthesis is run concurrently).

Out of scope:

- XTTS-v2 (Roadmap item 2, v1.x quality upgrade).
- Voice cloning/customization; non-Russian voices.
- SSML or prosody control beyond Silero's defaults.

## Dependencies

`bus.py` (task-01), `config.py` (task-02, for voice/rate settings),
`backend.py` (task-03, as the producer of the token stream this module
consumes).

## Acceptance criteria

Automated tests (pure logic, no speakers):

- Sentence buffer emits correct boundaries across a range of token-stream
  fixtures, including known-tricky Russian text cases (abbreviations,
  decimal numbers, ellipses) - if any of these are found to falsely trigger
  or suppress a boundary, that is a stop-and-report condition (CLAUDE.md
  0.1), not a silently accepted limitation.
- The buffer flushes a trailing partial sentence at stream end rather than
  dropping it.
- Playback queue test confirms sentences are played in original order even
  when given synthesis-ready events in a shuffled arrival order.

Manual handoff (speaker-dependent, human runs and reports):

- Exact command to run a scripted response through the full sentence
  buffer -> synthesis -> playback path; confirm audio starts promptly once
  the first sentence is ready (no unexpected synthesis/queueing delay), no
  clipped audio at sentence boundaries, and correct Russian pronunciation.
  This is a component check on this module's own slice of the budget, not
  the end-to-end target - that full-pipeline measurement happens in
  task-07.
