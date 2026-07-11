# Roadmap: v1.2.x stabilization toward v1.4 MCP and v1.5 file attachments

**Status:** Accepted roadmap.
**Branch:** codex/roadmap-v1.2-v1.3.
**Note:** roadmap scope now extends through v1.5.0; the file name and branch
name predate the later planning additions. v1.4.0 (MCP) and v1.5.0 (file
attachments) were swapped by an explicit human decision: MCP unlocks
capabilities that are otherwise impossible (web search, database access),
while attachments improve ergonomics of input paths that already have
workarounds (screen capture for images, microphone for audio).
**Context:** current release tag is already v1.2.1, so new roadmap work starts
at v1.2.2.

## Goal

Move Jarvis from the current v1.2.1 state toward a v1.3.0 Control Center
release, a v1.4.0 MCP integration release, and a later v1.5.0
file-attachment release through small, dependency-ordered engineering
releases. Each v1.2.x release should produce at
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
   Note: this wording is pre-v1.4.0. The v1.4.0 locality contract revision
   (`tasks/story-v1.4.0-task-2-locality-contract-revision.md`) supersedes it
   with the two-tier contract - core and inference local unconditionally;
   external access only as a per-component capability, off by default,
   user-enabled, user-visible - and rewrites this rule in the same change.
   Until that task lands, the unconditional wording remains in force.

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

- Completed: `tasks/done/story-v1.2.6-hotkey-provider-migration.md`.
- Introduce a `HotkeyProvider` interface with no Windows-specific details.
- Implement `WindowsHotkeyProvider` using `RegisterHotKey`.
- Route all existing global hotkeys through the provider:
  - screenshot full;
  - screenshot region;
  - clipboard submit;
  - mic sleep toggle;
  - thinking toggle;
  - shutdown.
- Require future push-to-talk to reuse `HotkeyProvider` when that deferred
  feature is implemented.
- Remove the `keyboard` dependency, or leave it only as an explicitly
  documented fallback with a clear privacy trade-off.
- Keep callback-thread behavior safe: the callback schedules work onto the
  asyncio loop and does not decide mutable engine state itself.

Boundary:

- Linux/X11/Wayland provider implementation is out of scope for the first
  migration.
- Manual global-hotkey behavior was verified by the human without elevation.

Story/task status: completed.

## Backlog for v1.4.0+ - Activation and warmup

Decision: deferred from v1.2.7. This work is not a prerequisite for v1.3.0
Control Center, v1.4.0 MCP integration, or v1.5.0 file attachments. Until it
lands, cold starts after
idle periods and the absence of push-to-talk/orb activation remain accepted UX
debt.

Purpose: reduce perceived first-response latency after idle periods without
weakening privacy or complicating the voice pipeline.

Scope:

- Complete the existing activation/warmup cards:
  - `tasks/backlog/activation-warmup-task-1-ollama-keepalive-warmup.md`;
  - `tasks/backlog/activation-warmup-task-2-warming-runtime-state.md`;
  - `tasks/backlog/activation-warmup-task-3-ptt-hotkey-trigger.md`;
  - `tasks/backlog/activation-warmup-task-4-orb-click-trigger.md`;
  - `tasks/backlog/activation-warmup-task-5-day0-checks-extension.md`.
- Add configurable Ollama `keep_alive`.
- Add async `warm_up_model()` using the existing `OllamaBackend`/`httpx` stack.
- Add WARMING state as a runtime activation state, not a privacy/cloud state.
- Buffer user speech during WARMING; do not drop it or send it before the
  model is ready.
- Add activation triggers:
  - push-to-talk through `HotkeyProvider`;
  - orb click as a universal fallback.
- Extend `manual/day0_checks.py` for human-run timing and trigger verification.
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

## v1.2.10 - UI transport

**Status:** Complete. Transport implementation, human visual/browser handoff,
and Task 5 cosmetic polish are accepted.

Purpose: move all UI surfaces onto one local HTTP+WebSocket transport as the
architectural prerequisite for the v1.3.0 Control Center, aligned with the
component-model direction in `VISION.md`.

Scope:

- Complete `tasks/done/story-v1.2.10-ui-transport.md`.
- Local server (aiohttp) in the engine asyncio loop: loopback bind,
  ephemeral port, one-time token.
- Protocol v1: hello/handshake with client capability declaration; `state`
  channel (snapshot plus deltas over `ui_contract.py` values); `control`
  channel (think toggle, reset, module reset, shutdown, visibility, and the
  existing configuration-menu commands). Envelope reserves channel
  multiplexing for later audio channels.
- Status Console and touchstrip migrate to the WS transport with visual
  parity; the `evaluate_js`/`js_api` bridge is removed; pywebview remains a
  window shell opening the loopback URL.
- Manual handoff verifies real windows and a Chrome client on the same URL.
- `PROJECT.md` records the transport decision and the loopback locality
  clarification: listening on loopback is not outbound network access.

Boundary:

- Loopback only. LAN binding, pairing/mTLS, audio channels, and multi-host
  operation are out of scope.
- `bus.py` is unchanged; the server is a bus client, not a distributed bus.
- No visual changes to existing surfaces beyond the explicit Task 5 cosmetic
  polish.

Story/task readiness: story complete; all v1.2.10 task cards are under
`tasks/done/`.

## v1.3.0 - Control Center

Purpose: deliver the full UI/control release on top of already-built engine
capabilities.

Prerequisites:

- CI/runtime verification contract is in place.
- Known reliability/documentation debts from v1.2.3 are addressed.
- Shutdown control and configuration layering exist.
- TTS engine boundary and benchmark decisions exist.
- Hotkeys use the unified provider path.
- v1.2.10 UI transport is complete: all surfaces on the local HTTP+WS
  server, `evaluate_js`/`js_api` bridge removed.

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

Story/task readiness: deferred to `tasks/backlog/`. The previous task-card
sequence was removed; replan the story before implementation.

## v1.4.0 - MCP integration

Purpose: give Jarvis its first tool-use capability class through MCP -
web search, database access, and other externally provided functions -
with Jarvis acting as the MCP host, the module fully switchable, and the
locality contract revised explicitly rather than eroded silently.

Preliminary scope:

- Tool-calling spike as a hard gate before the story:
  - measure native Ollama `tools` calling against a prompt-based contract
    on the local model, on a fixed task set;
  - record verified reliability facts in `PROJECT.md` before choosing the
    presentation strategy;
  - the speech-markup contract instability report is the precedent that
    makes this measurement mandatory, not optional.
- Locality contract revision as an explicit task, not a side effect:
  - core and inference remain local unconditionally;
  - external access is a per-component capability, off by default,
    enabled explicitly by the user, and visible in the data-source axis;
  - update `PROJECT.md`, `VISION.md`, and cross-cutting rule 3 in the
    same change.
- Jarvis is the MCP host: it connects to MCP servers as registered
  tool-provider components (see `VISION.md` component model) and decides
  how tools are presented to the model. Ollama sees only per-request tool
  declarations; MCP servers never talk to Ollama.
- Presentation to the model is a swappable layer: native `tools` field
  where the model template supports it, prompt-based declaration as the
  fallback; the spike decides the default.
- The MCP module is switchable:
  - off by default;
  - when off, no MCP server connection is opened and no tool declarations
    reach the model - equivalent to the capability not existing;
  - state survives restart via the layered config.
- Control Center integration:
  - an MCP toggle with clear on/off indication of the current state;
  - external tool calls reflected honestly in the data-source axis;
  - nice-to-have, not release-blocking: a read-only list of registered
    and currently available tools/functions, as a view over the
    component registry.
- Initial tool set is small and high-value (for example web search and a
  local/LAN database), each behind its own capability boundary.

Boundary:

- No silent high-impact actions; every external call is user-visible.
- All tool calls flow through a single interception point in the host; a
  later watchdog/policy component attaches there without rewiring. Tool
  dispatch must not be scattered across call sites.
- Tool results are current-turn context; no background or autonomous tool
  loops in the first iteration.
- Jarvis-as-MCP-server (exposing Jarvis's own capabilities outward) is out
  of scope.
- If the spike shows unreliable tool calling on the local model, stop and
  re-plan the release before writing story task cards.

Story/task readiness: story and task cards exist
(`tasks/story-v1.4.0-mcp-integration.md`, tasks 1-6). The task-1 spike may
start before v1.3.0 completes; tasks 5-6 need the Control Center.

## v1.5.0 - File attachments

Purpose: add deliberate file input as a new turn source, including audio files,
without weakening runtime locality or confusing file upload with live realtime
listening.

Preliminary scope:

- Add a user-visible attachment/input path after the Control Center and MCP
  foundations exist.
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
- Treating MCP tool results/resources as attachments is deferred until both
  features exist; the turn-source contract should not preclude it.

Story/task readiness: story card exists as
`tasks/story-v1.5.0-file-attachments.md`. No task cards are created in this
planning pass.
