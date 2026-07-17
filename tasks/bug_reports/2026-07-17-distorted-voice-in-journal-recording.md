# Distorted voice in a journaled utterance recording

**Detected at commit:** 1539c2abf5388c11a4482f7a583a2a17a67d2e9b
(task-journal-06 human-run handoff, 2026-07-17, uncommitted working tree
on branch `task-journal-06-live-feed-and-playback`)

## Symptoms

During the live end-to-end check of the Journal view, one of four voice
turns (`utterance-20260717-223230-0004.wav`, session
`20260717-222941-402ff9`) played back heavily distorted - "some kind of
interference, the voice was strongly distorted" per the tester. The
other three utterances in the same session played back clean. The model
still answered the turn normally.

## Suspected current cause

Unknown; not reproduced. The journal records the exact bytes that go to
the model (task-journal-02 taps the same wav chunk published by
audio_in), so the distortion almost certainly happened at capture time,
not in journal storage or playback:

- the three sibling files recorded moments apart through the identical
  path are clean, ruling out a systematic format/serving bug;
- candidate capture-side causes: another application grabbing or
  reconfiguring the microphone, a Windows audio enhancement kicking in,
  CPU/GPU contention while Ollama was answering the previous turn, or
  genuine acoustic interference at the microphone.

Notably, this is the first time a capture artifact was observable at
all - hearing exactly what the model received is the debugging purpose
the journal playback was built for, and it worked.

## Temporary decision

No code change. Keep the wav as recorded (the journal stores the audio
the model actually received; "fixing" or re-filtering stored audio
would corrupt the record - story-v1.5.0 boundary). Chosen over the
nearby alternatives:

- adding capture-side filtering/AGC now would be a blind fix for an
  unreproduced, once-in-four event and could degrade normal captures;
- discarding/re-recording the turn is impossible by design - the log is
  append-only and the moment is gone.

## Future considerations and boundaries

- If distorted captures recur, compare the affected wav's waveform
  (clipping? dropouts? resampling artifacts?) against a clean sibling -
  the journal now preserves the evidence needed for that.
- Check whether occurrences correlate with concurrent TTS/sound-cue
  playback or model inference load (shared audio device or CPU
  starvation of the capture stream).
- Any capture-path change belongs to the audio_in/VAD area, not to the
  journal stack; journal playback fidelity is explicitly out of
  suspicion here (bit-identical serving verified by design in
  task-journal-04).
