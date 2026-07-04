# Project: Jarvis — Local Voice/Vision Assistant

Owner: Andrey. Workdir: `D:\AI\Jarvis`. Windows 11, RTX 5070 Ti (16 GB VRAM), 32 GB RAM.
Goal: a fast, fully offline voice interface to a local LLM, with on-demand screen
capture. No network dependency at runtime. This file is the single source of
truth for architectural decisions; update it when a decision changes.

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

## Open questions (unverified - do not assume an answer)

- **Media on a non-final message in multi-turn history.** day0_checks.py
  and backend.py's payload construction are only verified for a single
  message carrying media (the day-0 case: one user turn, media on that
  turn). Whether `gemma4:12b-it-qat` attends to, ignores, or errors on
  media attached to an earlier (non-final) message in a multi-turn
  `messages` array has never been tested. Needs a day-0-style experiment
  (two-turn conversation; second turn asks a question about the first
  turn's audio/image) before task-07 relies on resending media in history.
- **Prefill cost / history retention policy for media.** If raw media
  bytes (screenshots especially) are kept verbatim in history and resent
  on every subsequent turn, prefill time and context usage could grow
  quickly across a long conversation. A trimming/retention policy (e.g.
  strip media from all but the most recent turn, or replace older turns
  with a text-only summary) is likely needed. Decide during task-07 and
  replace this bullet with the resolution.
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
  (llama-server / LiteRT-LM) with one config line.
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
- `capture.py` — mss screenshots; hotkey-triggered; modes: full screen and
  region select; publishes png to the bus for inclusion in the next request.
- `main.py` — wiring + system prompt. System prompt must enforce SHORT
  conversational answers (latency ∝ answer length) and Russian by default.

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
2. XTTS-v2 expressive TTS.
3. Re-tuning the model without losing audio (mix audio samples into the
   dataset or low-rank conservative LoRA) — research task.
4. Optional GUI (dialog history window).
5. Backend evaluation: LiteRT-LM prefix caching for lower prefill latency.
6. Region highlighter for screen capture: lets the user mark a region so
   OCR questions are targeted rather than bulk extraction (see Open
   questions - OCR confabulation).

## Day-0 artifacts

- `day0_checks.py` — verification script (fidelity / intonation / ocr / vram),
  keep in repo; rerun after any backend, model, or driver change.
