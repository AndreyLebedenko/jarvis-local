# Project: Jarvis — Local Voice/Vision Assistant

Owner: private. Workdir: repository root. Windows 11, local consumer GPU.
Goal: a fast local voice interface to an LLM, with on-demand screen capture.
Jarvis core has no runtime network dependency. The supported v1.0 backend is a
local Ollama endpoint; backend/model installation and non-local providers are
outside Jarvis core guarantees. This file is the single source of truth for
architectural decisions; update it when a decision changes.

## Verified facts (day-0 experiments, July 2026 — do not re-litigate)

- Backend: **Ollama**, model **`gemma4:12b-it-qat`** (Gemma 4 12B, encoder-free
  unified multimodal: text + image + audio in one backbone).
- **Audio and images both reach the model via the `images` field** of
  `/api/chat` (base64). A dedicated `audio` field is silently dropped by
  Ollama — never use it.
- Audio input: max 30 s per clip, 16 kHz mono wav. Place media before text
  in the prompt.
- Audio fidelity: verified — model transcribed Russian speech verbatim.
- **Intonation/prosody classification is unreliable in this quant** (detects
  that deliveries differ, misclassifies which is which). Decision: v1.0 is
  words-only. An `emotion2vec+` side-channel module (CPU-capable) is a planned
  v1.x plug-in via the event bus; do not build it into v1.0.
- Measured performance: load ~0.3 s (warm), audio prefill ~0.1–0.3 s,
  generation ~87 tok/s. VRAM under load: ~10.9/16 GB → ~5 GB headroom for TTS.
- Context: `num_ctx: 65536` (verified to fit; if VRAM pressure appears, first
  try `OLLAMA_KV_CACHE_TYPE=q8_0`, then drop to 32768).
- Owner's fine-tuned gemma4 variant **lost audio capability** during tuning
  (unified weights — text-only tuning shifts audio pathways). It is parked.
  Do not use it. Behavioral customization goes into the system prompt instead.
- Screenshot OCR: use high visual token budget (1120) for screen text; if
  small fonts garble, use region-select capture at full resolution rather
  than raising the budget.
- **Global hotkeys (`keyboard` package) require the process to run
  elevated (Administrator) on Windows.** Verified live: without
  elevation, `add_hotkey` callbacks only fire while the app's own window
  has focus - not globally, from whatever app the user is actually using
  when they press the hotkey. With an elevated terminal, hotkeys fire
  from any application, as intended. Jarvis's entire hotkey-driven
  interaction model (PROJECT.md: "Hotkeys + sound cues only") depends on
  this working globally, so the process must run elevated - see task-07's
  backlog notes for the operational consequence.
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

## Open questions (unverified - do not assume an answer)

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
  genuinely cold Ollama start (see Verified facts).
- `audio_utils.py` — shared wav-encoding helper. No project-module
  dependencies, used by both `audio_in.py` and `tts.py` so neither input
  nor output depends on the other for it.
- `audio_in.py` — microphone capture + silero-vad; end-of-utterance detection;
  chunks ≤ 30 s; publishes wav chunks to the bus.
- `tts.py` — subscribes to response sentences; Silero TTS (Russian) for v1.0;
  XTTS-v2 as a later quality upgrade. Sentence-level streaming is mandatory:
  buffer LLM tokens to sentence boundary → synthesize → play, while
  generation continues. Target end-to-end response start: within ~3 s of
  audio_in.py publishing the finished utterance (i.e. after VAD's
  request_end_pause_seconds confirm-delay - not from the literal instant
  speech physically stopped), covering audio prefill + first-sentence
  generation + TTS synthesis of that sentence. `request_end_pause_seconds`
  (`config.vad`) is a separate, tunable cost paid before this window
  starts: 2.0 s is a deliberately conservative value for the development
  stage; production is expected to tighten it to ~1.0-1.5 s once
  request-boundary behavior is validated (see task-04's audio_in.py).
  Loading the Silero TTS model requires network on first use (like
  `ollama pull` for the backend model) - a one-time setup step via
  `setup_tts_model.py`, run once before the offline runtime starts; not
  part of runtime behavior. tts.py's model loader checks the local cache
  explicitly and raises a clear error instead of silently reaching for
  the network if the one-time setup hasn't been run. `transliterate_latin()`
  converts Latin-script text to a crude phonetic Cyrillic approximation
  before synthesis, since Silero's symbol set has no Latin characters at
  all (see Verified facts) - applied after `normalize_numbers()`.
- `capture.py` — mss screenshots; hotkey-triggered; modes: full screen and
  region select; publishes png to the bus for inclusion in the next request.
- `sound_cues.py` — synthesizes placeholder cue tones (pure math, offline,
  no assets committed) if `config.sound_cues`' paths don't already exist,
  and plays them; fire-and-forget so a cue never adds latency to the
  request it signals about.
- `main.py` — wiring + system prompt. System prompt must enforce SHORT
  conversational answers (latency ∝ answer length) and Russian by default.
  Conversation history is text-only in v1.0 (see Open questions); media is
  attached only to the current turn. Warms Ollama up with a throwaway
  request before subscribing anything to the bus, so the response isn't
  spoken or recorded. Checks for Administrator elevation at startup and
  warns (does not refuse to start) if missing, since global hotkeys
  degrade to window-focus-only without it (see Verified facts).
  `Orchestrator.finish_turn()`'s cooldown (`config.vad.
  request_end_pause_seconds` after speech ends) mitigates the no-echo-
  cancellation risk of Jarvis hearing its own voice (see Verified facts) -
  it is not a substitute for real echo cancellation, which v1.0 does not
  attempt.

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
2. XTTS-v2 expressive TTS - also the answer to v1.0's Latin-script
   limitation (`transliterate_latin()`'s crude phonetic approximation,
   e.g. "gemma" -> "гемма"): XTTS-v2 (Coqui) supports 17 languages
   including Russian and English natively in one local model, no network
   at runtime once weights are downloaded. ~2 GB VRAM at FP16 for
   inference (comfortable within the ~5 GB headroom left after
   gemma4:12b-it-qat loads - PROJECT.md's day-0 numbers); RTF ~0.3
   (faster than real-time), first-audio latency ~150-400 ms depending on
   GPU - compatible with the sentence-level-streaming requirement. Not a
   drop-in fix for code-switching: language is set per synthesis call, so
   a sentence mixing Russian and English still needs the text segmented
   by language first and each segment synthesized with the matching
   language tag - but each segment would be genuinely correctly
   pronounced, not transliterated. Alternatives noted but less
   established than XTTS-v2: MOSS-TTS (2026, claims strong multilingual
   synthesis via language tags) and Chatterbox (9 languages incl.
   Russian). Deliberately deferred past v1.0 to avoid scope creep;
   v1.0's transliteration heuristic already covers the worst case
   (silence) reasonably well.
3. Re-tuning the model without losing audio (mix audio samples into the
   dataset or low-rank conservative LoRA) — research task.
4. Optional GUI (dialog history window).
5. Backend evaluation: LiteRT-LM prefix caching for lower prefill latency.
6. Region highlighter for screen capture: lets the user mark a region so
   OCR questions are targeted rather than bulk extraction (see Open
   questions - OCR confabulation).
7. Real echo cancellation for audio_in.py, replacing v1.0's busy-cooldown
   mitigation for Jarvis hearing its own TTS output (see Verified facts).

## Day-0 artifacts

- `day0_checks.py` — verification script (fidelity / intonation / ocr / vram),
  keep in repo; rerun after any backend, model, or driver change.
