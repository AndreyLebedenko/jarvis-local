# Story: Thinking mode

Status: Draft.

## Goal (user-facing)

Let the user toggle Ollama/Gemma thinking mode at runtime, from the same
hotkey-driven Jarvis process, without ever speaking or otherwise exposing
reasoning tokens as normal assistant output.

The feature is for occasional harder questions, not a new default answer
style. Thinking mode may be slower and more token-heavy; the user must be
able to turn it on deliberately and turn it off again without restarting
Jarvis.

## Boundaries

In scope:

- A config-backed global hotkey for toggling thinking mode.
- A runtime state bit that applies to the next accepted backend request.
- Sound-cue feedback for thinking mode on/off, following the existing
  hotkeys + sound cues interaction model.
- Ollama `/api/chat` payloads include the top-level `think` parameter.
- `message.thinking` is parsed or ignored separately from
  `message.content`; it must never be published as `ResponseToken`.
- Tests prove reasoning tokens cannot reach `ResponseToken` consumers or
  the TTS pipeline through the normal streaming path.
- Manual end-to-end verification with text, voice/audio, and screenshot
  input, run by the human because it depends on live Ollama, hotkeys,
  microphone, speakers, and screen capture.

Out of scope:

- Displaying, logging, saving, summarizing, or otherwise exposing the
  reasoning trace to the user.
- A GUI, status window, tray icon, or visible transcript.
- Per-turn prompt syntax such as "think about this" that overrides the
  hotkey state.
- Changing the system prompt to request hidden reasoning.
- Changing the default runtime behavior to always-on thinking mode.
- Backend/provider abstraction beyond the existing Ollama adapter.
- Optimizing latency or context usage beyond preserving the current
  payload/history policy.

## Acceptance criteria

- The task-card sequence below is completed and moved to `tasks/done/`.
- Automated tests cover payload construction, stream separation, runtime
  state updates, hotkey binding, config parsing, sound-cue wiring, and the
  negative guarantee that `message.thinking` never becomes `ResponseToken`.
- Hardware-dependent behavior is handed off to the human with exact manual
  commands/check steps.
- `PROJECT.md` is updated in the same change as the final architectural
  decision, including the implemented state owner, default mode, hotkey,
  cues, and the hard reasoning-token isolation rule.
- Runtime remains offline after one-time model setup; the feature adds no
  new package or network dependency.

## Task-card sequence (implementation order)

1. [task-11-thinking-backend-contract.md](task-11-thinking-backend-contract.md)
   - backend payload/stream support and isolation tests.
2. [task-12-thinking-mode-state.md](task-12-thinking-mode-state.md)
   - runtime toggle state, hotkey input, config schema, and pure wiring
   tests that do not touch hardware.
3. [task-13-thinking-mode-main-wiring.md](task-13-thinking-mode-main-wiring.md)
   - final `main.py` integration, cues, config.example, manual handoff,
   and `PROJECT.md` architecture update.

## Prior verified fact

[task-spike-thinking-mode.md](done/task-spike-thinking-mode.md) verified
locally against Ollama 0.31.1 and `gemma4:12b-it-qat` that `/api/chat`
accepts top-level `think: false` / `think: true`; with thinking enabled,
reasoning streams in `message.thinking` while final answer text remains in
`message.content`. This held for both text-only input and image input via
the existing `images` field.

This story depends on that fact. If a later manual test shows reasoning in
`message.content`, or any ambiguous stream shape, stop and do not ship
runtime wiring until the ambiguity is resolved.

## Open decisions recorded during story-card creation

- Default mode is off. Thinking mode is an explicit user-controlled tool
  because the spike showed substantially more generated tokens with
  thinking enabled, and Jarvis's voice UX depends on short latency.
- The hotkey toggles a persistent runtime state for future turns, not the
  currently in-flight request. Changing a live Ollama stream mid-response
  is out of scope and would create cancellation/partial-output questions
  unrelated to this feature.
- Reasoning traces are not exposed anywhere in this story. A later GUI or
  debug-console feature may decide to display them, but that must be a
  separate story because it changes privacy, logging, and transcript
  semantics.
- The state owner should be close to turn construction, not inside TTS.
  TTS must remain protected by receiving only `ResponseToken` content,
  with no knowledge of hidden reasoning fields.
