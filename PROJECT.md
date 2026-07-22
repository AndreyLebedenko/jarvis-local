# Project: Jarvis — Local Voice/Vision Assistant

Owner: private. Workdir: repository root. Windows 11, local consumer GPU.
Goal: a fast local voice interface to an LLM, with on-demand screen capture.
**Runtime locality contract (revised 2026-07-14, story-v1.4.0 task 2 -
supersedes the pre-v1.4.0 single-tier wording below and everywhere else in
this file):** core and inference remain local unconditionally - Jarvis's
own orchestration, conversation state, and the configured local Ollama
backend require no network access, and this does not change based on
configuration, testing method, or which components are enabled. External
network access exists only as an explicit per-component capability (for
example an MCP tool provider): off by default, enabled only by explicit
user action, and reported honestly on the data-source axis - a turn whose
tool call left the machine is labeled as such, independently of
`DataLocality` (which reports where inference runs, not whether a tool
call reached the network). With every such capability disabled - the
default, and the only state that exists before story-v1.4.0 lands - the
runtime is unconditionally local, byte-identical to the pre-v1.4.0
guarantee. Rationale: MCP integration (v1.4.0) gives Jarvis its first
capability that can leave the machine at all; the human decision was to
make that boundary explicit and per-component rather than erode the old
blanket guarantee silently. Backend/model installation and non-local
inference providers remain outside Jarvis core guarantees, as before. This
file is the single source of truth for architectural decisions; update it
when a decision changes.

Long-term product direction lives in [VISION.md](VISION.md). `PROJECT.md`
records verified facts and current architecture; `VISION.md` records where the
system is intended to grow.

## Verified facts (day-0 experiments, July 2026 — do not re-litigate)

- Backend: **Ollama**, model **`gemma4:12b-it-qat`** (Gemma 4 12B, encoder-free
  unified multimodal: text + image + audio in one backbone).
- **Audio and images both reach the model via the `images` field** of
  `/api/chat` (base64). A dedicated `audio` field is silently dropped by
  Ollama — never use it.
- Audio input: max 30 s per clip, 16 kHz mono wav. Place media before text
  in the prompt.
- **Ollama thinking mode is safe to wire only if reasoning tokens stay out
  of `ResponseToken` consumers.** Verified locally on 2026-07-06 against
  Ollama 0.31.1 and `gemma4:12b-it-qat`: `/api/chat` accepts top-level
  `think: false` / `think: true`. With `think: true`, reasoning streamed in
  `message.thinking` while final answer text streamed in `message.content`;
  with `think: false`, no `message.thinking` chunks appeared. This held for
  both text-only and image input through the existing `images` field. No
  inline reasoning markers appeared in `message.content` in either variant,
  so content tokens remained clean for TTS in the measured cases. Manual
  timings: text off 7.47 s (cold-ish first request, load 7.15 s), text on
  2.24 s; media off 0.79 s, media on 2.31 s. Warm generation cost increased
  as expected because thinking produced many more tokens (media eval_count
  10 off vs 161 on; text eval_count 13 off vs 163 on). Future runtime wiring
  must discard or separately route `message.thinking`; reasoning tokens must
  never be published as `ResponseToken` or reach the TTS pipeline.
- Audio fidelity: verified — model transcribed Russian speech verbatim.
- **Intonation/prosody classification is unreliable in this quant** (detects
  that deliveries differ, misclassifies which is which). Decision: v1.0 is
  words-only. An `emotion2vec+` side-channel module (CPU-capable) is a planned
  v1.x plug-in via the event bus; do not build it into v1.0.
- Measured performance: load ~0.3 s (warm), audio prefill ~0.1–0.3 s,
  generation ~87 tok/s. VRAM under load: ~10.9/16 GB → ~5 GB headroom for TTS.
- Context: `num_ctx: 65536` (verified to fit; if VRAM pressure appears, first
  try `OLLAMA_KV_CACHE_TYPE=q8_0`, then drop to 32768).
- Manual TTS spike on 2026-07-08, using `backend.flash_attention = true` and
  `backend.kv_cache_type = q8_0`: backend wall 3.68 s, load 3.47 s,
  prompt_eval 0.12 s, eval 0.08 s, eval_count 6; Silero speaker `baya`
  loaded in 0.52 s. Measured prompt classes were `russian`, `english`,
  `mixed_latin`, `numbers`, `short_answer`, and `code_like`, with
  first-audio / total times of 1.24 / 4.50 s, 0.99 / 4.87 s, 0.37 / 4.67 s,
  0.32 / 5.98 s, 0.24 / 2.75 s, and 0.39 / 4.39 s respectively. The run
  reported `peak_vram_delta_mib = 0` across those Silero prompts. This is a
  q8_0 profile was later compared by the human against f16 across Gemma4 and
  gpt-oss at large contexts. Any accuracy loss was not detectable on the
  owner's tasks, while q8_0 improved speed by 10-20%. Decision: prefer q8_0
  for large-context local use.
- Piper follow-up for English TTS: `python -m pip install piper-tts` succeeded
  as a one-command install, and the human judged the tested English voice as
  subjectively higher quality and lower perceived latency than the current
  Silero Russian baseline. This is a promising usability signal for a simple
  Silero/Russian + Piper/English route, not a matched benchmark or final engine
  decision, because the comparison crossed languages.
- Owner's fine-tuned gemma4 variant **lost audio capability** during tuning
  (unified weights — text-only tuning shifts audio pathways). It is parked.
  Do not use it. Behavioral customization goes into the system prompt instead.
- Screenshot OCR: use high visual token budget (1120) for screen text; if
  small fonts garble, use region-select capture at full resolution rather
  than raising the budget.
- **Initial camera spike, Logitech C920 USB, 2026-07-20:**
  `python -m manual.manual_check_camera_spike --usb-index 0 --label c920`
  captured a 640x480 frame successfully and sent it through the existing
  `/api/chat` `images` path to local Ollama `gemma4:12b-it-qat`.
  Capture latency was not acceptable yet: `open_seconds = 9.628`,
  `open_to_frame_seconds = 10.084`. Model answer quality was good for
  general scene description (accurately described the person, phone,
  headphones, sofa, wall art, lamp/equipment, and bottle) and partially
  useful for visible text (identified likely shirt text "LIFE" but smaller
  text was indistinct). Object counting was not reliable: the answer
  overcounted several categories while correctly expressing high
  uncertainty. Decision: USB camera quality is promising enough to continue
  the spike, but the default OpenCV backend latency is a blocker for in-turn
  UX until a backend-specific rerun (for example DirectShow) proves faster.
  Follow-up run
  `python -m manual.manual_check_camera_spike --usb-index 0 --label c920-1080p --opencv-backend dshow --frame-width 1920 --frame-height 1080 --fourcc MJPG`
  requested and received a 1920x1080 frame through DirectShow/MJPG.
  Capture latency improved to `open_seconds = 2.636`,
  `open_to_frame_seconds = 3.254`; model probe wall times were 7.82 s
  for scene description, 0.90 s for OCR, and 1.94 s for counting.
  Image quality was materially better: the model read "Hard Rock CAFE"
  correctly from the shirt and produced a more accurate room description.
  Counting remained weak: it returned only three prominent items, included
  odd bounding-box-like coordinates, and missed obvious objects. Decision:
  the USB C920 path is a go for task 2 using DirectShow + MJPG + requested
  1920x1080 as the first Windows target. General scene description and OCR
  are useful; precise object counting is not a v1.6.2 guarantee. The Imou
  RTSP path remains pending until that hardware is available.
- **Camera implementation scope, 2026-07-20:** v1.6.2's first implementation
  sprint is USB-only. The camera is a local, off-by-default builtin sensor;
  the Control Center's per-tool switch is its non-delegable privacy control.
  `capture_camera_image` returns image media separately from its text result;
  `ToolAwareDialog` attaches that media only to the current tool-loop turn,
  never conversation history. Imou RTSP is deferred pending the hardware
  spike. Tapo was rejected for hardware reasons and is not part of the
  product; neither camera path contacts a cloud API.
- **USB camera release verification, 2026-07-20:** the owner confirmed the
  C920 end-to-end path: model-initiated capture returned a useful scene
  description, the audit panel reported the local builtin call, and the
  camera cue played. With the device physically disconnected, enabling the
  camera now reports camera failure and keeps the capture tool unavailable;
  reconnecting it and requesting the camera-chip reset restores ready state.
  A capture tool request while the privacy toggle is off does not capture.
- **The native `RegisterHotKey` provider works globally without elevation.**
  Verified live on 2026-07-10: from a non-Administrator PowerShell process,
  `Ctrl+Alt+Q` fired while another application had focus. A second process
  attempting the same combination received the expected clear `HotkeyError`,
  and `Ctrl+C` cleanup unregistered the binding without a traceback. The old
  `keyboard` provider's elevation requirement does not apply to the native
  provider; the startup elevation warning has been removed.
  Full migration verification completed on 2026-07-11 from a
  non-Administrator session with another application focused: full-screen
  capture, region capture, clipboard submit, microphone sleep/wake, thinking
  on/off, and shutdown all passed. This closes v1.2.6. Region-overlay
  threading and DirectX capture behavior remain separate capture concerns,
  not hotkey-provider failures.
- **`sounddevice`'s `play()`/`wait()` convenience functions share one
  implicit default output stream per process.** Two concurrent calls
  don't mix - the second stops/replaces the first. Verified live as the
  cause of audible crackling and tempo artifacts: a sound cue and a
  spoken TTS sentence landing on the device at the same time. Fix: any
  code that plays audio through this convenience API must serialize
  against every other such caller in the process via a shared
  `asyncio.Lock` (main.py's `build_app()` wires one lock into both
  `TtsOutput` and `SoundCuePlayer`) - never assume a second, independent
  `sd.play()` caller is safe to add later without sharing that lock.
- **A genuinely cold Ollama start exceeds httpx's ~5 s default timeout.**
  Verified live: the day-0 "load ~0.3 s warm / 4.2 s cold" figures were
  themselves measured on an already-touched model, not a true first
  request after boot - the real cold case took long enough to trip
  `httpx.ReadTimeout` on main.py's warm-up call. `config.backend.
  read_timeout_seconds` (default 120 s) fixes this; do not remove or
  shrink it without re-measuring a true cold start.
- **Silero's v3_1_ru symbol set has no Latin characters at all** (only
  Cyrillic + limited punctuation - see `model.symbols`). Verified live:
  asked to say "gemma4" aloud, the digit was spoken (`normalize_numbers`)
  but "gemma" was silently dropped, same root cause class as the digit-
  stripping bug. `tts_silero.py`'s `transliterate_latin()` does a best-effort
  phonetic Latin-to-Cyrillic conversion before synthesis (e.g. "gemma" ->
  "гемма") - crude, not linguistically rigorous, but strictly better than
  silence.
- **v1.2.8 speech-markup prompt contract is not stable enough yet.**
  Human-run `python manual_check_speech_markup_contract.py` on 2026-07-09
  against Ollama 0.31.2, `gemma4:12b-it-qat`, `think: false`,
  `num_ctx: 65536`, `flash_attention: True`, `kv_cache_type: q8_0`, and all
  other generation knobs unset showed that normal prompts violate the flat
  `<speak>` / non-nested `<lang>` contract. `russian_only` passed, but
  `english_only`, `mixed_identifiers`, and `long_nuanced_pressure` produced
  nested `<lang>` spans; `quotes_and_slashes` and `punctuation_heavy` kept
  non-nested tags but left speakable text outside a complete final `<lang>`
  span. This is a model-output contract failure, not a parser unit-test
  failure. Do not treat task-3's prompt wording as verified stable until the
  bug report `tasks/bug_reports/gemma4-speech-markup-contract-instability.md`
  is resolved and the manual check passes.
- **Decision after that failed check: v1.2.8 runtime language routing uses
  charset segmentation, not LLM language tags.** For the supported v1 pair
  (`ru`/`en`), Cyrillic and Latin alphabets are sufficiently disjoint to split
  plain model text deterministically: Cyrillic routes to `ru`, Latin routes to
  `en`, and digits/punctuation/whitespace attach to neighboring text. The
  system prompt now explicitly tells the model not to add language markup.
  This avoids relying on the model to maintain a flat XML-like grammar during
  streaming.
- **v1.2.8 charset segmentation manual check passed.** Human-run
  `python manual_check_speech_markup_contract.py` on 2026-07-09 against
  Ollama 0.31.2, `gemma4:12b-it-qat`, `think: false`, `num_ctx: 65536`,
  `flash_attention: True`, `kv_cache_type: q8_0`, and all other generation
  knobs unset produced plain speakable text for all six fixed cases
  (`russian_only`, `english_only`, `mixed_identifiers`, `quotes_and_slashes`,
  `punctuation_heavy`, `long_nuanced_pressure`). No `<speak>`/`<lang>` tags or
  Markdown fences appeared. `language_segments.segment_by_charset()` routed
  Cyrillic prose to `ru` and Latin terms/identifiers such as `parse_user_id`,
  `JSONDecoder`, `APIClient`, `pull/push`, `request/response`, `REST`,
  `HTTP/2`, `WebSocket`, `real-time`, `latency`, `observability`, and
  `failure mode` to `en`. Mixed forms such as `CRUD-операций` split into an
  English `CRUD-` segment followed by Russian `операций`, which is acceptable
  for the current two-language TTS-routing contract.
- **No echo cancellation in v1.0: audio_in.py's microphone can pick up
  Jarvis's own TTS output from the speakers.** Verified live: after
  Jarvis finished speaking, it "heard" itself and responded to its own
  voice as if it were a new user question (a hallucinated-looking reply
  to nothing the human said). Root cause: audio_in.py buffers
  continuously with no notion of "Jarvis is currently speaking," and
  needs its own `config.vad.request_end_pause_seconds` of silence after
  Jarvis stops before it decides a self-heard "utterance" is finished and
  publishes it - by which point main.py's busy flag had already cleared.
  Mitigation (not a full fix): `Orchestrator.finish_turn()`'s cooldown
  keeps busy `True` for `request_end_pause_seconds` after speech ends, so
  a self-heard tail is rejected by the existing busy-guard. This narrows
  the window but does not eliminate the risk (e.g. unusually long room
  reverb could still exceed the cooldown); true echo cancellation would
  be the complete fix, and is not attempted in v1.0.

  Task-10 (v1.1) layers a second mitigation on top, using task-09's mic
  sleep/wake primitive: `Orchestrator` now pauses `AudioInput` the moment
  a turn starts actually speaking (`on_response_token`'s first token) and
  resumes it after `finish_turn()`'s existing cooldown - the mic is not
  merely ignored during this window, it stops capturing at the device
  level, same as the user-triggered privacy sleep. This does not replace
  the busy-cooldown (still the fallback for anything the pause misses,
  e.g. a turn that produces no speech at all) and still is not full echo
  cancellation - room reverb after the cooldown/wake could still be
  picked up. Explicit human decision (2026-07-05, task-10): implement
  this now rather than defer, given task-09's primitive already existed
  and the implementation cost was low.

  Stale-buffer-replay fix (2026-07-10, verified live with a hardware-muted
  mic; see tasks/bug_reports/stale-audio-buffer-replay-after-mic-stall.md):
  the pause above used to take effect only when `stream.read()` returned,
  so a device that stops delivering frames (hardware mute, USB stall) left
  the loop blocked in `read()` with a stale buffer that replayed as a
  fresh utterance when frames resumed - the log signature is `listening ->
  thinking` within tens of milliseconds, impossible for fresh audio (the
  `still_extending` guard needs `request_end_pause_seconds` of buffered
  trailing silence first). Now entering pause/sleep actively stops the
  stream (interrupting a blocked read, same mechanism as shutdown) and
  sets a buffer-invalidation flag; the loop discards the buffer plus any
  read that straddled the pause boundary, and treats a read exception
  while paused as the interruption, not a device failure. Consequently
  `finish_turn()`'s cooldown no longer needs to mirror
  `request_end_pause_seconds`: it is a short grace period before capture
  resumes, `config.vad.resume_cooldown_seconds` (default 1.0 s).

  MME wake recovery (2026-07-11, see
  `tasks/bug_reports/microphone-wake-portaudio-restart-failure.md`): the
  affected Windows device rejected `start()` on an `InputStream` that had
  been stopped for sleep/pause. `run_microphone_loop()` now closes the
  paused stream context and creates a fresh stream through `StreamFactory`
  for every resume, including the automatic speech-pause path. The old
  stream is never restarted; buffer invalidation and pause-spanning read
  discard remain unchanged. Human verification confirmed repeated
  sleep/wake capture on the MME device without the PortAudio restart error.

  Privacy guard, redesigned after a human review caught two real bugs in
  the first version (which tracked a single `Orchestrator`-side
  `_mic_paused_by_us` boolean plus a single `AudioInput.is_awake` bit):
  (1) pressing the privacy hotkey while `Orchestrator`'s auto-pause was
  active could be misread as "wake" instead of the user's actual "sleep"
  request, since the hotkey callback decided which action to take from
  the same bit the auto-pause was also flipping; (2) `finish_turn()`
  could wake a mic the user had put to sleep independently (e.g. a
  clipboard turn submitted while asleep, then answered aloud). Fixed by
  moving this composition into `AudioInput` itself, which now tracks two
  independent flags ANDed into the actual capture state: the user's own
  requested state (`toggle_user_sleep()`, the only method that publishes
  `MicSleepToggled`/drives the privacy cues) and `Orchestrator`'s
  auto-pause (`auto_pause_for_speech()`/`auto_resume_after_speech()`,
  silent - not a user-visible privacy action, so it must not sound like
  one on every spoken response). `Orchestrator` now calls the auto-pause
  methods unconditionally around a turn's speech and no longer needs to
  reason about the user's state at all.

  The same review also caught a related hotkey race (two rapid presses
  could both read a stale pre-toggle state and schedule the same action
  twice instead of toggling twice): the decision now happens entirely
  inside `toggle_user_sleep()` on the event loop, never in the hotkey
  callback thread. All three fixes have regression tests confirmed to
  fail without the fix and pass with it.
- **Microphone device matrix post-mute finding (2026-07-18):** the earlier
  distorted-capture class reproduced through PortAudio MME on both a USB Yeti
  X and a Bluetooth TicPods ANC headset during task-v1.5.1-4's human-run
  matrix. Sequence in both cases: several clean chunks, hardware mute on the
  microphone for about 3 minutes, hardware unmute, wait for the device's ready
  signal, then immediate dictation. The first post-unmute wav was low quality
  (`utterance-007.wav` for USB, `utterance-003.wav` for Bluetooth); the next
  chunk recorded immediately afterward, without settings changes or another
  user action, was clean like the initial chunks. Initial waveform inspection
  found no clipping in either degraded wav, so this is not classified as
  amplitude saturation. Evidence is preserved locally under
  `manual_check_microphone_devices_out/20260718-214650-1-Microphone_Yeti_X/`
  and
  `manual_check_microphone_devices_out/20260718-215925-4-Headset_TicPods_ANC/`.
  The defect is tracked in
  `tasks/bug_reports/2026-07-18-microphone-post-mute-first-capture-degraded.md`.
  No capture-path change is made in v1.5.1 task 4; a fix requires a dedicated
  capture-path task.
- **Silero VAD full-buffer re-scan exceeds the capture loop's real-time
  budget at roughly a 35-40 s buffer (measured 2026-07-18, dev machine,
  CPU).** `get_speech_timestamps` cost scales linearly with buffer length:
  about 0.25 s for a 30 s buffer, 0.5 s at 60 s, 1.5 s at 180 s, against the
  loop's 0.3 s block budget. Before the silence-trim fix
  (`tasks/task-fix-mic-silence-buffer-vad-overload.md`), the capture buffer
  grew unboundedly during speech-free stretches because trimming only
  happened after a published utterance; a 3-minute silent stretch therefore
  pushed the loop several times slower than real time, PortAudio's input
  ring overflowed (the overflow flag was silently discarded), and the first
  post-silence capture was published from spliced, degraded audio. This is
  the identified root cause of the post-mute degraded-capture finding above:
  the hardware mute merely supplied the silence. The loop now bounds the
  buffer to the in-progress utterance plus a 1.0 s lead-in (or 1.0 s of
  tail during pure silence) and logs input overflows.
- **Graded Ollama `think` values `"low"`, `"medium"`, and `"high"` are all
  accepted alongside `false` (story-v1.3.1 task 1).** Human-run
  `python -m manual.manual_check_graded_reasoning` on 2026-07-13 against
  Ollama **0.31.2**, `gemma4:12b-it-qat`, `num_ctx: 65536`,
  `flash_attention: true`, `kv_cache_type: q8_0` (all other generation
  knobs unset) sent all four top-level `think` values — `false`, `"low"`,
  `"medium"`, `"high"` — across a short deterministic calculation prompt
  and a multi-step reasoning prompt (3 runs each per level) plus one
  reproducible 4-quadrant image prompt (1 run per level): 28/28 requests
  returned a `done` chunk with no transport error. With `think: false`, no
  `message.thinking` chunks appeared for any prompt (thinking char count
  0). With `"low"`/`"medium"`/`"high"`, `message.thinking` carried
  reasoning text and `message.content` held only the clean final answer in
  all 28 cases — no `<think>`/`<thinking>` markers or other reasoning
  leaked into `content` at any level. This confirms the isolation rule
  already established for boolean `think` extends unchanged to the graded
  string values.
  Token volume and `message.thinking` length were **not monotonic across
  low -> medium -> high** in this run (e.g. calculation prompt eval_count
  averaged ~487/~798/~551 for low/medium/high respectively — medium
  exceeded high). Per this task's own caution, three runs per level is not
  enough to claim a stable ordering; do not treat eval_count or thinking
  length as a monotonic proxy for reasoning quality without a larger,
  dedicated measurement.
  Anecdotal accuracy signal (small sample, not a benchmark): with
  `think: false` the calculation prompt (`47 * 63 - 129`, correct answer
  2832) was answered incorrectly in all 3 runs (2856, 2856, 2886), and the
  multi-step train prompt (correct answer 4) was wrong once (6); with
  `"low"`, `"medium"`, and `"high"`, both text prompts were answered
  correctly in all 9 runs each. The image prompt (four colored quadrants)
  was answered correctly at every level, including `off`.
- **Tool-calling reliability spike (story-v1.4.0 task 1) chose native
  `tools` as the default presentation strategy.** Human-run
  `python -m manual.manual_check_tool_calling` on 2026-07-14 against Ollama
  **0.32.0**, `gemma4:12b-it-qat`, over a fixed 6-scenario task set (a
  single typed-argument tool call in Russian and English, a no-tool-call
  false-positive check, a choice between two available tools, an
  adversarial ambiguous-arguments stress case designed to provoke
  malformed/extra arguments, and a two-step tool-result round trip), 3
  runs per scenario per strategy (18 first-hop requests per strategy, plus
  up to 3 second-hop requests per strategy for the two-step scenario):
  - **Native `tools` field: 1.00 correct-call rate, 0.00 false-positive
    rate, 1.00 argument schema validity rate (including under the
    adversarial ambiguous-arguments scenario), 0.00 format-error rate,
    1.00 two-step no-spurious-call rate. Zero transport errors** - Ollama
    0.32.0 accepted the `tools` field for this model/template exactly per
    documented behavior; no stop condition triggered.
  - **Prompt-based JSON contract: 0.87 correct-call rate, 0.00
    false-positive rate, 0.85 argument schema validity rate, 0.11
    format-error rate, 1.00 two-step no-spurious-call rate** (the last
    computed only over runs whose first hop actually produced a tool
    call). All schema-validity failures were concentrated in the
    adversarial ambiguous-arguments scenario: 2 of 3 runs omitted the
    required `units` argument, where native got city+units right in all 3
    runs of the same scenario. One run each of `tool_choice` and the
    two-step scenario's first hop returned an empty, unparseable response
    body under the prompt contract (`invalid JSON: Expecting value: line 1
    column 1 (char 0)`), with no equivalent native-strategy failure
    anywhere in this run. One anecdotal answer-quality artifact outside
    these metrics: prompt/`no_tool_needed`/run 3 substituted a stray
    non-Latin token mid-sentence into an otherwise-English answer ("a
    programming செயல் that calls itself...").
  - **Decision: native `tools` is the default tool-presentation strategy
    for story-v1.4.0** (task 3/4 wire it) - it strictly dominated the
    prompt-based contract on every measured axis in this run, with zero
    errors of any kind. Prompt-based declaration remains the documented
    fallback per the story's own architecture for templates/models that
    do not support native tools; it is not exercised as a production path
    until such a model is actually in use.
  - Caveats: 3 runs per scenario is a small sample (matches this task's
    own scope, following the graded-reasoning spike's precedent), so
    treat the exact rates as directional, not a tight confidence interval
    - the qualitative gap (native: zero errors across 21 requests; prompt:
    errors concentrated specifically under adversarial input) is the
    load-bearing finding, not the third decimal place. The very first
    request of the whole run paid a cold-start Ollama load cost (8.13 s
    vs ~0.6-0.8 s warm), consistent with the existing cold-start facts
    above, not a per-strategy latency difference - both strategies
    otherwise measured near-identical wall time (~0.6-0.8 s) per request,
    so latency was not a factor in the decision. This run's script
    tolerates the native `tool_calls[].function.arguments` field being
    either a dict or a JSON-encoded string, but the run's own output did
    not distinguish which shape Ollama 0.32.0 actually returned - task 3's
    real parser should confirm this directly against a live call rather
    than assume either shape.
- **Audio attachment format-gate (task-v1.6.0-1, verified 2026-07-19
  against the project's actual `.venv`: `soundfile 0.14.0`,
  `torchaudio 2.8.0+cpu`, no new package installed for the check).**
  MP3 decodes with the already-declared stack: libsndfile 1.1+ (bundled by
  `soundfile`) has a native MP3 decoder/encoder -
  `soundfile.available_formats()` lists `MP3`, and a synthetic tone
  encoded to MP3 with `sf.write(..., format="MP3")` round-tripped
  successfully through both `sf.read()` and `torchaudio.load()`
  (torchaudio's Windows backend is soundfile itself,
  `torchaudio.list_audio_backends() == ['soundfile']`). M4A/AAC does not:
  `MP4`/`M4A`/`AAC` are absent from `available_formats()`, and both
  `sf.read()` and `torchaudio.load()` raised `LibsndfileError: Format not
  recognised` against a real AAC-in-MP4 fixture
  (`audio/sample.m4a`, built once with PyAV as an incidental
  authoring-machine tool, not a project dependency). Decoding M4A would
  need either PyAV (bundles a full static FFmpeg build, a large new
  runtime dependency) or `pydub` plus an external `ffmpeg` executable
  (its own Windows install/PATH story) - both hit
  task-v1.6.0-1's stop condition. Decision: MP3 is supported for v1.6.0
  file attachments with no new dependency; M4A is explicitly deferred,
  and task-v1.6.0-5 is blocked from implementing M4A decode until a human
  decides to accept one of those dependencies. Full policy (formats,
  numeric limits, chunking/truncation/rejection rules) is in
  `tasks/attachment-policy-v1.6.0.md`; proof is
  `tests/test_audio_decoder_formats.py`.

## Open questions (unverified - do not assume an answer)

- **Resolved (v1.2.5 human follow-up): prefer q8_0 KV cache for large
  contexts.** Comparisons across Gemma4 and gpt-oss found no task-detectable
  accuracy loss and a 10-20% speed improvement over f16.
- **Resolved (task-07, human decision): history is text-only in v1.0.**
  Media (audio, screenshot) is attached only to the current turn's
  message; conversation history carries text only, never resent media.
  This sidesteps the previously-open questions below entirely (never
  verified whether `gemma4:12b-it-qat` attends to media on a non-final
  message; no prefill-growth risk from accumulated screenshots in
  history). Deliberately designed to extend later: main.py's
  `ConversationHistory`/`Turn` already carry a `media_b64` field that
  v1.0 code simply never populates, so a future release can start
  resending media in history without restructuring the abstraction -
  only the retention policy and the non-final-message-media question
  (still genuinely unverified against live Ollama) would need
  resolving then.
- **OCR of dense screenshots confabulates.** Verified live: a 4K IDE
  screenshot produced fluent, structurally correct, factually invented
  text (not the real file contents). Usage pattern must be targeted
  questions about screen regions, not bulk extraction. Region
  highlighting is the v2.x roadmap answer (see Roadmap after v1.0).

## Architecture v1.0

Background process, no GUI. Hotkeys + sound cues only. Python 3.11, asyncio.

Modules (each an event-bus participant; no direct module-to-module calls):

- `bus.py` — asyncio event bus (pub/sub). The extension point for everything
  later (emotion side-channel, Discord bridge, etc.). Keep it trivial.
  Handlers must return quickly (enqueue onto the module's own queue and
  return); publish() awaits all handlers, so inline heavy work in a handler
  would serialize the streaming pipeline.
- `config.py` — settings home: model name, hotkeys, VAD/TTS parameters;
  loaded once at startup.
- `backend.py` — Ollama adapter: streaming `/api/chat`, media via `images`,
  latency metrics on every call. Thin interface so the backend can be swapped
  (llama-server / LiteRT-LM) with one config line. Uses an explicit,
  generous read timeout (`config.backend.read_timeout_seconds`, default
  120 s) rather than httpx's own ~5 s default, which is too short for a
  genuinely cold Ollama start (see Verified facts). `chat()` always
  publishes `ResponseComplete` once its stream ends, even if the stream
  never sent a `done: true` chunk (zeroed `LatencyMetrics` in that case,
  plus a logged warning) — `Orchestrator.finish_turn()` (main.py) only
  clears the busy flag off the back of that event, so a stream that
  silently ended without `done: true` would otherwise wedge the process
  busy forever (v1.2.3, see
  `tasks/done/story-v1.2.3-task-1-backend-stream-completion.md`).
  `BackendSettings` also carries optional `flash_attention`,
  `kv_cache_type`, and generation request knobs (`temperature`, `top_p`,
  `top_k`, `min_p`, `repeat_penalty`, `repeat_last_n`, `seed`,
  `num_predict`, `stop`, `draft_num_predict`); they default to omission
  so the current runtime contract stays unchanged unless a config file
  explicitly sets them.
- `audio_utils.py` — shared wav-encoding helper. No project-module
  dependencies, used by both `audio_in.py` and `tts.py` so neither input
  nor output depends on the other for it.
- `language_segments.py` — pure Russian/English charset segmenter. This is not
  general language detection: it deliberately covers the v1.2.8 pair with
  non-overlapping primary alphabets. `CharsetLanguageStream` is incremental for
  streamed tokens; `segment_by_charset()` is the one-shot helper for manual
  checks and tests. Neutral characters (digits, punctuation, whitespace) attach
  to the nearest language run so code identifiers, `HTTP/2`, `WebSocket`, and
  slash-separated English examples stay usable for TTS routing.
- `audio_in.py` — microphone capture + silero-vad; end-of-utterance detection;
  chunks <= 30 s; publishes wav chunks to the bus. `AudioInput.stop()` is the
  cooperative shutdown path for the microphone loop: it sets the loop's stop
  flag, wakes any sleep wait, and stops the active sounddevice stream so a
  blocking `stream.read()` running inside `asyncio.to_thread()` can return
  before `run_until_shutdown()` awaits all background tasks. Do not replace
  this with a teardown timeout that leaves background tasks alive.
  Since task-v1.5.1-1, `stop()` is terminal: it waits unconditionally
  until the loop (and its blocking read worker) has actually exited, so
  after `stop()` returns the microphone code can submit no further
  executor job, and a loop started after `stop()` exits immediately
  without opening a stream (the loop no longer resets the stop flag on
  entry). There is deliberately no timeout: `stream.stop()` interrupting
  a blocked read is verified device behavior (stale-buffer-replay fix);
  a driver whose read never returns even then would need its own
  explicit degraded-shutdown design, not a silent WARN-and-continue.
  Related process-lifecycle fact (verified 2026-07-18 against pywebview
  6.2.1 source): `webview.start(func)` runs `func` in a plain thread it
  never joins and can return before that thread is even scheduled, so
  `run_with_status_console()` owns the engine lifetime through a
  `concurrent.futures.Future` completed by the engine callback (result
  or exception) and blocks on it after `webview.start()` returns -
  otherwise interpreter shutdown races the engine teardown and in-flight
  `asyncio.to_thread()` submissions raise; an engine exception now
  propagates to the caller instead of dying in the unjoined thread (see
  `tasks/bug_reports/2026-07-17-shutdown-microphone-executor-race.md`).
- `tts.py` - common TTS contracts, response buffering, language routing,
  ordered playback, and health events. Silero remains the compatible
  default when no explicit bilingual routing table is configured; configured
  routes may select Silero or Piper independently for each supported language.
  `TtsOutput` owns sentence buffering and ordered playback orchestration;
  synthesis sits behind the `TtsEngine` protocol - the constructor's only
  synthesis seam (the earlier parallel `synthesize=` callable seam was
  removed in the 2026-07-09 entropy review). The protocol is
  `synthesize(text, language="ru") -> bytes` (wav-encoded; the wav header
  carries the sample rate, so playback needs no side channel - the
  earlier `SynthesisResult` wrapper duplicated the header's sample rate
  and was dropped). `language` is a routing hint, not a fixed engine mapping;
  `tts_silero.py` owns `SileroEngine`, lazy Silero loading, and the legacy
  Russian normalization/transliteration applied only when the configured
  model language is `ru`. `tts_piper.py` owns `PiperEngine` (v1.2.9 task 2,
  generalized in v1.2.15), the production adapter for local Piper `.onnx`
  voices: it imports `piper-tts` lazily and uses Piper's chunk API to write a
  complete wav header itself. Model/config path resolution and voice loading
  happen on first synthesis, not during app construction. v1.2.9 task 3 wires
  configured
  language routes through `BilingualTtsEngine`: `tts_factory.py` is the
  composition layer, and `build_tts_engine()` preserves
  the existing Silero-only default when only the built-in `ru -> silero`
  route is present, and otherwise composes one child engine per configured
  language (`ru`/`en`) with clear failure for unsupported language hints.
  A non-default routing table must cover both `ru` and `en` (charset
  segmentation emits both regardless of configuration). Since v1.2.15 each
  route is a typed Silero/Piper settings object: config shape, required fields,
  types, unknown parameters, and general sanity are validated at startup;
  model identifiers are not project-allowlisted. Model files and concrete
  engine/model/parameter compatibility are checked by lazy loading on first
  synthesis. A synthesis failure at runtime is logged
  and its unit skipped: `OrderedPlayback` requires every index to arrive,
  so submitting `None` for the failed index is what keeps one bad sentence
  from silently stalling all later speech in the session. The
  Silero-specific model loading, Russian number normalization, Latin
  transliteration, and `apply_tts` call live in `SileroEngine`. Since the
  v1.2.8 pivot, `TtsOutput` streams tokens through `SpeechUnitBuffer`:
  charset language segmentation happens BEFORE sentence buffering
  (`CharsetLanguageStream`, incremental), so language routing no longer
  depends on the model emitting XML-like control tags. A language switch is an
  additional flush boundary alongside sentence boundaries, and a short
  connective remainder at a switch (<= 3 word chars, no sentence punctuation -
  e.g. the Russian "и" between two English words) is carried into the following
  segment instead of becoming a standalone synthesis call - but ONLY while
  every configured route uses one engine (the Silero-only default, whose
  transliteration voices either language). With distinct per-language engines
  the carry is disabled: verified live in the v1.2.9 task-4 handoff, a
  carried Russian "Для" reached Piper, which has no Cyrillic phonemes and
  spelled it out letter by letter ("Missing phoneme from id map" warnings).
  The segment language reaches `TtsEngine.synthesize()` as the routing hint
  (ignored by the default Silero runtime).
  Production route verified live (2026-07-10, v1.2.9 task-4 handoff via
  `manual/manual_check_bilingual_tts_production.py`, which exercises the
  real load_settings -> build_tts_engine -> TtsOutput wiring and prints the
  engine per synthesized unit): `ru -> silero v3_1_ru (baya)`,
  `en -> piper .local-models/piper/en_US-ryan-low/en_US-ryan-low.onnx`,
  with correct ordering and no cross-language units.
  Sentence-level streaming is mandatory: buffer LLM tokens to sentence
  boundary -> synthesize -> play, while generation continues. Target end-to-end response start:
  within ~3 s of audio_in.py publishing the finished utterance (i.e. after VAD's
  request_end_pause_seconds confirm-delay - not from the literal instant
  speech physically stopped), covering audio prefill + first-sentence
  generation + TTS synthesis of that sentence. `request_end_pause_seconds`
  (`config.vad`) is a separate, tunable cost paid before this window
  starts: 2.0 s is a deliberately conservative value for the development
  stage; production is expected to tighten it to ~1.0-1.5 s once
  request-boundary behavior is validated (see task-04's audio_in.py).
  The final default-playback TTS unit gets a 1.0 s silent WAV post-roll before
  reaching `sounddevice.play()`: human testing across Silero and Piper heard
  final phrase endings clipped, and padding the last unit keeps the output
  device alive long enough to drain the audible tail without adding gaps
  between streamed sentences. Which unit is final is decided at play time
  ("no later unit scheduled yet"), not at synthesis time against an index
  recorded by `ResponseComplete`: the completion event can arrive after the
  last sentence (flushed mid-stream by a trailing ". ") has already finished
  synthesizing, so the synthesis-time check lost that race and the clipping
  returned intermittently (observed live). The play-time rule always holds
  for the true final unit; a mid-stream unit can also match during slow
  generation, where the extra tail is masked by waiting for the next
  sentence anyway.
  Loading the Silero TTS model requires network on first use (like
  `ollama pull` for the backend model) - a one-time setup step via
  `setup_tts_model.py`, run once before the offline runtime starts; not
  part of runtime behavior. `tts_silero.py` checks the local cache
  explicitly and raises a clear error instead of silently reaching for
  the network if the one-time setup hasn't been run. `transliterate_latin()`
  converts Latin-script text to a crude phonetic Cyrillic approximation
  before synthesis, since Silero's symbol set has no Latin characters at
  all (see Verified facts) - applied after `normalize_numbers()`.
- `speech_markup.py` — experimental pure scanner for Jarvis's small SSML-inspired speech
  markup subset. It accepts plain text as default Russian, optional `<speak>`,
  and `<lang xml:lang="ru|en">` routing tags (including common region variants
  normalized to `ru`/`en`). Rewritten in the 2026-07-09 entropy review from
  an `html.parser` subclass (which silently swallowed ANY tag-like text -
  "List<String>", "<div>" - a real content-loss risk for code answers) to a
  dedicated scanner that treats exactly the four known control tokens as
  markup and preserves everything else as literal spoken text.
  `SpeechMarkupStream` is incremental (feed()/close(), holds language state
  and unterminated-tag tails across chunks) so the TTS buffering integration
  can parse markup BEFORE sentence buffering during token streaming, using a
  closing `</lang>` as an extra flush boundary - see
  `tasks/story-v1.2.8-task-2-tts-buffering-integration.md` for that
  recorded design decision. It is no longer used by the runtime TTS path after
  the charset-segmentation pivot, but stays in the repo with tests as a
  preserved experiment and possible future repair/interop helper.
  `parse_speech_markup()` is the one-shot wrapper
  (cleans whitespace, merges adjacent same-language segments, smooths
  punctuation-only fragments, soft-drops malformed control tags without
  speaking them). Malformed known control fragments, missing language
  attributes, unsupported language codes, and unmatched `</lang>` closers
  log warnings through standard `logging`; `app.py` configures logging at
  startup, so those warnings reach stderr and, since v1.6.4, the rotating
  file log. This is not full SSML compatibility.
- `capture.py` — mss screenshots; hotkey-triggered; modes: full screen and
  region select; publishes png to the bus for inclusion in the next request.
- `sound_cues.py` — synthesizes placeholder cue tones (pure math, offline,
  no assets committed) if `config.sound_cues`' paths don't already exist,
  and plays them; fire-and-forget so a cue never adds latency to the
  request it signals about.
- `main.py` — wiring + system prompt (since v1.2.12 the prompt text lives
  in config.py's PromptSettings, `[prompts]` section). System prompt must
  enforce SHORT
  conversational answers (latency ∝ answer length), Russian by default, and
  plain speakable text. It tells the model not to use Markdown unless asked and
  not to add language markup; English terms, API names, identifiers, short
  English phrases, and quotes can appear as ordinary text where useful.
  Conversation history is text-only in v1.0 (see Open questions); media is
  attached only to the current turn. Assistant history stores the plain
  accumulated `ResponseToken` text. Warms Ollama up with a throwaway
  request before subscribing anything to the bus, so the response isn't
  spoken or recorded. Native global hotkeys do not require Administrator
  elevation (see Verified facts).
  `Orchestrator.finish_turn()`'s cooldown (`config.vad.
  resume_cooldown_seconds` after speech ends, default 1.0 s; historically
  `request_end_pause_seconds` until the 2026-07-10 stale-buffer-replay fix
  made the mic pause deterministic - see Verified facts) is a short grace
  period before capture resumes - not a substitute for real echo
  cancellation, which is still not attempted.

## Architecture v1.1 (controlled input)

See [tasks/done/story-v1.1-controlled-input.md](tasks/done/story-v1.1-controlled-input.md).
Task-08 landed first:

- `clipboard_input.py` — reads clipboard text via `pyperclip` (not
  Tkinter: reusing Tkinter here would repeat the thread-safety hazard
  already caught live in capture.py's region-select overlay, see
  `tasks/bug_reports/capture-region-select-tkinter-thread-safety.md`) and
  builds a `ClipboardSubmitted` event. No hotkey-listening code lives
  here yet - the real global hotkey is task-10's job (see the story
  card's task split). `config.clipboard.max_chars` (default 20000
  characters, ~5000 tokens at a rough 4 chars/token estimate) caps
  clipboard length; text over the cap is truncated with a visible
  in-band marker, never silently cut or rejected - an accidental huge
  paste (e.g. a log file) is a real risk to local-context latency, and a
  silent cut would let the model reason from an incomplete document
  without anyone knowing.
- `main.py`'s `Orchestrator` gained a shared `_start_turn()` path used by
  both audio (`on_utterance`) and clipboard (`on_clipboard`) turns,
  instead of a second parallel implementation. Clipboard turns record the
  *real* submitted text in `ConversationHistory` (the first non-
  placeholder user text in v1.0/v1.1) and never attach the pending
  screenshot from `capture.py` - a screenshot taken "for" a voice
  question should not silently attach to an unrelated pasted-code
  question that happens to arrive first (see the story's Open decisions).
- `config.sound_cues` gained `clipboard` (clean submission) and
  `input_error` (truncated or empty clipboard - distinct from the
  existing generic `error`, which covers backend/TTS failures) fields.
  The real `SoundCuePlayer`/`ensure_generated()` don't reference these
  yet and `config.example.toml` doesn't list them - that wiring is
  task-10's job.

Task-09 landed second:

- `AudioInput` gained `sleep()`/`wake()` (backed by an internal
  `asyncio.Event`) and a `stream_factory` constructor seam (defaults to
  the real `sd.InputStream`, injectable for tests) - no hotkey-listening
  code lives here either, matching task-08's pattern; the real global
  hotkey binding is task-10's job. (Superseded by task-10's review: see
  below - `sleep()`/`wake()` were replaced by `toggle_user_sleep()` plus
  the separate `auto_pause_for_speech()`/`auto_resume_after_speech()`
  pair, since a single awake bit could not represent the user's privacy
  intent and the internal echo-mitigation pause independently.)
- The original task-09 implementation reused the *same* `sd.InputStream`
  across sleep/wake cycles via `.stop()`/`.start()`. That behavior is
  superseded by the MME wake-recovery fix: `run_microphone_loop()` now closes
  the paused stream context and creates a fresh stream through
  `StreamFactory` on each resume, while still blocking on
  `self._awake.wait()` instead of busy-polling.
- The accumulated capture buffer is dropped on the sleep transition.
  Without this, audio captured but not yet confirmed as a complete
  utterance when sleep is triggered could still be sitting in the
  buffer when new audio arrives after wake, and the VAD/merge pipeline
  could stitch the two together into one utterance spanning a real gap
  where nothing was actually being captured. Consequence: any
  unconfirmed audio in the buffer at the moment sleep triggers is
  discarded, not published - sleep is a privacy pause, not a "flush
  first" action. Verified via a fixture test (speech, sleep before
  confirmation, wake, different speech) that the reset is what prevents
  the two from merging (test fails without the reset, passes with it).
- `config.hotkeys` gained `mic_sleep_toggle` (default `ctrl+alt+m`) and
  `config.sound_cues` gained `mic_sleep`/`mic_wake` fields. As with
  task-08's new sound cue fields, nothing wires these to the real
  hotkey listener or `SoundCuePlayer` yet, and `config.example.toml`
  doesn't list them - task-10's job.

Task-10 landed third, wiring task-08/task-09 end to end:

- `clipboard_input.py` gained `run_hotkey_listener()`, binding the new
  `hotkeys.clipboard_submit` (default `ctrl+alt+v`) - mirrors
  `capture.py`'s listener shape (config-driven binding, injectable
  provider/`read_clipboard`). This listener now uses `HotkeyProvider`;
  `keyboard_module` describes the historical v1.1 test seam.
- `audio_in.py` gained `run_hotkey_listener()` for `hotkeys.
  mic_sleep_toggle`, calling `AudioInput.toggle_user_sleep()` on every
  press, and a `MicSleepToggled(is_awake: bool)` bus event that method
  publishes (only that method - see the Verified facts entry above for
  why the internal auto-pause deliberately does not). `main.py`'s
  `wire()` subscribes to it and plays `mic_sleep`/`mic_wake` - the same
  "input module publishes, main.py decides what to do about it" split
  already used for every other cue, so `audio_in.py` still has no
  dependency on `SoundCuePlayer`.
- `main.py`'s `wire()` now also subscribes `ClipboardSubmitted ->
  orchestrator.on_clipboard` (task-08 built the handler but never
  wired it) and the new `MicSleepToggled` handler. `run()` starts both
  new hotkey listeners as background tasks alongside the existing
  audio/capture ones, cancelled/awaited on shutdown the same way.
- `sound_cues.py` gained tone generators and `_paths`/`_GENERATORS`
  entries for `clipboard`/`input_error`/`mic_sleep`/`mic_wake` - these
  config fields existed since task-08/task-09 but `SoundCuePlayer`/
  `ensure_generated()` never referenced them, so `sound_cues.play(...)`
  for any of them was silently a no-op (logged a warning) until now.
- `config.example.toml` gained entries for every new v1.1 field
  (`hotkeys.clipboard_submit`, `hotkeys.mic_sleep_toggle`,
  `clipboard.max_chars`, the four new `sound_cues` paths).
- System prompt left unchanged: pasted clipboard text arrives as an
  ordinary user message (task-08's `on_clipboard()` already sends the
  real text, not a placeholder), so the model does not need to be told
  the input came from the clipboard rather than speech to answer it
  well - there is nothing input-modality-specific for it to react to.

Human manual-testing review of task-10 found two more issues, both fixed:

- **No logging was configured anywhere in the process** (verified: a
  grep for `basicConfig`/`setLevel` across every module found nothing).
  Every existing `logger.info(...)` call project-wide (e.g. the busy-
  guard "ignoring ..." messages) was silently dropped - Python's logging
  module only auto-prints WARNING+ without configuration. This is what
  made the `input_error` cue issue below hard to diagnose from the
  console. Fixed: `run()` now calls `logging.basicConfig(level=INFO,
  format="%(asctime)s %(levelname)s %(name)s: %(message)s")` at
  startup, and `SoundCuePlayer.play()`/`_on_mic_sleep_toggled()` now log
  an INFO line naming the cue/state so cue-related activity is visible
  with a timestamp, as requested during review. *Superseded by v1.6.4:*
  the bare `basicConfig()` became
  `core/log_config.py::configure_logging()`, which keeps this stream
  handler and adds the rotating file sink. The reasoning above still
  holds - v1.6.4 only extends it from "visible in a terminal" to
  "recoverable after the fact".
- **The `input_error` cue was not reliably audible.** Its original tone
  (a single 240 Hz, 0.1 s blip) was quieter/shorter than every other
  v1.1 cue (all multi-segment). Fixed: redesigned as two same-pitch
  blips separated by a silent gap (`sound_cues.py::_cue_input_error()`),
  clearly longer and rhythmically distinct from the generic two-tone
  *falling* `error` cue. Since `ensure_generated()` only creates a cue
  file if it does not already exist, anyone who already ran task-10's
  build must delete their stale `sounds/input_error.wav` for the new
  tone to take effect on next launch.

## Architecture v1.2 (thinking mode)

**Superseded by Architecture v1.3.1 (graded reasoning mode) below.** Kept
as history of the original boolean design; `ThinkingModeState`,
`ThinkingModeToggled`, and `thinking_enabled` no longer exist in the
codebase - do not use this section as a current API reference.

See [tasks/done/story-thinking-mode.md](tasks/done/story-thinking-mode.md). Built on
the day-0 spike recorded in this file's Verified facts (top-level `think`
param; `message.thinking` isolated from `message.content`). Task-11 landed
the backend contract, task-12 the runtime state/hotkey, task-13 the final
`main.py` wiring:

- Default mode is **off**. Thinking mode is an explicit, user-controlled
  tool for occasional harder questions, not a new default answer style -
  the spike measured substantially more generated tokens with thinking
  enabled (media eval_count 161 vs 10; text 163 vs 13), and Jarvis's voice
  UX depends on short latency.
- `config.hotkeys.thinking_toggle` (default `ctrl+alt+t`) toggles the
  mode. `config.sound_cues.thinking_on`/`thinking_off` are the distinct
  feedback tones (`sound_cues.py::_cue_thinking_on()`/
  `_cue_thinking_off()`) - not to be confused with the existing
  `sound_cues.thinking` field, which is the unrelated per-turn "request in
  flight" cue played on every turn regardless of this mode.
- State owner: `thinking_mode.py`'s `ThinkingModeState`, holding a single
  `is_enabled` bit and publishing `ThinkingModeToggled` on
  `toggle()`. Mirrors `audio_in.py`'s `AudioInput.toggle_user_sleep()`
  race-avoidance shape - `toggle()` reads and flips state with no `await`
  in between, so two rapid hotkey presses (scheduled via
  `run_coroutine_threadsafe` from the hotkey provider's own thread) can
  never both observe the same stale value and schedule the same
  transition twice instead of toggling twice.
- `main.py`'s `Orchestrator._start_turn()` is the sole consumer: it reads
  `ThinkingModeState.is_enabled` synchronously (no `await` before the
  value reaches `OllamaBackend.chat()`'s argument list) at the start of
  each accepted turn and passes it as `thinking_enabled`. This is
  deliberately **sampled at turn start, not the live stream** - a hotkey
  press during an in-flight response affects only the next accepted turn.
  Changing a live Ollama stream mid-response was explicitly out of scope
  (cancellation/partial-output questions unrelated to this feature).
- Exact backend parameter: `OllamaBackend.build_payload()`/`chat()` accept
  `thinking_enabled: bool`, setting the top-level `think` field verified
  by the spike.
- **Hard reasoning-token isolation rule**: `message.thinking` is never
  read by `backend.py`'s stream loop - only `message.content` becomes a
  `ResponseToken`. This is enforced at the same point regardless of
  `thinking_enabled`, so there is no separate code path that could leak
  a reasoning chunk into `ResponseToken`, history, or TTS. A regression
  test (`tests/test_main.py::
  test_thinking_chunks_never_reach_tts_through_real_bus_wiring`) exercises
  this through the real bus/`wire()` wiring, not just `backend.py` in
  isolation.
- `wire()` subscribes `ThinkingModeToggled`, plays the on/off cue, and
  logs "Thinking mode enabled"/"disabled" at INFO level - the same
  publish-then-main-decides split used for every other cue-driving event
  (`MicSleepToggled`, etc.).
- Reasoning traces are not displayed, logged, or otherwise exposed
  anywhere in this story - out of scope by design (see the story card's
  Open decisions). A later GUI/debug-console feature would need its own
  story for the privacy/logging/transcript implications.
- **Manual end-to-end verification (2026-07-06, human-run against a live
  Ollama endpoint): passed.** Hotkey toggled thinking mode globally,
  `thinking_on`/`thinking_off` cues were audible and distinct, the
  console logged "Thinking mode enabled"/"disabled" on each toggle, and
  reasoning was confirmed to never reach the spoken answer with thinking
  on (voice, clipboard/text, and screenshot input) - the human explicitly
  confirmed "поток рассуждения в голосовой ответ не лезет, тут всё ок."
  The process stayed offline aside from the local Ollama endpoint.
  One unrelated anomaly was observed during the same session (an extra,
  unprompted turn on the same topic) and is tracked separately - see
  [tasks/bug_reports/thinking-mode-mic-window-before-autopause.md](tasks/bug_reports/thinking-mode-mic-window-before-autopause.md).
  It is not a regression in the reasoning-token isolation guarantee above;
  it concerns `audio_in.py`'s pre-existing, already-documented lack of
  full echo cancellation (see this file's other Verified facts entry on
  that topic), which thinking mode measurably widens the risk window for
  but does not itself cause.

## Architecture v1.3 (Status Console UI)

See [tasks/done/story-status-console-ui.md](tasks/done/story-status-console-ui.md).
Task-ui-01 landed first, defining the backend-to-UI contract before any
screen is built:

- `ui_contract.py` — pure data module (enums + frozen dataclasses), no bus
  wiring, no GUI framework dependency: `RuntimeState` (six states, including
  `WARMING` as a runtime activation state, not a privacy/cloud indicator),
  `ModuleId`/`HealthStatus`/`ModuleHealth` for the five module chips
  (backend, microphone, TTS, memory, vision), `EventLevel`/`SystemEvent` for
  the system events panel, and `VisibilityMode`/`DataLocality` as two
  independent axes (system visibility vs. where inference runs - v1.0 only
  ever reports `DataLocality.LOCAL`).
- No new bus events are published yet. `tasks/done/task-ui-01-state-and-
  event-contract.md` maps existing events (`ResponseToken`,
  `ResponseComplete`, `MicSleepToggled`, `ThinkingModeToggled`,
  `ScreenshotCaptured`, `ClipboardSubmitted`) onto this contract and lists
  the events that do not exist yet and are required by later task cards
  (turn-lifecycle event for `THINKING`/`LISTENING`, a warm-up event for
  `WARMING`, a structured error event, and hardware/model availability
  signals for microphone/TTS/backend/vision) - none of it implemented here,
  to keep this task card scoped to the contract itself.

Task-ui-02 landed second: the desktop shell itself, still with no live bus
wiring.

- **GUI framework decision (human, this task's stop condition):**
  `pywebview` over a local HTML/CSS/JS front-end, not a native widget
  toolkit. Windows backend is WebView2 (pre-installed on Windows 11); a
  future Linux backend would be QtWebEngine via PySide6 - a `pywebview`
  GUI-backend argument, not a UI rewrite. Chosen because it lets the
  existing `.planning/UI/mock-ups/jarvis_status_console_v1.html` visual
  language become the real UI with minimal rewrite while keeping every
  asset local. The UI stays a thin client over engine state delivered
  through `pywebview`'s own in-process `evaluate_js` bridge; a networked
  WebSocket transport is deferred to whichever later task needs cross-
  device delivery (task-ui-06's touchstrip, if it runs on a separate
  device) - `bus.py` itself is unaffected either way.
- `status_console_ui/` — the front-end: `index.html` (production shell:
  orb, five module chips, data-locality badge, disabled placeholders for
  the Think toggle/reset button/system-events panel that task-ui-04/03
  wire for real), `style.css` (system font stack only - Segoe UI/Consolas,
  no Google Fonts/CDN/bundled font files - and the responsive rule below
  720px width), `app.js` (pure DOM-update functions keyed to
  `ui_contract.py`'s JSON shapes: `applyRuntimeState`/`applyModuleHealth`/
  `applyDataLocality`/`applyModelLabel`). `demo.html`/`demo.js` are a
  dev-only QA harness (buttons exercising every state/health/locality
  value against the same markup) - not part of the production surface,
  reused by task-ui-07's manual QA pass.
- `status_console.py` — `StatusConsoleWindow` launches the `pywebview`
  window (injectable `window_factory`, mirroring `audio_in.py`'s
  `InputStreamLike` pattern, so tests need no real WebView2 install) and
  exposes `push_runtime_state()`/`push_module_health()`/
  `push_data_locality()`/`push_model_label()`/`push_system_event()`, each
  translating a `ui_contract.py` value into JSON and calling the matching
  `app.js` function via `evaluate_js`.
- `WARMING`'s color is a distinct amber shade (`--amber-warm`) from
  `SPEAKING`'s `--amber`, plus its own dashed/faster ring animation and an
  explicit "(локально)" qualifier in the label text - so it cannot be
  misread as a cloud/data-locality warning even though v1.0 has no cloud
  indicator to confuse it with yet (this task's acceptance criterion).
- `manual_check_status_console.py` — hardware-dependent handoff (real
  window, real WebView2): pushes `config.py`'s real `backend.model` (no
  hardcoded model name), cycles every `RuntimeState`, and publishes sample
  `SystemEvent`s through a real bus + `system_log.publish_system_event()`
  for visual review, per CLAUDE.md's testing protocol.

Task-ui-03 landed third: real system events, still with no live
`StatusConsoleWindow` subscribed inside `main.py`'s actual `run()` (see
below for why that remains deliberately out of scope).

- **Stop Condition, resolved:** "if logs and bus events diverge as
  competing sources of truth, stop and define which layer owns UI-visible
  events." Resolution: `system_log.py`'s `publish_system_event(bus,
  logger, source, level, log_message, ui_message, correlation_id=None)`
  is the *only* place that decides a user-facing system event happened -
  it always logs via the given logger AND publishes `ui_contract.py`'s
  `SystemEvent` on the bus in the same call, so the console/file log and
  the events panel can never disagree about whether something fired.
  `log_message` (English, technical - matches this project's existing
  console-log convention) and `ui_message` (Russian, matches the Status
  Console's other user-facing text) are two different strings by design,
  not one string forced to serve both audiences - see `system_log.py`'s
  docstring.
- `main.py`'s `warm_up()` (now takes `bus: EventBus`), `_on_mic_sleep_
  toggled()`, and `_on_thinking_mode_toggled()` all call
  `publish_system_event()` at their existing log call sites (source
  `WARMUP`/`HOTKEY`) - this is safe today even though nothing in `main.py`
  constructs a `StatusConsoleWindow` yet, since `bus.py` treats publishing
  with zero subscribers as a no-op.
- **Deliberately not done here:** wiring an actual `StatusConsoleWindow`
  into `main.py`'s `App`/`run()`. `pywebview`'s `webview.start()` runs its
  own GUI loop (typically expected on the main thread) alongside this
  process's asyncio loop (`asyncio.run(run())`, also wanting the main
  thread) - reconciling the two is a separate, larger concurrency question
  than "system events panel," not assigned to any task card yet. Until
  that lands, `manual_check_status_console.py` is the only place a real
  `StatusConsoleWindow` and a real bus meet.
- `status_console_ui/index.html`'s events panel (`#logList`) renders newest
  first (`app.js`'s `appendSystemEvent()`, `Element.prepend()`), is capped
  at `MAX_LOG_ENTRIES = 200` DOM nodes, and wraps long messages
  (`overflow-wrap: anywhere`) instead of overflowing the panel.
  `demo.html`/`demo.js` gained buttons for each `EventLevel` plus a
  "+50 events" stress button for this.

Task-ui-04 landed fourth: the Think toggle and reset controls, and the
first JS -> Python direction of the bridge (`pywebview`'s `js_api`,
`evaluate_js`'s counterpart).

- **Stop Condition, resolved:** "if a module has no lifecycle/reset API,
  do not fake success in UI. Stop and record the missing engine
  capability." No module (backend, microphone, TTS, memory, vision) has
  one today. Resolution, directly answering the story's own open question
  ("should reset module actions start as log-visible requests only?"):
  yes - `StatusConsoleApi.reset_module()` always publishes a `WARN`
  `SystemEvent` honestly reporting "no engine reset API exists yet" for
  every module, never a fake success. Only the two controls that *do* have
  a real, small engine capability are fully wired: the Think toggle
  (`ThinkingModeState.toggle()`, already existed) and the global context
  reset (`ConversationHistory.clear()`, added by this task - a genuinely
  implementable, narrowly-scoped capability, not blocked by the Stop
  Condition).
- At task-ui-04 time, `status_console.py` gained `StatusConsoleApi`, exposed
  to the front-end as `window.pywebview.api` (`js_api=` on
  `webview.create_window()`). Each public method was a plain sync callable
  scheduling its real async work via `asyncio.run_coroutine_threadsafe()`
  onto a given loop because pywebview invoked `js_api` methods from its GUI
  thread. The optional-loop construction order existed to bind that object
  before `webview.start()` created the real asyncio loop. This direct bridge
  was removed in v1.2.10. Task-v1.5.1-2 confirmed that no `create_window()`
  site binds `js_api` anymore and removed the API layer's silent
  warn-and-return guards for unknown enum values. Membership validation now
  lives in `UiTransportServer`'s control dispatch as `ProtocolError`s, while
  a direct programmatic call with a bad value raises `ValueError`.
  `_schedule()` remains because the native pywebview GUI-thread `on_closed`
  hook still drives `request_shutdown()` across the thread boundary and must
  never receive a closed-loop exception.
- At task-ui-04 time, the front-end deliberately did not optimistically flip
  the Think switch: `toggleThinking()` called the `js_api`, while the visual
  changed only through `applyThinkingMode()` after a real
  `ThinkingModeToggled` event. The v1.2.10 transport migration preserved this
  authoritative-state rule while replacing direct `window.pywebview` calls
  with WebSocket control messages and state updates.
- Global context reset requires confirmation before the destructive
  action (`showResetConfirm()`/`hideResetConfirm()` are pure local UI
  state; only `confirmContextReset()` calls `reset_context()`). Per-module
  reset buttons (chip `⟲` icons) have no confirmation step, since they
  never do anything destructive yet.
- `main.py`'s `ConversationHistory` gained `clear()` (drops every recorded
  turn; does not touch `Orchestrator`'s own busy/pending-screenshot state,
  which is unrelated to conversation history).

Task-ui-05 landed fifth: the `Open`/`Hidden` system visibility mode toggle.

- **Open Question, resolved (human decision):** the story's own open
  question ("does `Hidden` mute TTS globally or only for UI-triggered
  turns?") and task-ui-05's own blocking question ("should Hidden suppress
  spoken TTS from ordinary voice turns?") are both answered the same way:
  **neither - in v1, `Hidden` only changes what the Status Console UI
  itself displays.** It never touches `audio_in.py`/`tts.py`/
  `Orchestrator`; ordinary voice turns speak normally regardless of Open/
  Hidden. `tasks/task-ui-privacy-and-touchstrip-requirements.md`'s earlier
  "TTS muted/text-only" line was early UI planning, not this decision -
  that file has been corrected to match.
- `visibility_mode.py` - `VisibilityModeState`/`VisibilityModeChanged`,
  mirroring `thinking_mode.py`'s shape (bus-publishing state owner) but
  with no hotkey listener (task-ui-05's Scope only asks for a UI-level
  control) and a `set_mode(mode)` two-state setter rather than a binary
  `toggle()` - redundantly setting the already-active mode is a real,
  expected UI input (clicking "Open" while already Open) and is a no-op
  (no publish), not a spurious "changed" event.
- `status_console.py`'s `StatusConsoleApi` gained `set_visibility_mode
  (mode_value)`, the same `js_api`/`run_coroutine_threadsafe` pattern as
  `toggle_thinking()`/`reset_context()`. It publishes an `INFO` `SystemEvent`
  only when the mode actually changes (mirroring `VisibilityModeState`'s
  own no-op-on-redundant-call rule, so the two can't disagree about what
  counts as "changed").
- Front-end: a two-button `Open`/`Hidden` toggle in the topbar (`--cyan`
  for Open, `--violet` for Hidden - never `--amber`, which is reserved for
  warning/cloud/warmup-adjacent states per the privacy doc, so Hidden can
  never look like a cloud/error indicator) sits next to, but visually
  distinct from, the data-locality badge - clicking it never touches
  `#localityBadge`/`applyDataLocality()` (task-ui-05 AC: "Hidden does not
  imply cloud/offline status"), verified both structurally (a test parses
  `app.js`'s `applyVisibilityMode()` body) and live via the Preview tools.
  The one concrete Hidden behavior implemented: the vision/screen chip's
  detail text is replaced with a generic placeholder while Hidden is
  active (last real value remembered, restored on Open) - the only surface
  in the current UI that could carry a sensitive screen-capture detail.
- **Review finding, fixed:** `manual_check_status_console.py`'s first
  version subscribed `SystemEvent`/`ThinkingModeToggled` but never
  `VisibilityModeChanged`, so a real click in the actual window would have
  updated state and logged an event while leaving the toggle/vision-chip
  text unchanged - the manual handoff would not have proven what it
  claimed to. Fixed by adding the missing subscription;
  `tests/test_manual_check_status_console.py` now exercises this file's
  bus-wiring directly (fake console, real bus, no window) so a future
  missing subscription here fails an automated test.

Task-ui-06 landed sixth: the touchstrip glance surface, a second window
sharing the desktop window's engine state.

- **Stop Condition, evaluated:** "if the chosen GUI framework cannot
  support this surface without a separate process or large architecture
  change, stop and split the touchstrip work into its own story." Not
  triggered - `pywebview` supports creating multiple windows in one
  process before a single `webview.start()` call, so `TouchstripWindow`
  needed no new process or architecture change.
- `status_console.py`'s `StatusConsoleWindow` gained constructor
  parameters (`title`/`url`/`width`/`height`/`min_size`/`resizable`,
  all defaulting to the existing desktop values) so `TouchstripWindow`
  could subclass it with different defaults
  (`status_console_ui/touchstrip.html`, ~900x230, non-resizable - a real
  touch-strip device does not resize) instead of duplicating every
  `push_*()` method. `TouchstripWindow` overrides only
  `push_system_event()`, which raises `NotImplementedError` - Scope
  explicitly excludes a dense event log from this surface, and
  `touchstrip.js` has no `appendSystemEvent()` to call.
- **Both windows can share one `StatusConsoleApi` instance** (`pywebview`
  allows binding the same `js_api` object to more than one
  `create_window()` call) - toggling Think mode or Open/Hidden on either
  surface is one real engine state change, not two independently-tracked
  copies. `manual_check_status_console.py` now opens both windows this
  way.
- `status_console_ui/contract.js` - the `RUNTIME_STATES`/`MODULE_IDS`/
  `HEALTH_STATUSES`/`EVENT_LEVELS`/`VISIBILITY_MODES` arrays, extracted
  out of `app.js` and loaded before both `app.js` and the new
  `touchstrip.js` (task-ui-06's AC: "Same state contract as desktop
  Status Console is reused" - now structurally true at the JS layer too,
  not just because `ui_contract.py` is the one Python source). Color CSS
  custom properties were *not* extracted the same way (kept duplicated in
  `touchstrip.css`) - they are static constants with no behavior to drift,
  unlike the JS validation arrays that actively gate rendering.
- `touchstrip.js`/`touchstrip.html` expose the same `applyRuntimeState()`/
  `applyModuleHealth()`/`applyModelLabel()`/`applyDataLocality()`/
  `applyThinkingMode()`/`applyVisibilityMode()` function names as `app.js`,
  so `status_console.py`'s `push_*()` methods work against either window
  unmodified - only the rendering differs (two paginated glance/actions
  screens, module status as small dots instead of chip cards, model label
  and data locality combined into one line, no event log). Context reset
  requires a 1s pointer hold (`RESET_HOLD_MS`) instead of the desktop's
  tap-then-confirm-row, matching a touch glance surface where a modal
  confirm dialog would be too much chrome; releasing early cancels
  cleanly. The Open/Hidden badge on the glance page is itself tappable
  (calling the same `set_visibility_mode()`), unlike the desktop's
  separate two-button toggle - a deliberate touch-surface simplification,
  not a second implementation of the same control.
- Deferred, per Scope's own wording ("optional... after warmup story
  lands"): an activation trigger through the orb/touch affordance. The
  activation/warmup story was moved to `tasks/backlog/` for v1.4.0 or later.
  It is explicitly not a prerequisite for v1.3.0 Control Center or v1.4.0
  file attachments. Cold starts after idle periods and the absence of
  push-to-talk/orb activation remain accepted UX debt until it lands.

Task-ui-07 landed seventh and last: consolidated visual/manual QA across
every prior task-ui-0X card together, closing
tasks/done/story-status-console-ui.md.

- **Real bug found and fixed:** `demo.html`'s inline `<style>` block set
  `body{grid-template-areas}` to the wide "main log" two-column layout
  unconditionally, which won the CSS cascade over `style.css`'s own
  `@media (max-width: 720px)` override (equal selector specificity,
  declared later in the document - the inline `<style>` tag follows
  `style.css`'s `<link>`). `demo.html` never actually exercised the
  responsive stacked layout at narrow widths - `.main` was silently
  squeezed to ~83px wide instead of stacking full-width. `index.html` (the
  real product surface) was unaffected and verified correct independently.
  Caught by measuring live layout geometry via the Preview tools during
  this task's consolidated pass, not by the existing "no horizontal
  overflow" checks (which this bug did not trip - a cramped column is not
  the same failure as literal overflow).
- `tests/test_ui_qa.py` (new) adds the checks that only make sense with
  every surface built: a directory-scan network-asset check covering every
  file in `status_console_ui/` at once (so a future new file can't skip
  the "no CDN" rule by never getting its own test), all six `RuntimeState`
  colors present on *both* `style.css` and `touchstrip.css`, and that the
  two files agree on every color (caught `touchstrip.css` inlining
  `WARMING`'s hex literally instead of referencing a named
  `--amber-warm` token - same color, but a real duplication smell fixed
  during this pass).
- **TTS/Hidden manual check (Scope item) is moot**, per task-ui-05's
  already-recorded human decision: `Hidden` never touches audio output in
  v1, so there is nothing to manually verify there.
- **Global hotkey interaction** was not re-tested against a live `main.py`
  process during task-ui-07 because `main.py` and the Status Console windows
  still did not share a process then (see task-ui-03's "deliberately not
  done" note). That became the separate task-ui-08 follow-up below.

Task-ui-08 is the follow-up live integration task for the already-completed
Status Console story.

- `python -m jarvis --status-console` launches Jarvis and the Status Console in
  one process using the same `pywebview.start(callback)` ordering verified by
  `manual_check_status_console.py`: windows and their shared
  `StatusConsoleApi` are created before `webview.start()`, then the callback
  creates the real `asyncio` runtime and calls `StatusConsoleApi.set_loop()`.
  The headless launch path remains `python -m jarvis`; `--no-touchstrip`
  opens only the desktop console.
- Live wiring intentionally pushes only state with an authoritative source:
  model label from config, `DataLocality.LOCAL`, current Think state, current
  Open/Hidden visibility state, `SystemEvent`s, and coarse runtime states
  (`WARMING`, `LISTENING`, `THINKING`, `SPEAKING`, `ERROR`). It does not
  invent module health snapshots - the story's deferred question about the
  authoritative `ModuleHealth` source remains deferred.
- The desktop console receives `SystemEvent` entries; the touchstrip shares
  Think/Open-Hidden/runtime state through the same `StatusConsoleApi` but still
  has no dense event log, matching task-ui-06's boundary.

## Architecture v1.2.4 (Status Console control plane)

See `tasks/done/story-v1.2.4-status-console-control-plane.md`. Task-1 landed
the guarded Shutdown control:

- `status_console.py`'s `StatusConsoleApi` gained `request_shutdown()`/
  `set_shutdown_event()`, the same `js_api`/`run_coroutine_threadsafe`/
  chicken-and-egg-ordering pattern as `set_loop()` (constructed before
  `main.py`'s `run()` creates the real `asyncio.Event`, wired up once it
  exists). `request_shutdown()` does no teardown itself: it publishes an
  `INFO` `SystemEvent` ("Shutdown requested via Status Console") and then
  sets the *same* `shutdown_event` the existing `Ctrl+Alt+Q` hotkey already
  sets - `run_until_shutdown()` remains the single clean-shutdown
  implementation (cancels background tasks, awaits pending TTS/sound cues,
  unsubscribes bus handlers, unregisters every hotkey listener) regardless
  of which trigger fired it, per the story's Boundary ("Shutdown must use
  the same clean path as the existing shutdown hotkey").
- `main.py`'s `run()` now creates `shutdown_event` before
  `wire_status_console()` runs (previously created later, only for the
  hotkey) and calls `live_console.api.set_shutdown_event(shutdown_event)`
  before that wiring, so both triggers reach the identical `asyncio.Event`.
- Guarded, not a bare button: the desktop shell requires a click-then-
  confirm row (`showShutdownConfirm()`/`confirmShutdown()` in `app.js`,
  same shape as the existing context-reset confirm), and the touchstrip
  requires a 2-second pointer hold (`onShutdownHoldStart()`/
  `SHUTDOWN_HOLD_MS` in `touchstrip.js`) - deliberately twice the existing
  1-second context-reset hold, and colored `--red` rather than reset's
  `--amber` on both surfaces, since stopping the whole engine is a
  strictly bigger, easier-to-regret action than clearing conversation
  history (human decision, task-1: touchstrip gets a shutdown action too,
  made hard to trigger accidentally, per the story's own "decide" framing
  rather than leaving the two surfaces' capabilities to drift apart).
- Entropy review (2026-07-09, human-requested) hardened this control plane:
  - `StatusConsoleApi` now schedules all JS-API work through one private
    `_schedule()` (replacing eight copies of the guard/`run_coroutine_
    threadsafe` pattern): it also closes the check-then-schedule race left
    by the original `_loop_is_usable()` fix (loop closing between the check
    and the call raised the same `RuntimeError` in pywebview's JS thread),
    logs exceptions from scheduled coroutines instead of dropping them with
    the discarded future, and rejects invalid `ModuleId`/`VisibilityMode`
    strings with a warning instead of raising in the JS dispatch thread.
  - A Shutdown click before `set_loop()`/`set_shutdown_event()` complete is
    remembered and dispatched once wiring finishes, never silently dropped -
    the front-end disables its Shutdown button on first click, so a dropped
    early request would have made UI shutdown permanently unreachable.
  - Closing the desktop console with the title-bar X is now a shutdown
    trigger through the same clean path (window `closed` event ->
    `api.request_shutdown()`); previously the engine kept running headless
    and every later push hit a destroyed window. Any closed window (either
    surface, any cause) marks itself closed so `push_*()` becomes a safe
    no-op. Closing only the touchstrip does not stop the engine.
  - `LiveStatusConsole` deduplicates runtime-state pushes: `SPEAKING` was
    pushed on every streamed `ResponseToken` - two blocking `evaluate_js`
    round-trips per token inside `bus.publish()`, violating bus.py's own
    handler contract. Only real transitions reach the windows now. The
    broader runtime-state ownership question is recorded in
    `tasks/backlog/task-runtime-state-tracker.md`; the `TouchstripWindow`
    `NotImplementedError` capability holes in
    `tasks/backlog/task-touchstrip-capability-composition.md`.
  - `status_console.py` no longer imports `httpx`/`sounddevice` at module
    level (only the two default option sources need them, now imported
    lazily) - the UI bridge module must be importable without pulling in
    the audio/network stacks.
- The hotkey and the Status Console's Shutdown control both close the live
  `pywebview` window(s) after the clean engine teardown completes.
  `StatusConsoleApi.request_shutdown()` still does not destroy windows or
  cancel tasks itself; it only sets the shared shutdown event. The lifecycle
  boundary lives one layer up: `main.py` awaits `run_until_shutdown()` first
  (background tasks, pending TTS/sound cues, bus subscriptions, hotkeys), then
  calls `LiveStatusConsole.close()`, which destroys the desktop and touchstrip
  windows. This makes "Завершить работу" mean the application exits, not just
  that the engine stops behind an inert UI.

Task-2 landed the configuration layering contract - `config.py`'s
`load_settings()` now merges three sources, lowest to highest precedence:

- Built-in defaults (each `*Settings` dataclass's own field defaults) <
  `config.toml` (the human-edited file, unchanged from v1.0) <
  `config.ui.toml` (a new, optional file - written only by the Status
  Console, never by a human; added to `.gitignore` alongside `config.toml`
  since both are machine-local, not committed).
- Precedence is **per key, not per file**: `load_settings(path, ui_path)`
  reads and independently validates both files' raw TOML (same
  unknown-section/unknown-key/wrong-type `ConfigError` rules as always,
  attributed to whichever file actually contains the offending key - not
  a looser or differently-validated second source of truth), then merges
  each section as `{**base_section, **ui_section}` before building the
  dataclass. A key present in `config.toml` but absent from
  `config.ui.toml` still applies - `config.ui.toml` overriding one field
  in a section does not reset the rest of that section to built-in
  defaults.
- `config.ui.toml` is entirely optional; `load_settings()`'s existing
  single-file behavior is unchanged when it is absent (the common case
  today, since nothing writes it yet - that is task-3's job).
- **Restart-to-apply, by construction, not by extra code:**
  `load_settings()` runs exactly once at startup (`main.py`'s `run()`/
  `run_with_status_console()`). Writing `config.ui.toml` while Jarvis is
  already running has no live effect until the process is restarted -
  there is no file-watching, polling, or hot-reload anywhere in this
  path, matching the story's Boundary ("Do not implement live
  reconfiguration"). No new mechanism was needed to guarantee this; it
  falls directly out of `load_settings()` already only ever being called
  once per process lifetime.
- Menu UI, and the actual model/microphone fields `config.ui.toml` writes
  in practice, are deliberately out of this task's scope (task-3's job) -
  this task only proves the layering mechanism generically, exercised in
  `tests/test_config.py` against the already-existing `backend.model`/
  `backend.num_ctx` fields.

**Code-review finding, fixed:** `load_settings()`'s `ui_path` originally
defaulted to the independently cwd-relative `DEFAULT_UI_CONFIG_PATH`
constant, not anything derived from `path`. A test (or any caller)
loading a base config from one directory while a real `config.ui.toml`
happened to sit in the process's actual working directory - exactly the
state the repo root is left in after following story-v1.2.4-task-4's
manual handoff - would silently pick up that unrelated file instead of
getting pure defaults. Fixed: `ui_path` now defaults to
`path.with_name("config.ui.toml")` (same directory as `path`, not the
cwd); production's real zero-argument call (`load_settings()`) is
unaffected, since `DEFAULT_CONFIG_PATH.with_name(...)` resolves to the
exact same path as the old constant did. The two tests loading
`config.example.toml` (whose own directory *is* the real repo root) now
explicitly pass a guaranteed-nonexistent `ui_path`, since no directory-
relative trick can isolate them from a real file that could legitimately
exist right next to that particular path. Regression test:
`tests/test_config.py::test_default_ui_path_sits_next_to_the_given_base_path`
(monkeypatches `cwd` to a decoy directory with its own `config.ui.toml`
to prove cwd is never consulted at all; confirmed failing against the
old default, passing against the fix).

Task-3 landed the configuration menu itself (model + microphone,
restart-to-apply):

- `config.py` gained `MicrophoneSettings` (`device: str = ""`, ""
  meaning sounddevice's default input device) and `write_ui_config()`
  - the full-snapshot write-side counterpart to `load_settings()`. It always
  rewrites the whole file with the configuration-menu selection and never
  opens `config.toml` - structurally unable to overwrite the human-edited
  file regardless of what path it is given. Values are `json.dumps()`-
  escaped into TOML basic strings (stdlib `tomllib` is read-only). The only
  other writer is v1.4's narrow `update_ui_config_mcp_enabled()`, which
  preserves the existing UI layer and changes only `[mcp].enabled`.
- `audio_in.py` gained `stream_factory_for_device(device)` - binds
  `config.microphone.device` into a `StreamFactory` via
  `functools.partial`, so `_default_stream_factory`'s new `device`
  parameter never has to leak into `AudioInput`'s constructor or the
  `StreamFactory` type every existing fake-injecting test already relies
  on. `main.py`'s `build_app()` uses it whenever `audio_input` is not
  injected - this is what makes microphone selection genuinely
  restart-to-apply rather than a setting nothing reads. Model selection
  needed no equivalent wiring: `backend.model` already flowed from
  `load_settings()` into `OllamaBackend` before task-2 even existed.
- `status_console.py`'s `StatusConsoleApi` gained
  `request_model_options()`/`request_microphone_options()`/
  `save_config_selection()`. Enumeration uses injectable async sources
  (real defaults: local Ollama's `GET /api/tags` with a short 3 s timeout;
  `sounddevice.query_devices()` off-loop via `asyncio.to_thread()`) and
  degrades to just the current configured value on any exception - never
  live Ollama or real devices in a pure test, and enumeration failure
  never blocks the caller (Stop Conditions). Results never reach a window
  directly from this class - matching every other piece of state here,
  they are published as bus events (`ModelOptionsAvailable`/
  `MicrophoneOptionsAvailable`) that `main.py`'s `wire_status_console()`
  turns into `push_model_options()`/`push_microphone_options()` calls.
  `save_config_selection()` writes via `write_ui_config()` and publishes
  `UiConfigSaved`, which `wire_status_console()` turns into
  `push_pending_restart(True)`.
- **Desktop-only, by Scope decision**: the config menu (and its three new
  `push_*()` methods) has no touchstrip equivalent - `TouchstripWindow`
  overrides all three to raise `NotImplementedError`, the same pattern
  already used for `push_system_event()`. The touchstrip glance surface
  stays narrow by design; a settings menu does not fit its "glance/
  actions only" boundary.
- Front-end: `index.html`/`app.js`/`style.css` gained a collapsible
  "⚙ Настройки" panel (cyan, not amber/red - saving here is not itself
  destructive, only ever touching `config.ui.toml`, applied on next
  restart). `toggleConfigMenu()` re-fetches both selectors' options every
  time the panel opens (never on close); an empty-string microphone
  option renders as "(системный микрофон по умолчанию)" in the dropdown,
  matching `MicrophoneSettings.device`'s own "" sentinel. A saved config
  shows an amber pending-restart banner immediately (no engine
  confirmation to wait for, unlike every other control here - nothing in
  the running process actually changes until the next start).

**Code-review finding, fixed:** both `<select>`s start empty (no
`<option>`s) until `request_model_options()`/
`request_microphone_options()` resolve, and "Применить" had no guard
against being clicked before then - doing so read `modelSelect.value` as
`""` and saved an empty `backend.model` into `config.ui.toml`, breaking
the next restart. Fixed on both sides: `app.js`'s `#btnConfigApply`
starts `disabled` in markup and only re-enables once both selectors have
actually loaded real options since the panel was last opened (re-armed
to disabled on every open, not just the first, since a fast reopen-then-
click could otherwise race a fresh refetch); `style.css` gives the
disabled state a visibly distinct look (dimmed, `cursor: not-allowed`) -
a technically-inert button that looks identical to an enabled one gives
no signal why clicking does nothing. `status_console.py`'s
`_save_config_selection_async()` also rejects an empty/blank model as a
Python-side backstop independent of the front-end guard (publishes a
WARN `SystemEvent`, does not write); an empty microphone device is left
unguarded, since `""` is `MicrophoneSettings.device`'s own legitimate
"system default" sentinel, never invalid. Regression tests:
`tests/test_status_console.py::test_save_config_selection_rejects_an_empty_model`,
`::test_save_config_selection_allows_an_empty_microphone_device`, plus
structural checks that the button starts disabled and only re-enables
once both selectors report loaded.

**Human manual-testing review of task-1's shutdown control found a real
bug, fixed (2026-07-07):** before live-window lifecycle closing existed,
clicking the desktop Shutdown control the first time stopped the engine but
left the `pywebview` window open and inert. From the outside this looked like
nothing had happened, and the human's follow-up second click hit an
unguarded case: `StatusConsoleApi._loop` still held a
reference to the now-closed loop (nothing ever clears it), and every
public method only ever checked `self._loop is None`, not whether it was
*closed*. `asyncio.run_coroutine_threadsafe()` on a closed loop raises
synchronously inside `call_soon_threadsafe()`, crashing pywebview's own
JS-API dispatch thread with `RuntimeError: Event loop is closed` (visible
in the terminal) instead of failing safely. Fixed by replacing every
`if self._loop is None` guard (`toggle_thinking()`, `reset_context()`,
`reset_module()`, `set_visibility_mode()`, `request_shutdown()`,
`request_model_options()`, `request_microphone_options()`,
`save_config_selection()`) with a shared `_loop_is_usable()` check
(`self._loop is not None and not self._loop.is_closed()`) - any control
clicked after the engine has already shut down is now a safe no-op
everywhere, not just for shutdown specifically. As a cosmetic layer on
top (not a substitute for the real fix above), `confirmShutdown()`
(app.js) disables the desktop Shutdown button immediately on click, and
`onShutdownHoldStart()` (touchstrip.js) ignores further holds via a
`_shutdownRequested` flag, since there is no "shutdown complete" event to
drive a real state change and a confused repeat click/hold is a real,
observed failure mode. Regression test:
`tests/test_status_console.py::
test_api_methods_are_a_safe_no_op_after_the_loop_has_closed` (confirmed
failing against the pre-fix guard, reproducing the exact live traceback,
before passing against the fix).

**Second human manual-testing finding, same session (2026-07-07): the
orb stayed stuck on `SPEAKING` ("Отвечаю") forever after the very first
turn**, even though the engine kept handling later turns correctly in
the background - the terminal log showed several complete listening ->
thinking -> speaking cycles (audible cues, successful `/api/chat` calls)
while the desktop orb never visually changed. Root cause: `wire_status_
console()` pushes `RuntimeState.SPEAKING` on a turn's first
`ResponseToken`, but nothing ever pushed the orb back afterward -
`_on_full_response_complete()` already plays `sound_cues`' own
"listening" cue correctly on every turn, but the equivalent Status
Console push was simply never written when task-ui-08 wired runtime
states live. Not related to the closed-loop crash above, and not a
regression from this story's own work - a pre-existing gap in the
already-completed Status Console UI story that this session's manual
testing happened to surface. Fixed: `wire()`'s `on_full_response_
complete` closure (`main.py`) now pushes `RuntimeState.LISTENING`
("Готов слушать") right after `_on_full_response_complete()` completes,
mirroring the same push already used right after `warm_up()` at startup.
Regression test: `tests/test_main.py::
test_wire_pushes_listening_state_after_response_complete` (confirmed
failing without the fix, passing with it).

The same report also mentioned a quick duplicate/repeated answer
immediately before the stuck orb was noticed - this matches the already-
documented, deliberately deferred self-hearing/no-echo-cancellation gap
(see this file's Verified facts, and `tasks/bug_reports/thinking-mode-
mic-window-before-autopause.md`), tracked as Roadmap item 7. No code
change made for that part; this session's fix is scoped to the stuck-orb
symptom only.

## Architecture v1.2.10 (UI transport)

v1.2.10 replaces the in-process pywebview UI bridge with one local transport
owned by the engine's asyncio loop:

- `ui_transport.py` runs an `aiohttp` HTTP+WebSocket server on `127.0.0.1`
  and port `0` (an ephemeral port). Startup issues one process-local token;
  the initial UI URL carries it and each WebSocket URL presents it again.
- Protocol v1 uses the envelope `{protocol, channel, type, payload}`.
  `control/hello` declares client identity and capabilities; the server
  replies with `control/hello_ack` and a complete `state/snapshot`.
  Subsequent state changes are `state/delta` messages. The implemented
  channels are `state` and `control`; the envelope reserves channel
  multiplexing for later audio work.
- The state projection contains runtime state, module health, data locality,
  model label, recent system events, thinking mode, visibility mode, and the
  existing configuration-menu values. Control commands call the existing
  `StatusConsoleApi` paths; the transport does not add engine behavior.
- `status_console_ui/transport.js` is the shared browser client. The desktop
  console identifies as `status-console`; the touchstrip identifies as
  `touchstrip`. `pywebview` now remains only a window shell that opens the
  server URL; all UI state and controls use the WebSocket.
- Listening on loopback is local IPC, not outbound network access. This
  remains true under the two-tier locality contract (see the top of this
  file, revised by story-v1.4.0 task 2): the UI transport is part of core,
  not a per-component external capability, so it stays covered by the
  unconditional local guarantee regardless of MCP's later per-component
  exceptions.

## Architecture v1.2.11 (UI localization)

The Status Console and Touchstrip UI chrome is localized; English is the
default UI language.

- `[ui].language` in config.py selects the UI language: `en` (default) or
  `ru`. Any other value is a ConfigError. Restart-to-apply like every other
  setting.
- Boundary: this governs UI chrome only. The dialog language - the Russian
  system prompt, the warm-up prompt, TTS output, and speech markup - is
  runtime data and is not affected by `[ui].language`.
- `ui_text.py` is the single Python-side catalog of UI-visible runtime
  strings (runtime-state labels, substatus lines, module labels, microphone
  details, `ui_message` texts). No module hardcodes UI-visible prose.
  config.py repeats the supported set/default as literals because it must
  stay free of project-module imports; a test pins the two together.
- The transport state projection carries `ui_language`; the web layer
  (`status_console_ui/strings.js`) holds the en/ru dictionary for static
  markup (`data-i18n` attributes) and JS-produced strings, defaults to
  English before the snapshot arrives, and re-stamps on snapshot.
- The demo/QA harness pages are plain English and do not use the `data-i18n`
  mechanism.
- v1.2.11 also unified the user-muted microphone detail: ui_transport.py
  previously pushed "усыплён" on live MicSleepToggled while main.py seeded
  "не используется"; both now resolve the same catalog key, keeping the
  v1.2.10 wording decision ("не используется" / "not in use").

## Architecture v1.2.12 (external dialog prompts)

The system prompt and the warm-up request text are configuration, not
source literals:

- `[prompts].system` and `[prompts].warmup` in config.py's PromptSettings;
  defaults are the previous main.py literals verbatim (Russian prompt,
  "Привет"), so a missing config keeps v1.2.11 behavior byte-identical.
- Both must be non-empty strings; empty values are a ConfigError.
- This is the dialog-language counterpart to `[ui].language` (v1.2.11):
  the two are independent. Switching the assistant's spoken language means
  replacing `[prompts]` (and, if needed, adjusting TTS routes); it does not
  touch UI chrome, and `[ui].language` does not touch prompts.
- No separate config.llm.toml: the existing layered loader already gives
  type checking, unknown-key detection, and per-key precedence; a second
  file would add a second loader for two strings.

## Architecture v1.3.0 (Control Center)

Task 2 (configuration iteration 2) landed first after the accepted IA
document (`tasks/done/control-center-v1.3.0-ia.md`):

- `ui/config_selection.py` is the single validation authority for what
  the config menu may write: `UiConfigSelection` + `validate_selection()`
  with sanity ranges for VAD (threshold exclusive (0,1), max chunk
  1-120 s, request-end pause 0.1-10 s, resume cooldown 0-10 s). The
  command handler checks payload shape/types (ProtocolError), the API
  validates semantics before writing, and the front-end mirrors the same
  ranges from snapshot data - three layers, one authority.
  - TTS routes are all-or-nothing by contract: `build_tts_engine` requires
  a customized `[tts.languages]` to cover every routed language, so the
  UI writes either both ru+en routes or nothing (Silero-only default).
    Each route form is a projection of the selected engine's complete typed
    config contract. Field types, nullable/required state, defaults, and
    numeric/non-empty constraints come from dataclass metadata shared with
    TOML validation. Silero model identifiers are not allowlisted; model/file
    compatibility still surfaces honestly at lazy load through TTS health.
  - `write_ui_config()` gained optional `[ui]`, `[vad]`, and
    `[tts.languages.*]` sections; None omits a section so the layered
    loader falls through. It remains the only config writer and still
    never touches config.toml.
    A UI TTS route containing the discriminator `engine` replaces that
    language's base variant as a unit; otherwise changing engine would mix
    fields from two dataclasses, and omitted nullable fields could not be
    cleared. A route override without `engine` retains normal per-key merge.
- The snapshot gained a `config_values` section
  (`config_values_payload()`): current values, option lists, and the
  validation ranges. The front-end renders selectors and range-checks
  from this data instead of hardcoding a second copy of the contract.
- Everything stays restart-to-apply with the existing pending-restart
  indicator; `[prompts]` editing is deliberately out of the panel.
  - The supported-set constants (`SUPPORTED_UI_LANGUAGES`,
    `SUPPORTED_TTS_LANGUAGES`, `SUPPORTED_TTS_ENGINES`) were made public
    in config.py for the selection module and payload builder.

## Architecture v1.2.14 (UI state foundation)

Task 1 (RuntimeStateTracker) landed first:

- `core/lifecycle.py` defines the engine lifecycle events: `WarmupStarted`/
  `WarmupCompleted` (published by `warm_up()`), `TurnAccepted` (published by
  `Orchestrator._start_turn()` behind its own busy guard, carrying
  `TurnSource.VOICE`/`TEXT`), and `TurnCompleted` (published by
  `_on_full_response_complete()` after `finish_turn()`'s cooldown, so
  LISTENING is never announced while the turn's speech may still be
  audible).
- `ui/runtime_state.py`'s `RuntimeStateTracker` is the single owner of
  RuntimeState transitions: it subscribes to the lifecycle events plus
  `ResponseToken`/`SystemEvent` and publishes `RuntimeStateChanged` with a
  `substatus_key` (ui_text catalog key, localized by the renderer) or
  `substatus_text` (literal, e.g. an error message). SPEAKING is only
  entered from THINKING - the warm-up request streams `ResponseToken`
  through the same bus, and the tracker is subscribed before `warm_up()`
  runs, so unguarded tokens would have shown SPEAKING during WARMING.
- Rendering is one handler in `wire_status_console()`: RuntimeStateChanged
  -> `ui_text` resolution -> transport push. `wire()`'s closures lost all
  push logic and busy-guard duplication (`not orchestrator.is_busy` is
  gone from wiring); `transport.py` no longer decides SPEAKING on tokens
  or ERROR on error system events - it projects what it is told.
- The WARMING shown at startup is the UiStateStore's initial snapshot
  value (set at construction in `run_with_status_console()`), not a
  pushed transition; the tracker takes over from `WarmupStarted` on.
- The busy-rejection contract is now testable end to end: a turn rejected
  by the Orchestrator publishes no `TurnAccepted`, so the tracker never
  announces THINKING (`test_rejected_busy_turn_does_not_render_thinking`).

Task 2 (module health events) landed second:

- `ui/module_health.py`'s `ModuleHealthTracker` is the single owner of
  module-health projection, publishing `ModuleHealthChanged(module,
  status, detail_key)`; the transport resolves the detail via `ui_text`
  in its own language and folds it into the snapshot. The transport's own
  `MicSleepToggled` health handler is gone - one mechanism for every
  module.
- Sources are strictly existing signals, no polling or probes:
  - backend: `WarmupCompleted(succeeded)` -> OK/ERROR;
    `BackendRequestFailed` (new, published by `Orchestrator._start_turn`'s
    except path) -> ERROR; `ResponseComplete` -> OK (recovery; per-module
    dedup keeps the steady state quiet);
  - TTS: `TtsSynthesisResult(language, succeeded)` (new, published by
    `TtsOutput._synthesize_and_submit` on both branches) -> OK on
    success, DEGRADED on a failed unit (playback continues, the unit is
    skipped - so not ERROR); the next success recovers;
  - vision: `ScreenshotCaptured` -> OK; `CaptureFailed` (new, published
    by `CaptureInput` where the capture exception is now caught -
    previously that exception died silently inside the hotkey thread's
    `run_coroutine_threadsafe` future) -> ERROR;
  - microphone: `MicSleepToggled` -> OK/UNAVAILABLE with the settled
    v1.2.10 wording keys.
- "Unknown before first signal" is honest by construction: the tracker
  publishes nothing until a signal arrives, and the module chips' markup
  default is `data-status="unavailable"`. Memory publishes nothing (no
  engine implementation).
- Deliberate deviation from the task card's letter: the microphone seed
  in `wire_status_console()` still calls `set_module_health` directly -
  it is the initial snapshot value (mirroring task 1's WARMING seed
  decision), not a transition; every transition goes through the
  tracker.

## Architecture v1.2.15 (configurable TTS routes)

- `TtsSettings.languages` contains a discriminated union of
  `SileroTtsSettings` and `PiperTtsSettings`; there is no untyped parameter
  bag. The selected `engine` determines the exact accepted TOML fields.
- The global `[tts].voice` field moved to each Silero route as `speaker`.
  The unused global `[tts].rate` field was removed. Either legacy field now
  raises `ConfigError` with migration guidance instead of being silently
  ignored.
- Startup parsing validates required fields, types, unknown keys, non-empty
  identifiers/paths, and broad numeric sanity only. It deliberately does not
  allowlist model identifiers or probe files.
- Both engines load lazily on first synthesis and cache a terminal load
  failure for the rest of the process. Silero's checked-in manifest is used to
  locate the selected local package/JIT asset before calling `silero_tts`, so
  a missing model cannot trigger that library's implicit network downloader.
  Piper resolves its model/config paths at the same lazy boundary.
- `TtsEngineLoadFailed(language, engine, model, message)` is the raw route
  failure signal. `ModuleHealthTracker` maps it to TTS `ERROR`; ordinary
  `TtsSynthesisResult(succeeded=False)` remains `DEGRADED`, preserving the
  distinction between an unavailable route and one skipped synthesis unit.
  The original exception is logged with its traceback at the TTS boundary;
  repeated units do not repeat the load attempt or error signal.
- Piper routes expose the installed loader options plus every field of
  `piper.config.SynthesisConfig`. Silero routes expose model language, package
  identifier, synthesis speaker/sample rate, and optional accent/yo controls.
- Runtime remains offline and restart-to-apply. `setup_tts_model.py` accepts
  `--language`/`--model` for the explicit one-time network-enabled setup step.
- TTS modules follow an inward dependency direction: `tts.py` contains only
  common contracts and orchestration, `tts_silero.py` and `tts_piper.py`
  contain concrete adapters, and `tts_factory.py` is the composition layer
  that imports both adapters. `TtsOutput` requires an already-built
  `TtsEngine`; `app.build_app()` is the production composition root.
- Human hardware verification passed on 2026-07-12 after the configurable
  route implementation and SRP module split.

## Architecture v1.2.16 (model request composition state)

- `Orchestrator` owns one metadata-only lifecycle event emitted immediately
  before each accepted `OllamaBackend.chat()` call. It is the authoritative
  statement that a backend request has begun, not a claim that inference or a
  response succeeded.
- The event carries local wall-clock timestamp, input kinds included in the
  exact current request, and total voice-audio duration where applicable. It
  never carries content, audio/image bytes, filenames, dimensions, byte
  counts, waveform samples, or retention history.
- A screenshot is listed only when its pending capture is attached to the
  accepted voice request. Clipboard is listed only for an accepted clipboard
  request. Empty and busy-rejected inputs produce no request-composition
  state.
- The UI transport projects the latest event as `last_model_request`. The
  Control Center renders the timestamp first, followed by source metadata;
  microphone awake/asleep remains module health, not request composition.
- This narrow latest-state projection is deliberately not an interaction log.
  A later metadata-only model-interaction log may reuse this event stream but
  requires its own retention, privacy, and UI decisions.

## Architecture v1.3.1 (graded reasoning mode)

See [tasks/done/story-v1.3.1-graded-reasoning-mode.md](tasks/done/story-v1.3.1-graded-reasoning-mode.md).
Replaces Architecture v1.2's boolean thinking mode (`ThinkingModeState`/
`ThinkingModeToggled`/`thinking_enabled`) end to end. Task 1 verified the
graded Ollama contract, task 2 built the typed core, task 3 wired hotkey/
logs/cues/transport, task 4 replaced the UI and completed live handoff.

- **State owner:** `thinking_mode.py`'s `ReasoningLevelState`, one instance
  constructed in `build_app()`'s composition root and shared by every
  trigger. `ReasoningLevel` is a four-value enum (`off`/`low`/`medium`/
  `high`); the state always starts at `off` and is never persisted across
  restart. `set_level(level, source=...)` (direct selection) and
  `cycle_level(source=...)` (cycling) both read-decide-write synchronously
  with no `await` in between, so a hotkey cycle issued immediately after a
  direct UI selection continues the `off -> low -> medium -> high -> off`
  order from the selected level, not from wherever cycling last left off -
  verified live and by `tests/test_status_console.py::
  test_hotkey_cycle_after_a_direct_control_center_selection_continues_from_it`.
- **Backend mapping:** `OllamaBackend.build_payload()`/`chat()` take a typed
  `reasoning_level: ReasoningLevel`. `off` sends top-level `think: false`;
  `low`/`medium`/`high` send the same-name string (`think: "low"` etc.) -
  the exact contract verified live in task 1 (Ollama 0.31.2,
  `gemma4:12b-it-qat`; see this file's Verified facts). `Orchestrator.
  _start_turn()` samples `ReasoningLevelState.level` once, synchronously,
  before the backend call - a level change during an in-flight response
  affects only the next accepted turn, never the current stream.
- **Controls, all sharing the one state owner:**
  - the existing global hotkey (`config.hotkeys.thinking_toggle`, default
    `ctrl+alt+t`) calls `cycle_level()`;
  - the desktop Control Center offers a four-option segmented control
    (Off/Low/Medium/High) that calls the `set_reasoning_level` control
    command with the clicked exact level - the selected button changes
    only from the authoritative snapshot/delta (`applyThinkingMode()`),
    never optimistically on click, and the static markup preselects
    nothing (a real bug caught live: preselecting "Off" in the HTML made
    reopening the console while running at a non-off level flash a false
    selection until the real snapshot corrected it);
  - the touchstrip keeps one compact Thinking action that calls the
    `toggle_thinking` protocol-v1 compatibility command (also
    `cycle_level()`), displaying the exact current level text.
- **Event source tagging:** `ReasoningLevelChanged(level, source)` - `source`
  is a required field (no default), set to `"HOTKEY"` by the hotkey
  callback and `"UI"` by both `StatusConsoleApi` entry points
  (`toggle_thinking()`/`set_reasoning_level()`). A live human check on
  2026-07-13 caught every caller hardcoding `"HOTKEY"` even for a Control
  Center click; the System Events panel now attributes each change to the
  channel that actually triggered it.
- **Sound feedback**, `main.py`'s single `_on_reasoning_level_changed`
  handler on every `ReasoningLevelChanged` regardless of source: `off`
  plays `thinking_off` once; `low`/`medium`/`high` play `thinking_on`
  1/2/3 times in sequential order (no new sound-cue config fields - same
  `thinking_on`/`thinking_off` files as v1.2's boolean mode). The same
  handler logs `"Reasoning level: <off|low|medium|high>"` at INFO and
  publishes a matching localized `SystemEvent` (catalog keys
  `reasoning_level_off/low/medium/high`).
- **UI transport payload:** the `thinking` state key is
  `{"level": "<value>", "is_enabled": <bool>}` - `is_enabled` is `false`
  only for `off`, kept as a derived protocol-v1 compatibility field. No UI
  surface infers the level from `is_enabled`; both surfaces read `level`
  directly.
- **Isolation rule unchanged and reverified for all four levels:**
  `message.thinking` is never read by `backend.py`'s stream loop - only
  `message.content` becomes a `ResponseToken`. Task 1's live spike (28/28
  requests) and the existing real-bus regression test
  (`tests/test_main.py::test_thinking_chunks_never_reach_tts_through_real_bus_wiring`)
  both confirm no reasoning data reaches `ResponseToken`, history, TTS, or
  any UI/log surface at any level.
- **Manual end-to-end verification (2026-07-13, human-run against a live
  Ollama endpoint): passed.** Direct selection of all four levels in
  Control Center, cycling by hotkey and touchstrip, a hotkey/touchstrip
  cycle right after a direct Control Center selection continuing from the
  selected level, audible 1/2/3 `thinking_on` sequences and the single
  `thinking_off` cue, one accepted request at each level, a level change
  mid-response applying only to the next turn, no spoken or displayed
  reasoning across text/voice/screenshot turns, and restart returning the
  level to `off` - all confirmed. The same session's review also caught
  and fixed the two bugs recorded above (source tagging, optimistic
  initial selection).

## Architecture v1.3.2 (current-turn time context)

See [tasks/done/task-v1.3.2-time-context.md](tasks/done/task-v1.3.2-time-context.md).
Gives the model situational awareness of local date/weekday/time on every
turn. Deliberately unrelated to the not-scheduled heartbeat/proactive mode
(dual-context architecture is that feature's blocker - see the 2026-07-13
project memory note); this task is current-turn only.

- **New pure module:** `time_context.py`'s `format_time_context(epoch:
  float) -> str`, no bus wiring, no project-module dependencies - same
  shape as `language_segments.py`/`speech_markup.py`. Format:
  `"{weekday_ru}, {isoformat}"`, e.g.
  `понедельник, 2026-07-13T14:35+01:00`. `datetime.fromtimestamp(epoch)
  .astimezone()` attaches the local system tzinfo; `.isoformat
  (timespec="minutes")` renders an explicit numeric UTC offset. The weekday
  name comes from a hardcoded Russian table indexed by `dt.weekday()`, not
  `strftime("%A")`/`%Z` - both depend on the OS locale/timezone-abbreviation
  table, unreliable on Windows.
- **Why an explicit numeric offset, not a bare local time or raw epoch:**
  during a DST fall-back transition the local wall clock genuinely repeats
  an hour (e.g. in the UK, 01:30 BST is chronologically before 01:15 GMT
  even though "01:30" > "01:15" as bare numbers). An explicit offset keeps
  the two instants distinguishable; a raw epoch would too, but pushes exact
  calendar/weekday arithmetic onto the model, which `gemma4:12b-it-qat` is
  not expected to do reliably.
- **Injection point:** `Orchestrator._start_turn()` (`app.py`) appends the
  formatted string as a second `system`-role message, immediately before
  the turn's `user` message (closest to the query, not buried ahead of a
  potentially long history block). `self._current_turn_history_text` stays
  exactly `history_text`; the time-context string never reaches
  `ConversationHistory.add()` - current-turn only, mirroring the existing
  `media_b64` pattern applied to time instead of images. Every turn source
  (voice, clipboard) gets this for free since both already funnel through
  `_start_turn()`.
- **Clock source:** the existing `Orchestrator._clock` constructor seam
  (`Callable[[], float] | None`, defaults to `time.time`), already used for
  `ModelRequestStarted.timestamp` - no new seam needed.
- **Known accepted limitation, not fixed here:** because history storage
  never records the time-context string, no two turns' timestamps are ever
  compared directly by the model. The one indirect leak: if a turn's spoken
  answer states a time in words (e.g. "сейчас 01:30") and that literal
  answer text is later resent as accumulated assistant history, a later
  turn taken within the same DST fall-back hour could show an
  apparently-earlier time next to that older spoken answer. Narrow window
  (once a year, one hour, only if the user is discussing time-of-day
  exactly then) - accepted as-is, the same way the project already accepts
  a documented, narrowed-but-not-eliminated echo risk elsewhere (see this
  file's Verified facts entry on echo mitigation).
- **No config toggle in this first cut.** Always on.
- **Test-fixture note:** `tests/test_main.py`'s pre-existing
  `Orchestrator` tests used tiny placeholder epoch values (e.g. `123.0`)
  for `clock=` before this task. Since `_start_turn()` now runs every
  turn's epoch through `datetime.fromtimestamp(epoch).astimezone()`, those
  tiny values broke on Windows: `datetime.astimezone()` on a naive
  datetime near the epoch resolves through the CRT `mktime()`, which
  rejects local times that convert to a pre-1970 UTC instant (`OSError:
  [Errno 22] Invalid argument`, reproduced directly against
  `datetime.fromtimestamp(123.0).astimezone()`) - never an issue for real
  `time.time()` values. Fixed by switching those fixtures to realistic
  large epoch values; not a `format_time_context()` bug.
- **Verification status:** automated suite green
  (`tests/test_time_context.py` plus `tests/test_main.py`'s new
  time-context tests). The DST fall-back test forces `Europe/London` via
  `time.tzset()` (POSIX-only) and is skipped on the Windows dev machine;
  it is expected to run on cloud CI. **Human live-Ollama verification:
  passed.** The human confirmed Jarvis correctly answers date/weekday/time
  questions against the real backend - this was also the first real test
  of the Stop Condition's open question (whether Ollama/
  `gemma4:12b-it-qat` honors a second `system`-role message in one
  `/api/chat` call the way a single combined system message would be
  honored): it does, no fallback to concatenating onto the single existing
  system message was needed.

## Architecture v1.4.0 (MCP host core)

See `tasks/done/story-v1.4.0-task-3-mcp-host-core.md`. `src/jarvis/tools/`
is the host side of MCP: client management, tool registry, the single
interception point every tool call goes through, and the switchable
module state. No model wiring, no UI - task 4 wires the registry into the
dialog path, task 5 wires a Control Center switch.

- **Persistent controller, human-approved revision (2026-07-14).** The
  task card originally intended `McpHost` to be omitted entirely from
  `App` when `[mcp].enabled` is false. Implementation review found this
  left nothing for a later live toggle (task 5's Control Center switch)
  to call - by the time the object doesn't exist, there is no `enable()`
  to invoke. `jarvis.app.build_app()` now always constructs `McpHost`,
  regardless of config. `McpHost` genuinely is a client manager - it owns
  `_client_factory`, `_clients`, and the connect/disconnect loop, not
  merely a passive state flag. The revised, narrower invariant "off
  equals the capability does not exist" rests on: at rest (status `OFF`)
  it holds no client objects and has spawned no subprocess -
  `client_factory` is invoked only from inside `enable()`. A
  config/app-construction-level test asserts exactly this: `McpHost`
  exists immediately after `build_app()` but `status == OFF`; after
  v1.6.1 the shared registry may still contain local builtin tools, which
  are not MCP clients and do not spawn subprocesses.
- **Status model: `OFF` / `CONNECTING` / `ON` / `DEGRADED` /
  `DISCONNECTING`**, not a bare enabled bool. `McpModuleStatusChanged` is
  published on every transition - the typed, authoritative signal task 5
  needs; a generic `SystemEvent` alone is not fine-grained or
  guaranteed-ordered enough for a UI to reconstruct engine state from.
  `DEGRADED` covers four distinct causes, all deliberately folded into
  one status rather than given separate states: a configured, enabled
  server that failed to connect; a canonical adapter that does not match
  the provider's discovered name/schema; a tool rejected as a name
  collision with a different, already-registered provider's tool (see
  collision policy below); and a previously-healthy provider whose
  `call_tool()` raised mid-session (a transport/session failure,
  distinguished from the provider's tool merely reporting `isError: true`
  in a normal result - only the former pulls that provider's tools from the
  registry and marks the module degraded).
- **Admission gate, not a bool read directly by `dispatch()`.**
  `McpHost` tracks `_admitting`/an in-flight count/an `asyncio.Event`
  drain signal. `disable()` closes admission synchronously (no `await`
  between the status check and the flip) before doing anything else, so
  no concurrently-running `dispatch()` call can observe a stale "open"
  gate; only after every already-admitted call finishes does teardown
  touch a client. `enable()`/`disable()` are additionally serialized by
  one `asyncio.Lock`, so two concurrent toggles (a config-driven startup
  enable racing a UI click, or two rapid clicks) cannot both run the
  connect/disconnect loop at once.
  Status-event ordering was fixed to match the gate exactly, after a
  human review round caught it publishing out of order: `enable()` opens
  admission *before* publishing `ON`/`DEGRADED` (otherwise a subscriber
  reacting to the event the instant it fires could dispatch and see "MCP
  is disabled" despite the status it just received); `disable()` closes
  admission and publishes `DISCONNECTING` *before* awaiting the drain
  (otherwise `.status` would read a stale `ON`/`DEGRADED` for the entire
  drain window even though admission was already closed).
- **Tool-name collision policy: reject, not last-write-wins.** If two
  providers declare the same tool name, the later registration is
  rejected outright and the earlier provider keeps the name - tool names
  are the model-facing namespace (task 4's flat presentation), so
  last-write-wins would make identity depend on connection order and a
  later disconnect could delete a name a different, still-connected
  provider still legitimately owns. The rejecting server is marked
  `DEGRADED`, not disconnected - its other, non-colliding tools still
  register normally.
- **Canonical provider adapters (task 6, human-approved 2026-07-14).** A
  server may declare per-process `env` and a `tool_adapters` table. An empty
  adapter table preserves the generic MCP pass-through behavior; a non-empty
  table is an allowlist keyed by upstream tool name. Each entry maps that
  provider-specific declaration to one stable public name, may replace its
  description, exposes only selected model arguments, and may inject fixed
  provider arguments. The projected public JSON schema removes fixed and
  hidden arguments and rejects additional properties. Dispatch validates the
  public arguments before publishing `ToolCallStarted`, calls the upstream
  name with fixed arguments applied, and records the actual outbound arguments
  in the typed audit event. A configured upstream tool that is absent or has
  an incompatible schema marks the module `DEGRADED`; it is never reported as
  a healthy empty capability. This keeps DDGS's `search_text` and Qdrant's
  `qdrant-find` names below the model-presentation layer.
- **DDGS reviewed multi-backend launcher (human-approved and verified
  2026-07-15).**
  Human live testing of pinned DDGS 9.14.4 showed its DuckDuckGo text backend
  returning `DDGSException('No results found.')` for a normal query. The same
  command failed outside Jarvis, isolating the problem to the provider. DDGS
  hardcodes `POST` for that backend even though its base search engine already
  supports `GET`; the upstream GET change (`deedy5/ddgs#460`) was closed
  without merging.
  `examples/mcp/ddgs_get_mcp.py` therefore changes only that text engine's
  process-local `search_method` to `GET` before starting DDGS's standard MCP
  stdio server. The GET-only retry still returned an error in human testing.
  The approved follow-up uses the explicit set from `deedy5/ddgs#390`:
  `duckduckgo,wikipedia,brave,mojeek,yahoo,yandex`. This is DDGS aggregation,
  not a strict ordered fallback: DDGS may query multiple engines, merge their
  results, and stop after satisfying `max_results`. The launcher validates
  that every reviewed engine exists, accepts a future upstream DuckDuckGo
  `GET` as a no-op, and fails explicitly if the expected backend or method
  contract disappears. It never edits the provider environment or enables
  DDGS `auto`.

  Human live verification on 2026-07-15 confirmed this fixed multi-backend
  profile working end-to-end through Jarvis. Three voice-triggered
  `web_search` calls completed with `error=False` for an English live-score
  query, a Russian exchange-rate query, and an English weather query; measured
  provider times were 1.05 s, 10.88 s, and 1.42 s. Each call was followed by a
  successful model request and spoken answer. This establishes DDGS as an
  acceptable keyless demonstration provider, not as a production-reliability
  guarantee: the upstream search contracts are unofficial and availability
  may vary. If the fixed set breaks in later use, record the concrete failure
  in a bug report; self-hosted SearXNG remains the documented replacement
  candidate.
- **Task-6 live-verification boundary (human decision, 2026-07-15).** The
  owner previously verified read-only local Qdrant end-to-end and verified the
  DDGS success path above on the same host. Those are the required live checks
  for the initial demonstration. The optional LAN profile is a reviewed
  configuration example, not a claim that a separate LAN topology was tested.
  Transport failure, `DEGRADED` state, disconnect/toggle-off races, and the
  `local`/`lan`/`internet` projection contract are verified by the pure
  automated suite with test doubles; they are not additional required
  hardware drills. This split is deliberate: v1.4.0 claims a working initial
  read-only tool demonstration and deterministic host lifecycle behavior, not
  production availability of third-party providers. Any later live mismatch
  is handled as a focused bug report rather than pre-emptively expanding the
  task-6 hardware matrix.
- **Localization.** Every `ui_message` published by `jarvis/tools/`
  goes through `jarvis.ui.text`'s catalog under the existing
  `[ui].language` contract (see Architecture v1.2.11) - `ui_language` is
  threaded from `settings.ui.language` into `McpHost`/`ToolDispatcher` at
  construction. No hardcoded prose in either module; rejection reasons in
  particular are dedicated catalog keys per reason (disabled/unknown-tool/
  tool-disabled/provider-not-connected), not a raw English string
  interpolated into a localized sentence.
- **Cancellation is handled explicitly.** `asyncio.CancelledError` does
  not subclass `Exception`. Once `ToolCallStarted` has been published,
  cancellation at any later await - including the human-readable start
  event before `call_tool()` - completes exactly one correlated outcome
  (`ToolCallFinished` + `SystemEvent`) before re-raising. Outcome
  publication itself is shielded from caller cancellation, so a partial
  pair cannot be left behind. Cancellation during server discovery also
  disconnects the just-connected client before re-raising, rolls back any
  earlier connections from the same enable attempt, clears the registry,
  and returns the host to `OFF`; a connected subprocess can never be lost
  before it reaches `_clients`.
- Typed, correlated contract for watchdog/audit consumers
  (`tasks/backlog/mcp-egress-watchdog.md`): `ToolCallStarted`/
  `ToolCallFinished` carry a shared `correlation_id`, also attached to the
  paired `SystemEvent` - a consumer must never have to parse the
  localized `ui_message` string to recover which tool, provider, or
  duration a call involved.
- **Declared MCP data boundaries (human-approved 2026-07-14).** Each
  `[mcp.servers.<name>]` declares a default `data_boundary` of `local`,
  `lan`, `internet`, or `unknown`; optional
  `[mcp.servers.<name>.tool_boundaries]` entries override that default for
  mixed-boundary servers. Omission resolves to `unknown`, never silently
  to `local` or `internet`. `McpHost` resolves the effective value while
  registering each tool, and both `ToolCallStarted` and
  `ToolCallFinished` carry it as typed `DataBoundary` data. The value is a
  declared maximum authorized reach, not evidence from packet monitoring;
  the separate egress-watchdog story may later enforce or observe it.
  Task 5's data-source projection treats `local` as on-device, `lan` and
  `internet` as leaving the machine, and `unknown` as explicitly
  unclassified. If a turn uses several tools, its display precedence is
  `internet > lan > unknown > local`; inference locality remains the
  independent `DataLocality` axis.
- `StdioMcpClient` wraps the official MCP Python SDK (`mcp>=1.28`, added
  to `requirements.txt`), imported lazily inside the connection-owner
  task started by `connect()` (matching `tts_piper.py`'s precedent) so the
  package's own dependency tree
  (starlette, uvicorn, cryptography, ...) is never pulled in while MCP is
  disabled. `list_tools()` follows `ListToolsResult.nextCursor`
  pagination; `CallToolResult.structuredContent` is preserved through to
  `ToolDispatchResult`, not dropped - both verified against the installed
  SDK's actual field names (`mcp` 1.28.1), not assumed from documentation.
- **One connection-owner task per active stdio client.** The official
  `stdio_client()` transport enters an AnyIO task-group cancel scope, which
  must exit in the same asyncio task that entered it. Startup `enable()`
  and Control Center lifecycle actions run in different tasks, so storing
  an `AsyncExitStack` in the caller and closing it later is invalid.
  `StdioMcpClient` now starts a dedicated owner task on `connect()`; that
  task enters and exits both SDK contexts, while public `connect()` and
  `disconnect()` only start, signal, and await it. This preserves the
  existing host API and makes cross-task runtime toggles safe.
- **`McpTransportError` boundary (added after a human review round caught
  the original code treating every exception from `call_tool()` as fatal
  transport death).** Read against `mcp.shared.session.BaseSession.
  send_request()`'s actual source (installed `mcp` 1.28.1): a JSON-RPC
  error reply and a request that timed out waiting for a reply are both
  raised by the SDK as `mcp.McpError` - the session is provably still
  alive in both cases, only that one request failed. A genuinely broken
  transport instead surfaces as one of anyio's own stream exceptions
  (`BrokenResourceError`/`ClosedResourceError`/`EndOfStream`) on the
  memory-object streams `stdio_client()` pumps the subprocess through.
  `StdioMcpClient.call_tool()` catches exactly that family (plus a bare
  `OSError` as a safety net) and re-raises as `McpTransportError`; every
  other exception, including `McpError`, propagates unchanged.
  `ToolDispatcher` only calls `on_transport_error()` (which degrades the
  module and pulls the provider's tools in `McpHost`) for
  `McpTransportError` specifically - a normal per-call failure now fails
  only that call (`SystemEvent` level `WARN`), while `McpTransportError`
  still gets `ERROR` and the host-level reaction. This is a best-effort
  boundary based on reading the SDK's source. Per the task-6 verification
  decision above, broken-transport degradation is covered by the automated
  host/dispatcher suite and has not been claimed as a live broken-pipe fact.
- Verified via 89 tests across `tests/test_tools_registry.py`,
  `tests/test_tools_interception.py`, `tests/test_tools_host.py`, and
  `tests/test_tools_mcp_client.py` (plus dedicated `[mcp]` config-parsing
  coverage in `tests/test_config.py` and app-construction coverage in
  `tests/test_main.py`), all with fake MCP clients/SDK transport objects -
  no real subprocess or network. Includes direct reproductions of every
  race a human review round found live (concurrent `enable()`, dispatch
  admitted mid-`disable()`, stale status during the drain window).
  `python -m pytest` passes.

## Architecture v1.4.0 (model presentation layer)

See `tasks/story-v1.4.0-task-4-model-presentation-layer.md`. The dialog path
now presents task 3's registry to Ollama and owns the bounded, current-turn
tool round trip; MCP clients remain reachable only through
`ToolDispatcher.dispatch()`.

- `[mcp].presentation_strategy` selects `native` (the measured default) or
  `prompt`; `[mcp].max_tool_calls_per_turn` is a positive integer with default
  `3`. Multiple native calls returned together execute sequentially and
  consume the same per-turn budget.
- `dialog/tool_presentation.py` owns both model-facing strategies. Native
  presentation maps each enabled `RegisteredTool` to Ollama's flat `tools`
  namespace and preserves its JSON schema verbatim. Prompt presentation adds
  a system-role declaration plus an exact one-call-or-final-answer JSON
  contract; its result follow-up uses the user role, matching the task-1
  measured fallback contract. Disabled tools are not offered.
- `OllamaBackend.iter_chat()` is the transport-only raw-chunk seam. It may
  carry a tools payload prepared by the presentation layer but never chooses
  declarations, parses calls, or dispatches. The legacy `chat()` path now
  consumes the same seam and preserves its prior payload and event behavior.
- Off/empty identity is structural: when the registry has no enabled tools,
  `ToolAwareDialog.chat()` delegates directly to the legacy `backend.chat()`
  with the original messages, media, and reasoning level. No `tools` key and
  no prompt addition exists on that path.
- Native final-answer text remains streamed to `ResponseToken` consumers as
  chunks arrive. A native response whose first semantic data is a tool call is
  buffered and never published; tool metadata and any accompanying content
  therefore cannot reach history, visible response text, or TTS. If answer
  text starts first, that response is committed as the final-answer stream and
  any later malformed tool-call metadata is ignored rather than retroactively
  turning already-spoken text into a tool round trip. Prompt-strategy JSON is
  necessarily buffered until its envelope can be parsed; only the extracted
  `final_answer` is published.
- Tool results and errors are appended only to the in-memory message list for
  the current turn. **Current-turn media must survive every stateless tool-loop
  request (human-approved correction, 2026-07-14).** Live DDGS/Qdrant testing
  disproved the original first-request-only rule: after a tool call, the next
  `/api/chat` request contained only the `[голосовое сообщение]` placeholder,
  so the model could correctly complain that it had not received audio.
  `ToolAwareDialog` now materializes media once on the original user message
  in its loop-local message copy. Every tool-result or forced-final follow-up
  therefore carries the same user media, while no media is attached to the
  assistant/tool/system messages or persisted to `ConversationHistory`. The
  repeated payload and media evaluation cost are accepted: Ollama's API is
  stateless, so dropping the originating request changes the meaning of the
  turn.
- Budget exhaustion, malformed calls, and dispatch failure append honest
  context and trigger exactly one request with native tools removed and an
  explicit no-more-tools instruction. A failed real dispatch stops that
  response's batch immediately: every later requested call is represented in
  model context as not executed, but never reaches `ToolDispatcher`. If the
  model still returns a call or a malformed response, the layer emits a short
  deterministic failure answer and completes the turn; arbitrary model output
  cannot extend the loop.
- Intermediate tool-request responses never publish `ResponseComplete`.
  Exactly the final answer does, including the existing zero-metrics fallback
  when its stream ends without `done: true`, preserving the v1.2.3 turn-
  termination guarantee.

## Architecture v1.4.0 (Control Center MCP surface)

See `tasks/done/story-v1.4.0-task-5-control-center-mcp-surface.md`. The existing
local WebSocket `state`/`control` channels now expose MCP without adding a
second transport or allowing the browser to infer engine state.

- `McpModuleStatusChanged` is the only live toggle-state authority. The UI
  sends a target boolean but does not update optimistically; snapshots and
  deltas render `off`, `connecting`, `on`, `degraded`, or `disconnecting`.
  `off` always carries an empty tool list. `on`/`degraded` may carry the
  registry's read-only tool snapshot; transition states mark entries
  unavailable.
- `StatusConsoleApi` calls `McpHost.enable()`/`disable()` on the engine loop,
  then persists the host's confirmed `enabled` result to `[mcp].enabled` in
  `config.ui.toml`. `update_ui_config_mcp_enabled()` preserves every existing
  UI override and, when the file is absent, creates only the MCP section; a
  toggle cannot materialize effective model, microphone, UI, VAD, or TTS
  values as new overrides. This is a narrow live-lifecycle exception to the
  general restart-to-apply config rule; there is still no file watcher or
  generic runtime config reload.
- The turn data-source projection resets to `local_only` on
  `ModelRequestStarted` and consumes only typed
  `ToolCallStarted.data_boundary`. Its precedence is
  `internet > lan > unknown > local`; rejected calls that never publish
  `ToolCallStarted` cannot falsely mark a turn as off-machine.
  `VisibilityMode` and inference `DataLocality` remain independent state
  fields and are never mutated by this projection.
- Tool call/outcome `SystemEvent` messages continue through the existing
  event panel. No separate audit window or untyped parsing path was added.

## Architecture v1.5.0 (dialog journal)

See [tasks/done/story-v1.5.0-dialog-journal.md](tasks/done/story-v1.5.0-dialog-journal.md).
The journal is a local, append-only record parallel to the model-facing
conversation history. It is not fed back into model context.

- Each session is stored as a JSONL event log. Events preserve source,
  timestamp, text, media references, and a reserved nullable `transcript`
  field. Voice audio and screenshots remain binary files beside the log;
  they are never embedded in JSONL.
- `JournalRecorder` queues writes away from the turn-critical path. The
  journal store and its SQLite FTS5 index are rebuildable from the raw logs.
  The index covers assistant answers only; user turns, system provenance
  events, and future transcripts are not searchable in v1.5.0.
- The journal is not passively fed back into model context. The explicit
  exception introduced by v1.5.3 is user-initiated session fork: Jarvis starts
  a new session with a verbatim, text-only tail seed from the selected source
  session, plus deterministic provenance. The source journal log is not
  appended to or rewritten.
- Search accepts an answer query and an optional date range. Russian search is
  exact/prefix matching only because SQLite FTS5 has no Russian stemming;
  morphology and semantic search remain later work.
- The Status Console exposes sessions, feeds, media, and search through the
  existing authenticated local HTTP transport. Live `journal_event` updates
  use the existing state WebSocket channel. Journal media is served through
  that transport, never through `file://` URLs.
- The Journal view is a second Status Console view with a live,
  bottom-anchored feed, HTML5 audio tiles, date/query search, safe snippet
  highlighting, and jump-to-session-context. Hidden mode replaces the whole
  view with a neutral placeholder; transport endpoints and live pushes are
  suppressed as a second privacy boundary.
- v1.5.0 ships without automatic journal retention or pruning. Logs, audio,
  and screenshots therefore grow until the user removes them manually. The
  disk-growth/privacy policy remains an explicit open question, recorded in
  [tasks/bug_reports/2026-07-17-journal-retention-policy.md](tasks/bug_reports/2026-07-17-journal-retention-policy.md).
- A separate release-preparation edge case remains open: microphone shutdown
  can race a blocking executor read. It is recorded in
  [tasks/bug_reports/2026-07-17-shutdown-microphone-executor-race.md](tasks/bug_reports/2026-07-17-shutdown-microphone-executor-race.md)
  and is outside the journal data/UI contract.

## Architecture v1.5.2 (Journal UX pack)

See [tasks/done/story-v1.5.2-journal-ux-pack.md](tasks/done/story-v1.5.2-journal-ux-pack.md).
The Journal view is now an action surface on top of the v1.5.0 journal, while
the journal's append-only normal-operation contract remains intact.

- `POST /api/journal/input` accepts typed text through the existing
  authenticated local HTTP transport. Hidden mode is enforced in the
  transport before the text reaches the orchestrator. Accepted text enters
  the shared `_start_turn()` path as `TurnSource.TEXT_INPUT`, records as a
  `dock` user journal event, and never consumes a pending screenshot.
  Empty, busy, and over-limit submissions return structured rejections; typed
  over-limit text is rejected, not truncated. The length cap reuses the
  configured clipboard cap, but clipboard semantics remain truncation with a
  marker because the source is external.
- The Journal input dock sends by button or Enter, keeps text on rejection,
  and relies on live `journal_event` pushes for the feed update. Shift+Enter
  inserts a newline. Hidden mode suppresses the whole dock with the rest of
  the Journal view.
- Assistant answers expose a UI-only copy control that copies the recorded
  answer text. Arbitrary fragments remain normal browser/WebView text
  selection plus Ctrl+C; no transport path or custom selection model exists.
- A voice turn that consumes a pending screenshot records both the WAV and
  the exact PNG bytes sent to the model on the same user journal event.
  Thumbnails render those image media references through the existing
  authenticated media endpoint; no `file://` URLs or backend resizing are
  introduced.
- `JournalStore` reports total and per-session disk usage and can delete a
  whole existing session directory. Deletion is manual, per-session, and
  explicit; no retention schedule or automatic cleanup exists in v1.5.2.
  The active-session guard lives in the transport, using the recorder's
  current session id, while the store remains a file store with no runtime
  dependency.
- The SQLite FTS index is kept consistent by targeted deletion of the
  deleted session's rows. A full rebuild remains a recovery path, not the
  routine deletion path.
- Privacy and locality boundaries are unchanged: every new endpoint uses the
  existing token-authenticated local transport and returns `hidden` while
  Hidden is active. No new network capability is added.

## Architecture v1.5.3 (Memory layer A)

See [tasks/story-v1.5.3-memory-layer-a.md](tasks/story-v1.5.3-memory-layer-a.md).
The Journal view now provides the first explicit memory-across-sessions
surface while preserving the append-only journal invariant.

- Session continuation is a fork, not in-place continuation. `POST
  /api/journal/sessions/{session_id}/fork` validates the selected source
  session through the authenticated local transport, rejects Hidden/busy/
  unknown/oversize cases structurally, clears the live model-facing history,
  and seeds a new session from the selected source session's verbatim text-only
  tail. Oldest turns are dropped first to fit `[memory].fork_seed_max_chars`;
  once a turn no longer fits, every older turn is dropped too, so the seed is
  never a middle-holed selection. A fork is rejected for oversize only when the
  newest seedable turn itself exceeds the budget. No turn is split,
  summarized, or generated.
- The fork prepends one deterministic system history line stating that this
  session continues an earlier conversation and giving the source session's end
  timestamp in the same weekday + ISO 8601 format as the current-turn time
  context. The source session log is never appended to or rewritten.
- The new journal session records exactly one `role="system"`,
  `source="fork"` provenance event with `metadata.continued_from` and the seed
  drop report. The seed report separates `skipped_events` (events with no
  model-facing text) from `excluded_events` (intentional provenance exclusions).
  Seeded user/assistant turns are not replayed aloud and are not re-recorded as
  fresh journal events.
- When forking a session that already contains provenance, `source="fork"`
  system events are retained as part of the seed chain, but
  `source="context"` blank-context markers are skipped because they only
  describe the UI boundary and do not carry source conversation content; these
  markers are counted as `excluded_events`, not `skipped_events`.
- Blank context creation is also explicit. `POST /api/journal/context/new`
  clears the live model-facing history, resamples the session-start system
  prompt/memory snapshot, and creates a new journal-visible session
  immediately with one `role="system"`, `source="context"` provenance event
  carrying `metadata.kind = "new_context"`. The next typed/voice turn appends
  to that session; no source journal session is mutated.
- `memory/self.md` and `memory/memory.md` are local UTF-8 curated files by
  default, configurable through `[memory].root`, `self_file`, `memory_file`,
  `self_max_chars`, and `memory_max_chars`. Missing or empty files inject
  nothing. Over-cap files are truncated for prompt injection only with a
  warning; the disk file is not modified by loading.
- System prompt composition is sampled at session start: process start,
  explicit blank context creation, context reset, and fork. The base
  `[prompts].system` comes first, then `self.md`, then `memory.md`, each
  inside fixed delimiters. Mid-session edits do not affect the live session
  until the next session start.
- The Journal view exposes both files through fixed-id authenticated
  `GET`/`PUT /api/memory/files/{self|memory}` endpoints and a plain-text
  memory panel. Writes are explicit, exact, cap-checked, and atomic
  temp-file-plus-replace operations; the API never accepts arbitrary paths and
  never silently writes truncated content. The local v1.5.3 write contract is
  last-write-wins across multiple clients: there is no version check or
  cross-window conflict resolution. The UI preserves edits typed into the same
  textarea while a save request is in flight.
- Hidden mode suppresses fork and memory-file surfaces in the transport and
  clears memory editor DOM content in the UI. Runtime locality is unchanged:
  all new work is local files plus the existing authenticated local transport,
  with no new network capability.

## Architecture v1.6.0 (file attachments)

See [tasks/done/story-v1.6.0-file-attachments.md](tasks/done/story-v1.6.0-file-attachments.md).
File attachments extend the Journal input dock's local turn-submission surface;
they do not add a second chat surface, hotkey, cloud upload path, or `file://`
access.

- `POST /api/journal/input` keeps the v1.5.2 JSON body contract for typed
  text and additionally accepts `multipart/form-data`. Multipart requests use a
  `text` field for optional typed text and file parts for uploaded attachments.
  Text-only multipart requests fall back to the same text-input submitter and
  return the same accepted/rejected result shape with `files: []`.
- The endpoint is local and token-authenticated like the rest of the Status
  Console transport. Hidden mode is enforced before parsing the request body,
  so hidden typed text and hidden attachment bytes cannot reach the attachment
  planner or orchestrator.
- Transport owns only the streaming guards that must happen before file bytes
  are retained in request state: total attachment bytes and attachment part
  count. File bytes count against `MAX_TOTAL_UPLOAD_BYTES_PER_TURN`; the
  multipart `text` field does not. Per-class limits, supported formats,
  text-file truncation, audio probing, and human-readable rejection reasons
  remain the attachment planner's contract.
- Uploaded filenames are treated as untrusted metadata. The transport reduces
  them to basenames before constructing `AttachmentUpload`; the planner and
  orchestrator never receive client directory paths.
- Multipart responses return final turn state at top level:
  `status: accepted|rejected` and `reason`. `files` is always present on the
  multipart path and contains one result per uploaded file with
  `status: accepted|warning|rejected`, `filename`, `class`, `warnings`, and a
  rejection `reason` when applicable. Transport-level count rejections use the
  same human-readable sentence style as planner rejections.
- The Journal input dock is the only v1.6.0 upload UI. It exposes an Attach
  button, drag-and-drop target, selected-file list with remove controls, and
  per-file result rows after the API answers. It does no client-side policy
  enforcement beyond collecting browser `File` objects; supported formats,
  byte caps, truncation, audio duration, and rejection messages remain server
  contracts. Hidden mode clears any selected files and blocks submission before
  file bytes can be sent. A document-level file drag/drop guard also prevents
  the WebView's default file-navigation behavior, including while the Journal
  dock is hidden.
- The first-iteration supported upload classes are text (`.txt`, `.md`,
  `.csv`, `.json`, `.log`), image (`.png`, `.jpg`, `.jpeg`), and audio
  (`.wav`, `.mp3`). Text is decoded as UTF-8 and capped at 20000 model-facing
  characters with an explicit truncation marker. Images are sent as-is after a
  PNG/JPEG signature sniff, with no resize/recompression dependency. Uploaded
  audio is decoded through the existing `soundfile`/`torchaudio` stack,
  normalized to 16 kHz mono WAV clips, and split into deterministic <= 30 s
  chunks up to the 90 s per-file cap.
- Human release verification on 2026-07-20 confirmed the v1.6.0 attachment
  paths through the Status Console Journal against local Ollama: text
  attachments, a real JPG image, and uploaded speech audio are accepted and
  reach the model through the intended local media path; unsupported files are
  rejected without starting a model turn; text truncation, audio chunking, and
  audio size/duration controls are visible to the user.
- Accepted image media and normalized uploaded-audio clips use the same
  current-turn `images` payload list as screenshots and microphone audio.
  Images are ordered before audio clips within an attachment turn. Attachment
  media is not stored in `ConversationHistory` and is not written as journal
  binary media; the journal records the composed text with source
  `attachment`.
- Oversize request paths for `/api/journal/input` return JSON `413`:
  `status: rejected`, `reason: request_too_large`, `actual_bytes`,
  `max_bytes`, and `files: []`. The outer aiohttp request-size guard and the
  streaming attachment-byte guard are both mapped to this JSON shape.
- The orchestrator attachment entry point returns structured
  `accepted`, `busy`, or `no_accepted_content` results. The transport maps that
  result to HTTP response state and does not inspect the orchestrator's busy
  flag directly.

## Architecture v1.6.1 (builtin tools and delegated control)

See [tasks/story-v1.6.1-builtin-tools-delegated-control.md](tasks/story-v1.6.1-builtin-tools-delegated-control.md).
Builtin tools extend the existing v1.4.0 tool path with in-process local
providers. They do not add network capability, subprocesses, or a second
dispatch path.

- Builtin tools register in the same `ToolRegistry` as MCP tools under the
  reserved provider name `builtin`. `[mcp.servers.builtin]` is rejected during
  config parsing so an external MCP server cannot claim that identity.
  `RegisteredTool.provider_kind` distinguishes `builtin` from `mcp` for the
  Control Center without changing the flat model-facing tool namespace.
- `ToolDispatcher.dispatch()` remains the single interception point for every
  model-requested tool call. It resolves the registered provider, applies a
  provider-specific admission gate, publishes the same correlated
  `ToolCallStarted` / `ToolCallFinished` audit events, and emits the paired
  localized `SystemEvent`. Builtin calls use `data_boundary = local` and
  dispatch to an in-process object; MCP calls still require an enabled MCP
  provider client.
- MCP off still means no MCP clients, no MCP server processes, and no external
  tool capability. It no longer means the shared registry is empty: builtin
  tools stay registered and callable while `McpHost.status == OFF`. MCP
  enable/disable/degraded transitions clear only MCP providers' tools and do
  not drop or duplicate builtin registrations.
- The Control Center tool list projects the shared registry. Builtin tools are
  visible with a distinct provider label, remain available when MCP is off,
  and use the same per-tool enable/disable path as MCP tools.
- Delegation is strictly allowlisted. The model may only delegate these local
  changes: set the reasoning level, append/replace `memory.md`, and
  append/replace `self.md`. Privacy-relevant controls are not delegable:
  microphone sleep, Open/Hidden visibility mode, MCP module toggles, and MCP
  server enablement remain user controls only.
- `set_reasoning_level` accepts exactly `off`, `low`, `medium`, or `high`.
  It calls the single state owner, `ReasoningLevelState.set_level(...,
  source="TOOL")`. The existing sampled-at-turn-start contract is unchanged:
  the change applies from the next accepted turn, while the current turn's
  confirmation is a normal tool round trip. UI honesty still comes from the
  existing `ReasoningLevelChanged` event.
- Memory writes use one builtin `remember` tool with explicit `file`
  (`memory` or `self`), `mode` (`append` or `replace`), and `content`
  arguments. Writes go through `MemoryFileRepository`; no tool path accepts
  arbitrary paths or bypasses the per-file caps. Append joins
  non-empty files with a deterministic blank-line separator. Successful
  replace writes first save the previous file content to the same directory as
  `memory.md.bak` or `self.md.bak`; this is a single previous-version slot,
  overwritten by the next successful replace, and reported in the tool result
  content plus structured content. Over-cap and empty-content requests return
  normal tool errors and leave the file and backup unchanged. Mid-session
  writes become part of the injected system prompt only at the next session
  start, matching the v1.5.3 memory sampling contract.

## Architecture v1.6.3 (Status Console three-tab layout)

See [tasks/done/story-v1.6.3-status-console-ui-reorg.md](tasks/done/story-v1.6.3-status-console-ui-reorg.md).
A layout story: no new engine state, no transport changes. It replaces the
accumulated scatter of buttons and inline forms with three tabs and records
the criterion that decides where a future control goes.

- **Placement is decided by the nature of the data, not by widget type.**
  `Status` is live engine state and controls that act immediately.
  `Journal` is the conversation surface. `Settings` is cold configuration,
  rarely touched. A new control is placed by that rule, not by taste or by
  which tab has room. The MCP module toggle and tool list are runtime and
  belong on Status even though they look like configuration; the model and
  microphone selectors are cold configuration and belong on Settings even
  though they sit next to runtime chips historically.
- Tabs are an unpersisted `data-view` attribute on `<html>`, the same
  mechanism the v1.5.0 journal switch already used. There is no stored tab
  preference and no engine-side view state.
- The global header - brand, `LOCAL`, `LOCAL SOURCES`, and Open/Hidden - is
  visible on every tab. The honesty axis never disappears behind tab
  switching.
- Entering Settings re-fetches model and microphone options, preserving the
  v1.2.4 fresh-on-open contract without a Settings button. The form stays
  restart-to-apply; nothing about `config.ui.toml` changes.
- Context reset exists only as the Journal's explicit "Новый контекст"
  (task-v1.5.3-8). The console's duplicate was removed; the underlying
  `reset_context` command is untouched and the Touchstrip still uses it.
- MCP *server* configuration stays in `config.toml`. The story was drafted
  assuming it was part of the inline settings form and only needed
  relocating; it never had a UI. Building one is feature work, not layout.
- **"Last request to model" is not a Journal duplicate.** The Journal labels
  each message with its source, but has no equivalent for
  `last_request_screenshot` and never shows audio duration, so this record
  is the only place the UI answers "was a screenshot sent to the model". It
  is compressed to a chip strip under the orb state, not deleted. It is
  current state from the state snapshot, not history: it survives reconnect
  and answers "what is true now", which a bounded scrolling log cannot.
- The Status column fits the default 900 px window by density, not by window
  height. The MCP tool list is bounded at 180 px with its own scroll so
  v1.6.1's builtin tools cannot displace Shutdown; raising the window
  instead would have failed on a 1080p display and would not have survived
  the next tool added.
- **The action row is deliberately not bottom-pinned.** A bottom-pinned row
  absorbs the confirmation panel's height out of the column's free space, so
  opening the confirmation moves the Shutdown button up by its own height.
  story-v1.2.10-task-5's guarantee that a confirmation never moves a primary
  action wins over the cosmetics of pinning. Do not re-add `margin-top:
  auto` here.
- `.main` scrolls, so its children carry `flex-shrink: 0`. Without it an
  overflowing column steals height from the orb while its absolutely
  positioned ring keeps its size, producing a round ring around an ellipse.

## Architecture v1.6.4 (two logs: system log and user-facing record)

See [tasks/done/story-v1.6.4-observability-and-logging.md](tasks/done/story-v1.6.4-observability-and-logging.md).
`publish_system_event()` has always taken two texts - a detailed English
`log_message` and a `ui_message` - but only half the wiring existed: logging
had no file handler, so the detailed stream lived on stderr and died with the
process, and `ui_message` never passed through the UI language catalog. This
story finishes the split rather than blurring it. **Place future logging work
by the rule below, not by which surface is easier to reach.**

- **Two logs, two audiences, and neither substitutes for the other.**
  - The *system log* is detailed, English, on disk, rotating, and is not a
    UI surface. It is what a user attaches to a problem report.
  - The *user-facing log* is the console's events panel, in the interface
    language, and it answers "what has Jarvis been doing" for the person
    using it.
- **English is correct for the system log and is not a localization gap.**
  It is an engineering artifact, on the same terms as identifiers, commit
  messages, and technical documentation. Translating it would help no one:
  the audience reading it is the audience reading the source.
- **A UI panel is not a diagnostic tool.** The events panel holds 200
  entries in memory, is cleared on every reconnect, and does not exist yet
  when a startup crash happens. Diagnosis is the file's job. This is why the
  panel's bounded budget is not a defect to be fixed by growing it.
- **Content rule, binding on both logs:** record kinds, counts, durations,
  and sizes - never payload content. No transcript text, no clipboard text,
  no image data, no attachment file contents. File names are
  payload-adjacent and stay out of the user-facing log; the system log may
  carry one only as a deliberate, documented decision in the relevant task
  card, never as a default. Automated tests pin this for the paths the story
  added, including one that pins the request payload's exact key set so a
  future content-carrying field fails rather than ships.
- **Log location and bounds are configuration, not a guessed platform
  path.** `[logging].directory` (default `logs`) follows the
  `JournalSettings.root`/`MemorySettings.root` precedent exactly.
  `max_bytes = 2000000` at roughly 90 bytes per INFO line is on the order of
  20000 lines - a long session without a rotation mid-diagnosis - and
  `backup_count = 5` caps the set near 10 MB: small enough to attach to a
  report, bounded so a long session cannot fill a disk. The setting is the
  directory, not the file name; rotation owns file naming.
- **A failure to open the log degrades to stderr with a warning.** Jarvis
  must not fail to start because it could not write a log file.
- **Locality is untouched.** A local file sink opens no socket, so under the
  two-tier runtime locality contract at the top of this file it is not a
  network capability and does not appear on the data-source axis. There is
  no log shipping, no telemetry, and no upload path; sending a log anywhere
  is always an explicit human act of attaching a file.
- **The model-request record is a typed event, not a formatted string.** The
  engine emits the modality kind and, where it has one, the duration; the UI
  localizes from the existing `last_request_*` keys. Pre-rendering engine
  side would either lose the translation or force the engine to know the
  interface language. It is a sibling payload of `system_event_payload()`
  discriminated by an `entry` field, not an extension of `SystemEvent`, so
  no existing producer changes shape.
- **One `ModelRequestSummary`, three projections, no derived duplicates.**
  The chip strip answers "what is true now" and survives reconnect; the
  panel entry answers "what happened" within a bounded history; the system
  log answers "what happened then" and survives process exit. The chip strip
  from task-v1.6.3-4 is not replaced by the panel entry - they answer
  different questions.
- **The system log's request line does not go through
  `publish_system_event()`**, and this is deliberate. That function's
  guarantee is that one occurrence reaches both sinks together; here the
  panel already has a typed localized entry, so sharing the call would
  render every turn twice - once localized, once as a raw diagnostic. The
  formatter therefore lives in its own `core/model_request_log.py` rather
  than inside `system_log.py`, whose docstring promises the opposite
  invariant. Do not "simplify" it back into the shared helper.
- The request line is written *before* the backend call, because a request
  that hangs or crashes the backend is exactly the case the file exists for.
- **Hidden mode is unchanged.** The events panel has no
  `data-visibility="hidden"` rule and stays visible, which is acceptable
  only while its entries carry modality names and nothing else. If an entry
  ever needs to say something more specific, the Hidden rules must be
  revisited first - that is a stop-and-ask, not an inline decision.

## Project verification contract (v1.2.2)

Runtime locality and CI verification are separate guarantees:

- Jarvis's core and inference have no network dependency beyond the
  configured local Ollama endpoint (see the top of this file for the full
  two-tier contract, revised by story-v1.4.0 task 2). This is unconditional
  for core and inference and is not relaxed by anything below. External
  network access exists only as an explicit, off-by-default, user-enabled
  per-component capability (MCP tools) - CI never exercises that capability
  either, per the hardware/live-Ollama exclusions below, so this rule's
  practical meaning for CI is unchanged.
- Cloud CI (GitHub Actions) is allowed, but only for the pure, hardware-free
  automated suite: installing `requirements.txt`, `requirements-dev.txt`, and
  the local package in editable mode; running `python -m ruff format --check .`,
  `python -m ruff check .`, and `python -m pytest`. CI may reach the network to
  install dependencies.
- CI must never run, and must never be extended to run: live Ollama calls,
  model downloads, anything requiring secrets, or hardware-dependent checks
  (GPU/VRAM, WebView visual review, microphone, speakers, global hotkeys,
  screen capture). Those stay human-run manual handoffs, unchanged from the
  Testing protocol in AGENTS.md.
- A green CI run proves the pure automated suite passes on a clean
  dependency install. It does not prove the runtime is free of network
  calls at run time - that remains a code-review/architecture guarantee,
  not something CI measures.

## Quality tooling contract (maintenance)

- Production Python code lives under `src/jarvis`, grouped by responsibility
  (`core`, `audio`, `inputs`, `ui`, plus `app.py`/`__main__.py`).
  `python -m jarvis` is the canonical launch command; tests and manual
  checks import the installed package, with no root-level production
  modules or `sys.path` manipulation remaining.
- Ruff (lint and format) is the enforced deterministic gate: `python -m ruff
  check .` and `python -m ruff format --check .` run in CI alongside
  `python -m pytest` (see the verification contract above). Configuration
  lives in `pyproject.toml`.
- Pyright is advisory, not a CI gate. Evaluated 2026-07-14 against the final
  `src/jarvis` layout: 313 errors across 91 files, later reduced to 274.
  The story-v1.4.0 task-3 branch reports 316 after adding the MCP test
  suite: 29 findings are in the newly added/modified MCP tests (test-double
  and optional-narrowing noise of the already classified kinds below),
  while `python -m pyright src/jarvis/tools` is clean at 0 errors.
  About 61% is structural noise from typing test doubles as concrete
  production classes and from a loosely-typed `JSONValue` union indexed
  positionally in tests; another ~18 findings come from ctypes/Win32 and
  asyncio typeshed limitations that have no practical fix. A further 39
  findings in `core/config.py`/`ui/transport.py` initially looked like a
  real gap in TTS-settings construction, but both files already validate
  every field (`ConfigError`/`ProtocolError`, with test coverage) before
  constructing the dataclass - Pyright just can't trace that generic,
  loop-driven validation statically. These are suppressed with
  `# type: ignore[arg-type]` at the 9 affected sites, matching the
  pre-existing precedent at `ui/transport.py`'s `_parse_vad()`. Run
  `python -m pyright` manually when touching config/transport parsing; it
  stays out of CI because making the remaining findings green requires a
  DI/typing redesign (protocol-based interfaces for the composition root)
  outside quality-tooling scope. Full classification:
  `tasks/done/story-quality-task-8-advisory-tool-evaluation.md`.
- Semdup is rejected. No installable package or locatable source under that
  name exists (checked PyPI and web search, 2026-07-14); this is an
  environmental blocker, not worked around. Independently, Semdup's
  documented purpose - catching semantic logic duplication introduced by
  multiple agents editing the same codebase in parallel - does not match
  Jarvis's sequential, human-supervised development model. Do not reattempt
  installation; revisit duplicate-logic tooling only under a new task card
  proposing a different, resolvable tool.

## Code entropy review practice (maintenance)

Since Semdup (semantic-duplication tooling) was rejected above, duplicated
logic that drifts silently apart is caught by manual review, not a tool
gate. Established and first applied in
`tasks/done/story-code-entropy-reduction.md`.

- **What counts as entropy:** two independent implementations of the same
  contract or invariant (a validation rule, a load-once/cache-error
  pattern) with no single source of truth enforcing them, or sibling
  classes/functions solving the same problem with diverging rigor. Risk is
  proportional to how likely the contract is to change without both sides
  being touched together.
- **What does not:** incidental structural similarity with no shared
  invariant behind it. Per this repo's core engineering principles, do not
  force an abstraction over three similar-looking but independently-varying
  lines.
- **How to look for it:** after closing a quality-tooling or architecture
  initiative, read sibling implementations side by side - parallel
  adapter/engine classes, parallel construction sites for the same data
  across layers, and functions Ruff's complexity check flags (not for the
  number, but because a nontrivial function is exactly where a second,
  independently-written copy is expensive to keep in sync). Prefer this
  over waiting for a bug report: divergence found by reading code is cheap
  to fix immediately; divergence discovered because a fix landed in only
  one sibling is a live bug.
- **First instances found and fixed:** `SileroEngine`/`PiperEngine`
  (`src/jarvis/audio/tts_silero.py`, `tts_piper.py`) independently
  reimplemented the same double-checked-locking lazy-load-and-cache-error
  pattern - extracted into `LazyAsyncLoad` in `src/jarvis/audio/tts.py`.
  `core/config.py`'s and `ui/transport.py`'s independent TTS field-type
  validation predicates were consolidated into
  `core/config.py`'s `tts_field_matches_spec()`.
- When extracting a shared implementation, preserve every call site's
  existing behavior and error messages exactly - this is refactoring, not
  a design change. A prior pass on this exact story initially changed
  `ConfigError` wording during consolidation without a test catching it;
  the fix added `tests/test_config.py::test_tts_route_type_mismatch_reports_python_type_name`,
  which locks the wording and was confirmed to fail if the bug is
  reintroduced.

## Agent/dev graph index

- Graphify is a development aid, not a Jarvis runtime dependency.
- The project graph is built exclusively through deterministic structural
  extractors. The code-only Graphify path also parses supported documentation
  formats such as Markdown when a structural extractor exists.
- Semantic LLM extraction and LLM community labeling are not part of the
  project graph pipeline. Graph construction must not contact Ollama or
  another model. Parsed documentation nodes do not replace project documents
  as sources of truth.
- `tools/graphify.ps1 update` is the normal source-change path.
  `tools/graphify.ps1 refresh` deletes generated graph output and performs a
  fresh deterministic rebuild. Source and structurally parsed documentation
  changes use the same code-only update path.
- Graph queries support source structure and code relationships only. Product
  and architectural requirements remain authoritative in project documents
  and must be read directly.

## Working agreements (for the agent)

- Hardware-dependent tests (microphone, speakers, hotkeys, VRAM) are run by
  the human. The agent writes them, hands over exact commands, and waits for
  output. Automated tests cover pure logic: bus, sentence buffering, payload
  construction, VAD chunking on prerecorded wavs.
- Git: commit before any destructive or wide-ranging change. Never delete or
  rewrite files outside the task scope without explicit confirmation.
- Follow CLAUDE.md in this repo for communication protocol and stop
  conditions.

## Roadmap after v1.0

1. emotion2vec+ intonation side channel (bus subscriber, CPU).
2. XTTS-v2 and Kokoro are parked. The v1.2.5 spike found their installation
   and startup complexity made further investigation unacceptably expensive
   for the current project boundary. This is an operability and research-cost
   decision, not a negative model-quality result. Reconsider only if their
   integration cost changes materially. Production is confirmed for the
   tested Silero/Russian plus Piper/English configuration, but the routing
   architecture imposes no language-to-engine mapping: either engine may be
   configured for either supported language with a compatible model.
3. Re-tuning the model without losing audio (mix audio samples into the
   dataset or low-rank conservative LoRA) — research task.
4. Optional GUI (dialog history window).
5. Backend evaluation: LiteRT-LM prefix caching for lower prefill latency.
6. Region highlighter for screen capture: lets the user mark a region so
   OCR questions are targeted rather than bulk extraction (see Open
   questions - OCR confabulation).
7. Real echo cancellation for audio_in.py, replacing v1.0's busy-cooldown
   mitigation *and* v1.1/task-10's mic-pause-during-speech mitigation for
   Jarvis hearing its own TTS output (see Verified facts) - both are
   still timing-window mitigations, not a device-level fix for reverb
   that outlasts the cooldown.

## Day-0 artifacts

- `manual/day0_checks.py` — verification script (fidelity / intonation / ocr / vram),
  keep in repo; rerun after any backend, model, or driver change.
