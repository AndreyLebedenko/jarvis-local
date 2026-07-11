# Task: Recreate microphone stream after sleep/wake

**Bug report:** `tasks/bug_reports/microphone-wake-portaudio-restart-failure.md`
**Status:** Completed.

## Decision

After a combined microphone pause, the current `InputStream` is closed with
its context manager. When capture resumes, `AudioInput` creates a fresh stream
through the existing `StreamFactory`; it never calls `start()` on the paused
stream again.

## Scope

- Preserve the existing user-sleep and auto-pause state machine.
- Preserve the buffer invalidation boundary across every pause/resume.
- Recreate the stream for every resume path, including user wake and automatic
  speech-pause resume.
- Add pure tests proving that wake uses a new stream and does not restart the
  old object.

Out of scope:

- Retry/backoff for a newly created stream that fails to open.
- PortAudio device selection, VAD, hotkeys, sound cues, and echo cancellation.
- Live microphone verification; the MME reproduction remains human-run.

## Acceptance Criteria

- [x] The old stream is closed after pause and is never started again.
- [x] A resume obtains a fresh stream from `StreamFactory`.
- [x] Pause-spanning reads and buffered audio are still discarded.
- [x] The microphone loop remains alive through a normal sleep/wake cycle.
- [x] Pure tests pass; human MME verification is complete.

## Verification

- Automated: `python -m pytest tests/test_audio_in.py`.
- Human: run `python main.py`, toggle microphone sleep, wait for the sleep
  cue to finish, wake the microphone, and speak a request. Repeat the cycle
  and confirm that requests continue to produce responses without the
  PortAudio MME restart error.

## Outcome

Human verification confirmed repeated sleep/wake cycles continue to capture
and answer requests on the affected Windows MME device without the PortAudio
restart error.
