# Story: v1.1 - Controlled input

Status: Completed.

## Goal (user-facing)

Give the user explicit runtime control over how Jarvis receives input,
without adding a GUI. v1.1 centers on a clipboard-to-prompt hotkey for
source code and long text, plus a privacy-oriented microphone sleep mode.
The assistant remains hotkey-driven, gives sound-cue feedback for state
changes, and keeps in-flight responses speaking to completion.

## Boundaries

In scope:

- Clipboard-to-prompt: a global hotkey sends the current clipboard text as
  the next user message.
- Clipboard input must avoid screenshots for readable text/code and must
  preserve the existing text-only history policy.
- Microphone sleep mode: a global hotkey pauses microphone capture for
  privacy and later resumes it.
- Sleep mode must not interrupt an in-flight backend request or TTS
  response; the current turn finishes normally.
- Sound cues for clipboard submission, sleep, wake, and any recoverable
  input error.
- Config entries for the new hotkeys and cue paths, following the existing
  strict config validation style.

Out of scope:

- Thinking-mode product wiring. That depends on
  [task-spike-thinking-mode.md](../task-spike-thinking-mode.md), which is
  parallel research for a later story, not a v1.1 dependency - see
  "Parallel research" below.
- Read-only dialog history window. It is deferred; see
  [backlog-history-window.md](../backlog-history-window.md).
- Text input UI, prompt editor, or chat window.
- ASR/transcription of spoken user utterances.
- Echo cancellation.
- Interrupting/canceling an in-flight response.
- Automatically pausing the microphone during Jarvis's own speech as a
  stronger echo-mitigation than the current busy-cooldown (Roadmap #7).
  task-09 builds a user-triggered sleep/wake mechanism only; using it
  internally for this purpose is a distinct cross-module control path
  (Orchestrator commanding AudioInput, not just responding to a user
  hotkey) and must be an explicit decision, not something task-09 or
  task-10 does silently - see task-10's "Open decision" section.

## Acceptance criteria

- The v1.1 task-card sequence below (task-08, task-09, task-10 - not the
  parallel-research spike) is completed and moved to `tasks/done/`.
- Automated tests cover pure logic for clipboard input events, payload
  construction/history behavior, microphone sleep-state transitions, config
  parsing, and wiring.
- Hardware-dependent behavior is handed off to the human with exact manual
  commands/check steps: clipboard hotkey, microphone sleep/wake hotkey,
  sound cues, and live end-to-end behavior with Ollama/TTS.
- Runtime remains offline after one-time model setup; no network dependency
  is introduced.
- `PROJECT.md` is updated in the same change as any architectural decision
  that changes the verified project model.

## Task-card sequence (implementation order)

1. [task-08-clipboard-input.md](task-08-clipboard-input.md) -
   clipboard-to-prompt event, clipboard reader, and Orchestrator refactor.
2. [task-09-microphone-sleep-mode.md](task-09-microphone-sleep-mode.md) -
   privacy-oriented microphone pause/resume.
3. [task-10-v1.1-main-wiring.md](task-10-v1.1-main-wiring.md) - real
   hotkey registration, final wiring, cues, config, and manual handoff for
   the v1.1 runtime.

## Parallel research (not on v1.1's critical path)

- [task-spike-thinking-mode.md](../task-spike-thinking-mode.md) - a manual
  experiment that is prerequisite only for a *future* thinking-mode
  story/task. It does not block, and is not blocked by, task-08/09/10 -
  none of v1.1's own deliverables consume its findings. Originally
  listed as step 1 of the implementation order above; that was a
  story-card mistake (a false critical-path dependency) and has been
  corrected. Run it whenever convenient relative to the rest of v1.1;
  v1.1 is complete once task-08/09/10 are done regardless of this task's
  status.

## Open decisions recorded during story-card creation

- Clipboard input is the central v1.1 feature because it is immediately
  useful, avoids unreliable screenshot OCR for text/code, and fits the
  existing hotkey + event-bus interaction model without requiring a GUI.
- Sleep mode is defined as privacy mode, not merely an orchestration gate.
  The microphone stream should pause or stop while asleep rather than
  continuously listening and discarding recognized utterances.
- The read-only history window is not part of v1.1. The current runtime
  does not have a transcript source for spoken user utterances; solving
  that has architectural consequences and belongs to a later story.
- Clipboard access uses `pyperclip`, not Tkinter: reusing Tkinter for
  clipboard reads would inherit the same thread-safety hazard already
  caught live in capture.py's region-select overlay (see
  `tasks/bug_reports/capture-region-select-tkinter-thread-safety.md`).
  `pyperclip` is a small, cross-platform, easily-fakeable dependency;
  `win32clipboard` (native, but adds `pywin32` and ties the code more
  tightly to Windows) was considered and rejected for this reason, even
  though the project is already Windows-first.
- Clipboard text is length-capped (`task-08`'s `max_chars`, default
  ~20000-30000 characters) and truncated with a visible in-band marker
  plus an error/warning cue on overflow - never silently truncated and
  never sent unbounded. An accidental multi-megabyte paste (e.g. a log
  file) is a real risk to local-context latency/cost, and a silent cut
  would let the model reason from an incomplete document without anyone
  knowing.
- Orchestrator's per-turn logic (busy-guard, thinking/speaking cues,
  history recording) must be factored into one shared turn-start path
  used by both the existing audio flow and the new clipboard flow, not
  duplicated. See task-08's "Current boundary" for the concrete
  requirement.
- A clipboard submission never consumes a pending screenshot: if one was
  captured before the clipboard hotkey is pressed, it stays pending for
  the next *audio* turn rather than being attached to the clipboard turn
  or discarded. This is a user-facing behavior choice, not just an
  implementation detail - a screenshot taken "for" a voice question
  should not silently get attached to an unrelated pasted-code question
  that happens to arrive first. See task-08's "Current boundary" for the
  concrete requirement.
