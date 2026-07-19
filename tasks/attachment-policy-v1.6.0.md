# Attachment policy v1.6.0

**Produced by:** `tasks/task-v1.6.0-1-attachment-policy-and-format-gate.md`.
**Referenced by:** task-v1.6.0-2 through task-v1.6.0-8 (do not restate these
numbers; link back here and update this file if a later task needs a
change, recording the reason).

This is the first-iteration policy only. Nothing here is a permanent
architectural ceiling; it is what v1.6.0 ships with, sized to the model's
verified constraints (`PROJECT.md`'s day-0 audio facts) and to the
existing text/clipboard precedent (`config.clipboard.max_chars`), not to a
theoretical maximum.

## Supported formats

| Class | Extensions | MIME types | Notes |
|---|---|---|---|
| Audio | `.wav`, `.mp3` | `audio/wav`, `audio/x-wav`, `audio/mpeg`, `audio/mp3` | See "Compressed-audio dependency decision" below. |
| Image | `.png`, `.jpg`, `.jpeg` | `image/png`, `image/jpeg` | Matches the existing screenshot path's PNG plus common camera/phone JPEG. |
| Text | `.txt`, `.md`, `.csv`, `.json`, `.log` | `text/plain`, `text/markdown`, `text/csv`, `application/json` | Must decode as UTF-8. |

Any other extension/MIME, and any MIME whose declared type disagrees with
the extension's class, is rejected as unsupported. No PDF, DOCX, archive,
or video container in this iteration (story boundary).

Detection is extension-first: the browser-supplied MIME type is a
secondary check, not authoritative (browsers are inconsistent about MIME
for `.log`/`.md`/etc). A file is accepted only if its extension is in the
table above; task-v1.6.0-2 owns the exact matching rule.

## Compressed-audio dependency decision

Empirically checked 2026-07-19 against the project's actual `.venv`
(`soundfile 0.14.0`, `torchaudio 2.8.0+cpu`, both already in
`requirements.txt` - no package installed for this check). Proof is
`tests/test_audio_decoder_formats.py`, which is part of `python -m pytest`
and runs in CI.

- **MP3: supported, no new dependency.** `soundfile.available_formats()`
  lists `MP3` - libsndfile 1.1+ bundles a native MP3 decoder/encoder.
  Verified live: encoded a synthetic tone to MP3 with `sf.write(...,
  format="MP3")` and read it back successfully through both `sf.read()`
  and `torchaudio.load()` (torchaudio's Windows backend is soundfile
  itself - `torchaudio.list_audio_backends()` returns `['soundfile']`).
- **M4A/AAC: not supported, and not planned for v1.6.0.** `MP4`/`M4A`/`AAC`
  are absent from `soundfile.available_formats()`. Verified live against a
  real AAC-in-MP4 fixture (`audio/sample.m4a`, built once with PyAV as an
  incidental authoring tool, not a project dependency - see the fixture
  note in the test file): both `sf.read()` and `torchaudio.load()` raise
  `soundfile.LibsndfileError: Format not recognised`.
  Decoding M4A would need either PyAV (bundles a full static FFmpeg build,
  tens of MB, a large new runtime dependency) or `pydub`+an external
  `ffmpeg` executable (an external-executable dependency with its own
  install/PATH story on Windows). Both hit this task's stop condition
  ("Stop if MP3/M4A support requires a large parser/runtime dependency or
  an external executable that has non-obvious install/runtime
  trade-offs"). Per this task's acceptance criteria, the decision is
  recorded as unresolved-by-design and **task-v1.6.0-5 (audio attachments)
  is blocked from implementing M4A decode** until a human explicitly
  decides to accept one of those dependencies in a future task. Until
  then, an uploaded `.m4a`/`.aac` file is rejected the same way as any
  other unsupported format (see "Unsupported/oversize handling" below) -
  clearly, not silently.
- The story card's preliminary scope listed "WAV/MP3/M4A" as illustrative
  examples, not a binding commitment; `story-v1.6.0-file-attachments.md`
  is updated alongside this note to point at this decision instead of
  restating the format list.

This is a new verified fact for `PROJECT.md`'s "Verified facts" section
(recorded there in the same change) since it is exactly the kind of
locally-verified, do-not-re-litigate capability fact that section exists
for.

## Numeric limits

### Audio

- Normalization target (unchanged from the existing mic path): 16 kHz
  mono, 16-bit PCM WAV, via the existing
  `jarvis.audio.utils.samples_to_wav_bytes` helper.
- Max clip length sent to the model: **30 s** - the verified Ollama
  per-clip ceiling (`PROJECT.md`), matching `config.vad.max_chunk_seconds`'s
  existing default for microphone chunking.
- Max raw uploaded duration per audio file: **90 s** (= 3 clips). A file
  that would chunk into more than 3 clips is rejected outright rather than
  silently sent as a truncated first 90 seconds - see "chunking" below for
  the reasoning.
- Max audio files per turn: **1**. Multiple audio narratives ordered in one
  turn is not a v1 need and avoids an ordering-across-files design question
  in task-v1.6.0-6; revisit if a real use case appears.
- Max upload size per audio file: **20 MB** (covers a 90 s stereo 44.1 kHz
  16-bit WAV, ~15.9 MB, with headroom; MP3 at any reasonable bitrate is far
  smaller for the same duration).

### Image

- Max images per turn: **4**.
- Max upload size per image: **15 MB** (generous for phone-camera JPEG/PNG,
  blocks pathological raw-sized uploads).
- No resize/recompression policy is decided here - that is
  task-v1.6.0-4's job. For context (not a constraint): the existing
  screenshot path already sends full-resolution PNG with no resize, and
  `PROJECT.md` records a 1120 visual-token OCR budget as the relevant
  model-side knob if downscaling is ever needed.

### Text

- Max characters sent to the model: **20000**, matching
  `config.clipboard.max_chars` - reuses the existing budget rationale
  (local-context latency) rather than inventing a second number for
  materially the same risk.
- Max upload size per text file (pre-decode safety cap, bytes read before
  truncation applies): **2 MB**.
- Max text files per turn: **1** (v1 simplicity; no cross-file ordering/
  merge policy needed yet).
- Encoding: must decode as UTF-8 (project convention, `CLAUDE.md`).
  Invalid UTF-8 is rejected as unsupported - no chardet-style guessing,
  which would be a new dependency for a marginal case.

### Combined per-turn caps

- Max total attached files per turn: **4**, across all classes together
  (e.g. 4 images and nothing else, or 2 images + 1 audio + 1 text). Each
  class's own sub-cap still applies within that total.
- Max combined upload size per turn: **40 MB**, an independent safety net
  on top of the per-file caps (keeps local normalization work bounded even
  when several large files are attached at once).

## Unsupported/oversize/truncation/chunking representation

Behavioral decisions only; the actual UI (attachment chips, feed tiles) is
task-v1.6.0-8's job. What is decided here is the *signal* every later task
consumes.

- **Unsupported format** (extension not in the table, or a
  disagreeing MIME): rejected before any bytes are normalized or sent to
  the model. Deterministic user-facing message names the file and the
  reason, e.g. `"notes.pages: unsupported file type (.pages). Supported:
  audio (wav, mp3), image (png, jpg), text (txt, md, csv, json, log)."`
  The attachment does not become part of the turn.
- **Oversize file** (exceeds its per-file byte cap, or would exceed a
  per-turn count/byte cap): rejected the same way, message states the
  actual size and the limit, e.g. `"photo.png: file is 24.1 MB, exceeds
  the 15 MB image limit."`
- **Text truncation**: same in-band-marker pattern already used by
  `jarvis.inputs.clipboard` - never silent, because the model must not
  reason from a document it doesn't know is incomplete. A `truncated: bool`
  result field (mirroring `ClipboardSubmitted.truncated`) is the signal
  task-v1.6.0-2's planner exposes.
- **Audio chunking**: files over 30 s (up to the 90 s cap) split into
  sequential fixed-length 30 s windows (last window may be shorter) - not
  VAD-based, since an uploaded file has no live speech-end signal to key
  off; task-v1.6.0-5 keeps this deterministic. Each clip is a distinct
  visible unit (e.g. "clip 2 of 3, 30.0-60.0 s"), never silently merged or
  dropped. A file that would exceed 90 s (>3 clips) is rejected outright
  with a message stating the cap and asking the user to trim/split before
  re-uploading - silently sending only the first 90 seconds would repeat
  exactly the kind of dishonest-about-capability behavior the story's
  goal explicitly rejects (upload is not realtime listening, and must not
  pretend to have heard more than it did).

## Open item for task-v1.6.0-6 (turn orchestration)

No verified fact governs relative ordering when a turn mixes images and
audio clips in the same `images` payload list (the verified fact only says
"media before text"). Default proposed here, **not verified, a design
default subject to revision**: images first, then audio clips, each group
in upload order. Text-file content is not part of the `images` list; it is
appended to the outgoing user message text, recommended (task-v1.6.0-3's
concrete choice, not binding) as a clearly delimited block:

```
[Attached file: notes.txt]
<file content, truncated marker if applicable>
[End of notes.txt]
```

## Verification

`tests/test_audio_decoder_formats.py` (pure, deterministic, part of
`python -m pytest`, no Ollama, no hardware):

- WAV decodes via `soundfile` (baseline, reuses `audio/a1.wav`).
- MP3 round-trips end-to-end through `soundfile` and `torchaudio.load()`
  using only the declared stack.
- M4A fails to decode via both, against a real AAC-in-MP4 fixture
  (`audio/sample.m4a`).
- `soundfile.available_formats()` confirms MP3 present, M4A/MP4/AAC
  absent.

No production UI, transport, or orchestration code changed in this task.
