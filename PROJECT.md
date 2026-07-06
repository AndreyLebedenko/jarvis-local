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
  inside `toggle_user_sleep()` on the event loop, never in the keyboard
  callback thread. All three fixes have regression tests confirmed to
  fail without the fix and pass with it.

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
- `run_microphone_loop()` reuses the *same* `sd.InputStream` across
  sleep/wake cycles via its own `.stop()`/`.start()` rather than
  reconstructing it (avoids wake-up latency), and blocks on
  `self._awake.wait()` while asleep instead of busy-polling.
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
  `keyboard_module`/`read_clipboard`).
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
  `run_coroutine_threadsafe` from the keyboard package's own thread) can
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

## Architecture v1.3 (Status Console contract, in progress)

See [tasks/story-status-console-ui.md](tasks/story-status-console-ui.md).
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
   mitigation *and* v1.1/task-10's mic-pause-during-speech mitigation for
   Jarvis hearing its own TTS output (see Verified facts) - both are
   still timing-window mitigations, not a device-level fix for reverb
   that outlasts the cooldown.

## Day-0 artifacts

- `day0_checks.py` — verification script (fidelity / intonation / ocr / vram),
  keep in repo; rerun after any backend, model, or driver change.
