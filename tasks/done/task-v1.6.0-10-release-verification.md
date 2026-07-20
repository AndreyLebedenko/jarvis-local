# Task v1.6.0-10: Release verification and documentation

**Status:** Completed.
**Story:** `tasks/done/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-1 through task-v1.6.0-9 completed and reviewed.

## Summary

Close v1.6.0 with end-to-end verification, human-run Ollama audio checks,
documentation updates, and story cleanup.

## Context you need

- Story acceptance criteria: every box must be checked or explicitly
  re-scoped by the human.
- `PROJECT.md`: record only verified facts and architectural decisions.
- README/user docs if they describe input sources or the Status Console
  Journal view.
- Testing protocol: live Ollama and hardware/media behavior checks are
  human-run handoffs, not agent-run tests.

## Boundary

- Verification and docs only. Code changes are limited to review findings
  explicitly approved during release verification.
- Do not start v1.6.1 builtin tools or v1.6.2 camera work.
- Do not claim uploaded audio behavior as verified until the human-run
  check passes against local Ollama.

## Requirements

- Run the full automated gate: `python -m ruff format --check .`,
  `python -m ruff check .`, and `python -m pytest`.
- Prepare a human-run manual check script or exact command sequence for:
  text attachment, image attachment, uploaded audio attachment, unsupported
  format, text truncation, audio chunking, and Hidden mode. The image check
  must include a real `.jpg`, not only PNG: the live-verified `images`
  precedent (screenshot path) covers PNG only, so JPEG-through-`images` is
  not yet a verified fact (agreed at task-v1.6.0-4 review, 2026-07-19).
- Update `PROJECT.md` with the final v1.6.0 architecture summary and any
  verified uploaded-audio facts.
- Update user-facing docs/screenshots if they enumerate Journal input
  capabilities.
- Update the story card status and move completed task cards to
  `tasks/done/` only after human review approves closure.

## Acceptance criteria

- [x] Automated Ruff and pytest gates are green.
- [x] Human-run uploaded-audio check passes or produces a recorded stop
      condition/bug report.
- [x] `PROJECT.md` records the final architecture and verified facts
      without weakening the locality contract.
- [x] User-facing docs mention Journal attachments and their limits.
- [x] Story acceptance criteria are all checked or explicitly re-scoped.

## Manual release handoff

All commands below are run by the human from the repository root on the
Windows 11 machine with local Ollama running. The agent must not run the live
Ollama/WebView checks.

Prepare files:

```powershell
New-Item -ItemType Directory -Force manual_check_journal_attachments_in
Set-Content -Encoding UTF8 manual_check_journal_attachments_in\notes.txt "Jarvis attachment smoke note: the release checklist token is ALPHA-160."
$long = "Jarvis text truncation line. " * 900
Set-Content -Encoding UTF8 manual_check_journal_attachments_in\long.log $long
Set-Content -Encoding UTF8 manual_check_journal_attachments_in\manual.pdf "unsupported placeholder"
Copy-Item <path-to-a-real-jpg-photo> manual_check_journal_attachments_in\photo.jpg
@'
import math
import struct
import wave
from pathlib import Path

path = Path("manual_check_journal_attachments_in/long.wav")
sample_rate = 16000
seconds = 65
with wave.open(str(path), "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(sample_rate)
    for index in range(sample_rate * seconds):
        value = int(12000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        wav.writeframesraw(struct.pack("<h", value))
'@ | python -
```

Use `audio\a1.wav` for the uploaded-audio speech check. If that fixture is not
intelligible speech on the test machine, record or choose a short spoken
`.wav`/`.mp3` and use it instead.

Launch:

```powershell
python -m jarvis --status-console --no-touchstrip
```

Checklist:

1. Open the Journal view, click New context, and confirm the input dock shows
   the Attach button, drop target, textarea, and Send button.
2. Attach `manual_check_journal_attachments_in\notes.txt`, type "What token is
   in the attached note?", send, and confirm the file row becomes accepted,
   the new journal user turn source is Attachment, the answer identifies
   `ALPHA-160`, and the accepted file row is cleared from the input dock
   after the turn is accepted.
3. Attach `manual_check_journal_attachments_in\photo.jpg`, type a concrete
   question about the visible photo content, send, and confirm the file row is
   accepted, clears from the input dock after the turn is accepted, and the
   answer describes the real JPG. This must be a real `.jpg`, not a renamed
   PNG.
4. Attach `audio\a1.wav` (or the chosen short spoken WAV/MP3), ask for a brief
   transcription/summary, send, and confirm uploaded audio reaches the model
   as audio rather than being treated as text or ignored.
5. Attach `manual_check_journal_attachments_in\manual.pdf` with no typed text,
   send, and confirm the file row is rejected with the unsupported-format
   reason and no model turn is accepted. Confirm the rejected row still has a
   remove control and can be cleared without toggling Hidden.
6. Attach `manual_check_journal_attachments_in\long.log`, ask for the first
   visible topic, send, and confirm the file row reports a warning and the
   journal/model-facing text includes the truncation marker.
7. Attach `manual_check_journal_attachments_in\long.wav`, ask "How was this
   audio attachment handled?", send, and confirm the journal user text includes
   the audio cue saying it was split into 3 clips. Do not judge speech content
   from this synthetic tone; this step verifies chunking visibility.
8. Select at least one pending file, toggle Hidden before sending, and confirm
   the pending selection is cleared. While Hidden, submission must not send
   text or files; after switching back to Open, the old pending files must not
   reappear. Also drag any local file onto the Hidden Journal window and
   confirm the WebView stays on the Status Console instead of navigating to
   `file://` content.
9. Repeat the visual pass with `[ui].language = "ru"` after restart and at a
   narrow desktop width around 720 px: controls and result rows must stay
   readable, localized, and non-overlapping.

Record the exact outcome of steps 3 and 4 before closing the story. Only if
the uploaded-audio speech check passes may `PROJECT.md` gain a verified fact
claiming live uploaded-audio behavior against local Ollama.

## Sprint verification so far

- `python -m pytest tests\test_journal_view_ui.py` -> 47 passed.
- `python -m pytest tests\test_journal_view_ui.py tests\test_journal_live_ui.py tests\test_ui_i18n.py` -> 84 passed.
- `python -m ruff format --check .` -> green.
- `python -m ruff check .` -> green.
- `python -m pytest` -> 1162 passed, 1 skipped.

Closure:

- Human-run real JPG and uploaded-speech-audio checks passed on 2026-07-20.
- Positive and negative release checks passed, including unsupported-file
  rejection, Hidden privacy behavior, document-level drop guarding, and audio
  size/duration control.
- Story and task cards were closed after human review approval.

