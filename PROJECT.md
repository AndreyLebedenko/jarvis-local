# Project: Jarvis — Local Voice/Vision Assistant

Owner: private. Workdir: repository root. Windows 11, local consumer GPU.
Goal: a fast local voice interface to an LLM, with on-demand screen capture.
Jarvis core has no runtime network dependency. The supported v1.0 backend is a
local Ollama endpoint; backend/model installation and non-local providers are
outside Jarvis core guarantees. This file is the single source of truth for
architectural decisions; update it when a decision changes.

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
  stripping bug. `tts.py`'s `transliterate_latin()` does a best-effort
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
- `tts.py` — subscribes to response sentences. Silero remains the compatible
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
  `SileroEngine` ignores it, since its transliteration fallback already covers
  non-Russian text. `PiperEngine`
  (v1.2.9 task 2) is the production adapter for local Piper `.onnx` voices:
  it validates the model file and adjacent or explicit `.json` config during
  TTS initialization, imports `piper-tts` lazily, and uses Piper's chunk API
  to write a complete wav header itself. v1.2.9 task 3 wires configured
  language routes through `BilingualTtsEngine`: `build_tts_engine()` preserves
  the existing Silero-only default when only the built-in `ru -> silero`
  route is present, and otherwise composes one child engine per configured
  language (`ru`/`en`) with clear failure for unsupported language hints.
  A non-default routing table must cover both `ru` and `en` (charset
  segmentation emits both regardless of configuration), and a silero route
  must name the one supported model (`v3_1_ru`, shared constant
  `config.SILERO_MODEL`); either violation fails at startup rather than on
  the first mismatched segment. A synthesis failure at runtime is logged
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
  part of runtime behavior. tts.py's model loader checks the local cache
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
  log warnings through standard `logging`; `main.py` configures logging to
  print those warnings to the console/stderr at runtime. This is not full
  SSML compatibility.
- `capture.py` — mss screenshots; hotkey-triggered; modes: full screen and
  region select; publishes png to the bus for inclusion in the next request.
- `sound_cues.py` — synthesizes placeholder cue tones (pure math, offline,
  no assets committed) if `config.sound_cues`' paths don't already exist,
  and plays them; fire-and-forget so a cue never adds latency to the
  request it signals about.
- `main.py` — wiring + system prompt. System prompt must enforce SHORT
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
  with a timestamp, as requested during review.
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
- `status_console.py` gained `StatusConsoleApi`, exposed to the front-end
  as `window.pywebview.api` (`js_api=` on `webview.create_window()`).
  Every public method is a plain sync callable scheduling its real async
  work via `asyncio.run_coroutine_threadsafe()` onto a given loop - the
  same race-avoidance pattern this project's hotkey listeners already use
  (`thinking_mode.py`/`audio_in.py`'s `run_hotkey_listener`), since
  `pywebview` invokes `js_api` methods from its own GUI thread, not the
  asyncio loop's thread. `loop` is optional at construction and set later
  via `set_loop()` (every method is a no-op before that): `create_window
  (js_api=...)` needs the object before `webview.start()` runs the GUI
  loop, but the real asyncio loop this object schedules onto is typically
  created *inside* the callback `webview.start()` invokes - see
  `manual_check_status_console.py` for the real ordering.
- The front-end deliberately does not optimistically flip the Think switch
  on click: `toggleThinking()` only calls the `js_api`; the switch's
  visual only ever changes via `applyThinkingMode()`, called back from the
  real `ThinkingModeToggled` event - the UI never shows a state the engine
  has not actually confirmed (story's Key Decision: "UI consumes engine
  state through explicit events/snapshots"). `window.pywebview` is
  `undefined` outside a real `pywebview` window, so every `js_api` call in
  `app.js` is guarded - `demo.html` exercises the switch/reset-confirm
  visuals directly via `applyThinkingMode()`/`showResetConfirm()` without
  a live backend.
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

- `python main.py --status-console` launches Jarvis and the Status Console in
  one process using the same `pywebview.start(callback)` ordering verified by
  `manual_check_status_console.py`: windows and their shared
  `StatusConsoleApi` are created before `webview.start()`, then the callback
  creates the real `asyncio` runtime and calls `StatusConsoleApi.set_loop()`.
  The old headless launch path remains `python main.py`; `--no-touchstrip`
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
  - the write-side counterpart to `load_settings()`, and the *only*
  writer of `config.ui.toml` anywhere in the project. It always rewrites
  the whole file with exactly `[backend].model` and `[microphone].device`
  (iteration 1 has nothing else to preserve there) and never opens
  `config.toml` - structurally unable to overwrite the human-edited file
  regardless of what path it is given. Values are `json.dumps()`-escaped
  into TOML basic strings (stdlib `tomllib` is read-only, so this avoids
  adding a TOML-writing dependency for two known-simple string fields).
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
- Listening on loopback is local IPC, not outbound network access. The
  runtime locality guarantee is unchanged: Jarvis requires no network access
  beyond the configured local Ollama endpoint.

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

## Project verification contract (v1.2.2)

Runtime locality and CI verification are separate guarantees:

- Jarvis runtime has no network dependency beyond the configured local
  Ollama endpoint (see the top of this file). This is unconditional and is
  not relaxed by anything below.
- Cloud CI (GitHub Actions) is allowed, but only for the pure, hardware-free
  automated suite: installing `requirements.txt` and running
  `python -m pytest`. CI may reach the network to install dependencies.
- CI must never run, and must never be extended to run: live Ollama calls,
  model downloads, anything requiring secrets, or hardware-dependent checks
  (GPU/VRAM, WebView visual review, microphone, speakers, global hotkeys,
  screen capture). Those stay human-run manual handoffs, unchanged from the
  Testing protocol in AGENTS.md.
- A green CI run proves the pure automated suite passes on a clean
  dependency install. It does not prove the runtime is free of network
  calls at run time - that remains a code-review/architecture guarantee,
  not something CI measures.

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

- `day0_checks.py` — verification script (fidelity / intonation / ocr / vram),
  keep in repo; rerun after any backend, model, or driver change.
