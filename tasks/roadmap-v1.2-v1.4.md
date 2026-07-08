# Roadmap: v1.2.x stabilization toward v1.4 file attachments

**Status:** Accepted roadmap.
**Branch:** codex/roadmap-v1.2-v1.3.
**Note:** roadmap scope now extends through v1.4.0; the branch name predates
the v1.4 planning addition.
**Context:** current release tag is already v1.2.1, so new roadmap work starts
at v1.2.2.

## Goal

Move Jarvis from the current v1.2.1 state toward a v1.3.0 Control Center
release and a later v1.4 file-attachment release through small,
dependency-ordered engineering releases. Each v1.2.x release should produce at
most one major architectural output. If a second major architectural decision
appears inside a release, split it into a later roadmap item instead of
expanding scope.

Runtime locality remains a core product rule: Jarvis core must not require
network access at runtime. The roadmap explicitly separates this from cloud CI
used only for pure build/test verification.

## Cross-cutting rules

1. Measurement before architectural decisions.
   Hardware-dependent decisions must be based on verified facts recorded in
   `PROJECT.md`, not on assumptions or external benchmarks.

2. Pure CI is allowed only after the project contract is updated.
   Cloud CI may install dependencies and run pure automated checks, but it must
   not run hardware tests, contact live Ollama, download models, require
   secrets, or prove anything beyond the covered test surface.

3. Runtime remains local and offline.
   One-time setup may require network, such as dependency installation or model
   download scripts. Normal Jarvis runtime must not require network access
   beyond the configured local Ollama endpoint.

4. Hardware handoffs stay manual.
   Microphone, speakers, global hotkeys, screen capture, GPU/VRAM, WebView
   visuals, and live Ollama checks are written by the agent but run and
   confirmed by the human.

5. Stop conditions are real gates.
   When a task card says to stop on a conflict, missing architectural
   capability, unclear requirement, circular dependency, infrastructure error,
   or repeated failed approach, the task stops. Do not silently turn a stop
   condition into an implementation workaround.

6. Graphify documentation refresh is explicit.
   Meaningful documentation/task-card changes should still be reflected in
   graphify, but the docs refresh can be run as a separate step because semantic
   extraction may take longer than normal code edits. For local documentation
   refresh, `gpt-oss:20b` is an acceptable faster graphify model choice while
   the team is still tuning the ritual.

## v1.2.2 - Project verification contract

Purpose: legalize and introduce pure CI without weakening the local runtime
guarantee.

Scope:

- Update `AGENTS.md` and `PROJECT.md` to distinguish runtime locality from
  cloud build/test verification.
- Add GitHub Actions for pure automated checks, initially `python -m pytest`.
- Explicitly exclude hardware/manual checks, live Ollama, model downloads,
  secrets, microphone, speakers, global hotkeys, screen capture, and GPU/VRAM
  checks from CI.
- Keep local test invocation documented as `python -m pytest`.

Acceptance criteria:

- Project docs no longer forbid CI categorically; they forbid network-dependent
  runtime behavior and hardware/live checks in CI.
- CI runs the same pure test suite expected locally.
- CI failure does not become a blocker for manual hardware handoff tasks whose
  verification cannot run in GitHub Actions.

Story/task readiness: enough data exists now. Create a dedicated story or task
card before implementation.

## v1.2.3 - Hygiene and known debts

Purpose: remove or document known reliability and honesty gaps before larger
architecture work.

Scope:

- Add a regression test and narrow fix for the backend-stream edge case where
  a stream ends without a `done: true` chunk and the orchestrator can remain
  busy forever.
- Update README known issues while the `keyboard` package is still present,
  explaining the global hotkey privacy trade-off and Administrator/global
  behavior limitations.
- Optionally add a local preflight command or script if it improves the local
  workflow after CI lands.

Boundary:

- Do not introduce a broad turn-level watchdog without first proving the
  specific completion failure mode. Prefer a small test around the stream
  completion contract.
- Do not start the HotkeyProvider migration here.

Story/task readiness: enough data exists now.

## v1.2.4 - Status Console control plane

Purpose: make the live Status Console able to control Jarvis shutdown and begin
the first limited configuration surface.

Scope:

- Complete `tasks/story-v1.2.4-task-1-shutdown-control.md`.
- Trigger the existing clean shutdown path from `StatusConsoleApi`, with a
  deliberate UI guard and visible system event when possible.
- If the existing shutdown path cannot be exposed without circular dependency
  between UI wiring and `run()` lifecycle ownership, stop and split out a small
  lifecycle controller abstraction.
- Add Configuration menu iteration 1:
  - layered config: built-in defaults, `config.toml`, then `config.ui.toml`;
  - Status Console writes only the UI config layer;
  - model selection from local Ollama `GET /api/tags`;
  - microphone selection from `sounddevice.query_devices()`;
  - restart-to-apply behavior with a visible pending-restart indicator;
  - dropdowns degrade to the current configured value when a source is
    unavailable.
- Record restart-to-apply as a project decision in `PROJECT.md`.

Boundary:

- Do not implement live reconfiguration.
- Do not fake module reset success where no engine reset API exists.
- Lifecycle controller is conditional on the shutdown task's stop condition;
  it is not assumed in advance.

Story/task readiness: shutdown card exists; configuration menu needs a new
story/task card before implementation.

## v1.2.5 - TTS engine foundation

Purpose: separate TTS engine selection from buffering/playback so future voice
quality work is measured cleanly.

Scope:

- Expose Ollama attention/cache request options through backend config before
  the spike:
  - `flash_attention`;
  - `kv_cache_type`;
  - configured values must be sent in `/api/chat` `options` alongside
    `num_ctx`.
- Add a dedicated spike task next: `manual_check_tts_engines.py`.
- The spike is a human-run measurement task, not an engine migration:
  - compare Silero, Piper, Kokoro, and XTTS-v2 where they can be installed
    locally;
  - compare quality on fixed Russian, English, mixed Latin, numbers, short
    answers, and code-like phrases;
  - measure first-sentence latency from first response token to audible
    playback;
  - measure cold load time;
  - measure peak VRAM delta while Gemma remains resident;
  - compare Ollama Gemma runs with 64K f16 KV cache and 64K q8_0 KV cache,
    including whether q8_0 frees enough resource headroom for the stronger TTS
    options without unacceptable latency or quality regressions.
- Stop after the spike script is ready and hand off exact commands to the
  human. The agent does not run hardware/GPU/live Ollama measurements.
- After human measurements, update `PROJECT.md` with verified facts before
  choosing the target TTS host, model, or migration path.
- Refactor `TtsOutput` so sentence buffering and playback orchestration remain
  there, while synthesis moves behind a `TtsEngine` interface.
- Move the current Silero implementation into `SileroEngine`.
- Keep Silero-specific normalization and Latin transliteration inside or near
  the Silero engine boundary.
- Return synthesis metadata such as sample rate through a structured
  `SynthesisResult`.
- Add config shape for `[tts] engine` and engine-specific subsections.
- Preserve existing behavior under tests before running new experiments.
- Expose typed optional Ollama generation options such as `temperature`,
  `top_p`, `top_k`, `min_p`, `repeat_penalty`, `repeat_last_n`, `seed`,
  `num_predict`, `stop`, and `draft_num_predict`, preserving existing behavior
  when unset.

Boundary:

- Do not run the spike against ad-hoc environment-only Ollama settings if the
  runtime path is meant to use request `options`.
- Do not decide multilingual product behavior before the measurements land.
- Do not implement "answer in the language of the request" in this release.
  Record that as deferred until the multilingual TTS path is chosen.
- Do not perform the TTS engine refactor until the spike results have been
  recorded in `PROJECT.md`, unless the human explicitly chooses to refactor the
  current Silero path first as a purely preparatory step.
- Do not choose generation defaults without verified local measurements.

Story/task readiness: enough data exists for a TTS foundation story; benchmark
details should be included in that story.

## v1.2.6 - HotkeyProvider migration

Purpose: remove the privacy and reliability debt from global hotkey handling.

Scope:

- Complete `tasks/story-v1.2.6-hotkey-provider-migration.md`.
- Introduce a `HotkeyProvider` interface with no Windows-specific details.
- Implement `WindowsHotkeyProvider` using `RegisterHotKey`.
- Route all existing global hotkeys through the provider:
  - screenshot full;
  - screenshot region;
  - clipboard submit;
  - mic sleep toggle;
  - thinking toggle;
  - shutdown;
  - future push-to-talk.
- Remove the `keyboard` dependency, or leave it only as an explicitly
  documented fallback with a clear privacy trade-off.
- Keep callback-thread behavior safe: the callback schedules work onto the
  asyncio loop and does not decide mutable engine state itself.

Boundary:

- Linux/X11/Wayland provider implementation is out of scope for the first
  migration.
- Manual global-hotkey behavior remains a human handoff.

Story/task readiness: existing story card is sufficient as the starting point.

## v1.2.7 - Activation and warmup

Purpose: reduce perceived first-response latency after idle periods without
weakening privacy or complicating the voice pipeline.

Scope:

- Complete the existing activation/warmup cards:
  - `tasks/story-v1.2.7-task-1-ollama-keepalive-warmup.md`;
  - `tasks/story-v1.2.7-task-2-warming-runtime-state.md`;
  - `tasks/story-v1.2.7-task-3-ptt-hotkey-trigger.md`;
  - `tasks/story-v1.2.7-task-4-orb-click-trigger.md`;
  - `tasks/story-v1.2.7-task-5-day0-checks-extension.md`.
- Add configurable Ollama `keep_alive`.
- Add async `warm_up_model()` using the existing `OllamaBackend`/`httpx` stack.
- Add WARMING state as a runtime activation state, not a privacy/cloud state.
- Buffer user speech during WARMING; do not drop it or send it before the
  model is ready.
- Add activation triggers:
  - push-to-talk through `HotkeyProvider`;
  - orb click as a universal fallback.
- Extend `day0_checks.py` for human-run timing and trigger verification.
- Record measured warmup timing in `PROJECT.md` after human confirmation.

Boundary:

- Wake word is out of scope.
- Final WARMING timeout calibration waits for measured data.
- If the HotkeyProvider migration is not complete, do not leave the project in
  a long-lived mixed-hotkey model without explicitly documenting the remaining
  privacy debt.

Story/task readiness: existing story and task cards are available.

## v1.2.8 - Multilingual speech markup

Purpose: prove a simple multilingual speech contract before changing the TTS
engine.

Scope:

- Complete `tasks/story-v1.2.8-multilingual-speech-markup.md`.
- Accept a small SSML-inspired markup contract from the LLM:
  - optional `<speak>` wrapper;
  - `<lang xml:lang="ru">...</lang>`;
  - `<lang xml:lang="en">...</lang>`.
- Parse markup into ordered language segments.
- Treat Silero's unsupported `<lang>` tag as Jarvis routing metadata, never as
  text passed directly to the TTS engine.
- Merge adjacent same-language segments and smooth punctuation/connective-only
  fragments so tiny markup spans do not produce unnatural standalone TTS calls.
- Add pure parser tests before playback wiring.
- Record manual Gemma4 markup-stability checks in `PROJECT.md`.

Boundary:

- Do not claim full SSML compatibility.
- Do not migrate to XTTS-v2, Silero multilingual, or any other new production
  TTS engine in this story.
- Do not use automatic language detection as the primary source of truth.
- Do not change display/history storage without resolving the story's open
  question about raw tagged text versus clean text.

Story/task readiness: story card exists; implementation task cards should be
created before coding.

## v1.3.0 - Control Center

Purpose: deliver the full UI/control release on top of already-built engine
capabilities.

Prerequisites:

- CI/runtime verification contract is in place.
- Known reliability/documentation debts from v1.2.3 are addressed.
- Shutdown control and configuration layering exist.
- TTS engine boundary and benchmark decisions exist.
- Hotkeys use the unified provider path.
- Activation/warmup foundations exist and measured facts are recorded.

Scope:

- Full Control Center UI on the existing Status Console design system.
- Configuration iteration 2:
  - TTS engine;
  - language;
  - voice;
  - likely VAD thresholds if the engine/config contracts support it.
- Complete data-source/data-presence axes where supported by real engine state.
- Preserve existing privacy semantics:
  - data locality is independent from system visibility mode;
  - Open/Hidden does not imply cloud/offline;
  - Hidden does not mute ordinary voice turns in v1 unless a later explicit
    product decision changes this.

Boundary:

- No new major engine architecture should be introduced inside v1.3.0. If a
  new architectural dependency appears, move it back into a v1.2.x preparation
  release.

Story/task readiness: not ready for implementation until the prerequisite
v1.2.x work lands.

## v1.4.0 - File attachments

Purpose: add deliberate file input as a new turn source, including audio files,
without weakening runtime locality or confusing file upload with live realtime
listening.

Preliminary scope:

- Add a user-visible attachment/input path after the Control Center foundation
  exists.
- Treat file upload as a new turn source, separate from microphone and
  clipboard turns.
- Support an initial focused set of file classes:
  - audio files, such as WAV/MP3/M4A, normalized and chunked into model-safe
    audio clips;
  - image files through the existing current-turn media path;
  - text files with explicit size limits and visible truncation.
- Keep media current-turn only unless a later verified design changes history
  retention.
- Preserve the verified Ollama media rule: audio and images go through the
  `/api/chat` `images` field.
- Add day0-style verification before treating uploaded audio-file behavior as a
  project fact.

Boundary:

- Do not rely on the model's self-description as a verified capability.
- Do not add broad document parsing, PDF/DOCX ingestion, or long-form media
  summarization in the first iteration unless separate task cards establish
  the boundaries.
- Do not store uploaded binary media in conversation history by default.
- Do not confuse uploaded audio-file processing with realtime microphone
  listening.

Story/task readiness: create a dedicated v1.4 story later. No v1.4 task cards
are created in this planning pass.
