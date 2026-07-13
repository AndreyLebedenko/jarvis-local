# Story v1.3.1: Graded reasoning mode

**Status:** Completed. Verified live 2026-07-13 (human-run checklist); see
PROJECT.md's Architecture v1.3.1 section.
**Release:** v1.3.1

## User-facing goal

Replace the binary thinking-mode switch with four persistent reasoning states:
Off, Low, Medium, and High. The selected state applies to the next accepted
model request and is represented consistently by the backend request, Control
Center, touchstrip, hotkey, logs, and sound feedback.

## Product contract

- The authoritative runtime value is one of `off`, `low`, `medium`, or `high`.
- The default is `off`.
- Ollama request mapping is exact:
  - `off` sends top-level `think: false`;
  - `low` sends top-level `think: "low"`;
  - `medium` sends top-level `think: "medium"`;
  - `high` sends top-level `think: "high"`.
- The current value is sampled once when an accepted turn starts. A change
  during an in-flight response affects only the next accepted turn.
- The desktop Control Center selects a level directly.
- The existing thinking hotkey and touchstrip action cycle in this order:
  `off -> low -> medium -> high -> off`.
- Sound feedback uses the existing configured cue files:
  - `off` plays `thinking_off` once;
  - `low`, `medium`, and `high` play `thinking_on` one, two, or three times.
- Reasoning content remains private implementation data. `message.thinking`
  must never become a `ResponseToken`, reach TTS or conversation history, or
  appear in UI text, logs, or system events.

## Boundaries

In scope:

- A human-run local verification of the graded Ollama request values before
  runtime implementation.
- A typed reasoning-level value and one runtime state owner.
- Exact backend payload mapping for all four states.
- Hotkey cycling, direct UI selection, touchstrip cycling, logs, and sound
  feedback.
- UI transport snapshot and delta payloads carrying the authoritative level.
- Pure automated tests for every mapping and state transition.
- Final live-Ollama, hotkey, sound, and WebView handoff for the human.
- Updating `PROJECT.md` when the graded contract is verified and when the
  architecture is implemented.

Out of scope:

- `think: "max"`.
- Automatic level selection or escalation.
- Per-turn prompt syntax or other temporary overrides.
- Changing an in-flight backend request.
- Displaying, logging, saving, or summarizing reasoning traces.
- Changing the system prompt, generation options, history policy, or TTS
  text behavior.
- Live config reload or a persisted default reasoning-level setting.

## Acceptance criteria

- [x] The task-card sequence is completed in order.
- [x] The human-run spike confirms the exact request and response contract for
      `false`, `low`, `medium`, and `high` before implementation begins.
- [x] Every accepted request sends the value matching the sampled runtime
      level.
- [x] Control Center, touchstrip, hotkey, logs, and sound feedback all reflect
      the same authoritative level.
- [x] Tests prove that reasoning data cannot reach any normal-output consumer.
- [x] Existing media and text-history behavior remains unchanged.
- [x] Runtime remains local and adds no dependency.
- [x] Project formatting, lint, and pure tests pass.
- [x] Hardware-dependent verification is handed to and completed by the human.

## Task-card sequence

1. [story-v1.3.1-task-1-graded-reasoning-spike.md](story-v1.3.1-task-1-graded-reasoning-spike.md)
   - Verify and record the local Ollama/model contract.
2. [story-v1.3.1-task-2-reasoning-level-core.md](story-v1.3.1-task-2-reasoning-level-core.md)
   - Add the typed state and backend request mapping.
3. [story-v1.3.1-task-3-runtime-level-controls.md](story-v1.3.1-task-3-runtime-level-controls.md)
   - Wire hotkey cycling, orchestration, logs, cues, and transport controls.
4. [story-v1.3.1-task-4-graded-reasoning-ui-and-handoff.md](story-v1.3.1-task-4-graded-reasoning-ui-and-handoff.md)
   - Update both UI surfaces and complete manual verification and docs.

## Stop conditions

- Stop if any supported request value is rejected or its response stream shape
  is ambiguous.
- Stop if reasoning appears in `message.content` or any normal-output path.
- Stop if implementing levels requires changing the conversation, media, or
  TTS text contracts.
- Stop if direct selection and cycling cannot share one authoritative state
  without duplicated transition logic.

