# Story v1.2.9 Task 2: Piper engine adapter

Status: Completed.

## Summary

Introduce a production Piper adapter behind the existing `TtsEngine` protocol,
using local `.onnx` and `.onnx.json` files only.

## Boundary

In scope:

- Add a `PiperEngine` implementation of `TtsEngine`.
- Validate the configured model path and adjacent or explicit config path.
- Convert Piper chunk output into WAV bytes with a valid header.
- Keep Piper-specific imports lazy so pure config/tests do not require Piper.
- Cover path validation and WAV conversion with pure tests.

Out of scope:

- Choosing when Piper is used; routing is task 3.
- Downloading Piper models.
- Supporting Piper speaker selection beyond what the chosen model requires.
- Replacing Silero for Russian.

## Acceptance Criteria

- `PiperEngine.synthesize(text, language="en") -> bytes` returns WAV bytes.
- Empty Piper output fails with a clear exception.
- Mixed sample-rate chunk output fails with a clear exception.
- Missing model/config files fail before synthesis.
- Existing Silero tests remain green.
- No runtime network dependency is introduced.

## Notes

The spike found that `voice.synthesize(text, wav_file)` can leave the standard
library `wave` writer without a complete header in the installed Piper package.
Use the chunk API and set WAV channels, sample width, and sample rate
explicitly.
