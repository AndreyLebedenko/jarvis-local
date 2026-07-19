# Task v1.5.3-8: Explicit new context UI

**Status:** Completed.
**Story:** `tasks/story-v1.5.3-memory-layer-a.md`
**Depends on:** task-v1.5.3-7 human release verification.

## Summary

Make blank context creation an explicit Status Console / Journal action
instead of relying on an implicit side effect of sending the next message
after a reset or empty state.

## Context you need

- Human verification on 2026-07-19 found that the v1.5.3 memory/fork
  features work after the memory editor focus fix, but the current UX
  still hides a major state transition: a new conversation context can be
  born implicitly.
- `src/jarvis/app.py`: `Orchestrator.clear()` resets history and
  resamples the system prompt / memory snapshot.
- `src/jarvis/journal/recorder.py`: journal sessions are currently tied
  to recorded events; verify whether an explicit empty context should
  create a journal-visible provenance event.
- `src/jarvis/ui/status_console_ui/`: existing reset-context, Journal
  session list, fork/continue, and memory panel controls.
- `PROJECT.md`: update the architecture entry if the context/session
  contract changes.

## Boundary

- UI/UX and local transport semantics for starting a blank context.
- No summarization, retrieval, memory writes, or fork-seed changes.
- Do not merge this into the existing Continue action. Continuing a past
  Journal session remains a fork; starting a blank context is a separate
  command.

## Requirements

- Add a localized explicit `New context` / `Новый контекст` action.
- The action must be confirmation-gated if it would discard unsaved memory
  edits or abandon non-empty current conversation state.
- After the action succeeds, the UI must show that the active context is
  blank/new before the next user message is sent.
- If the implementation creates a journal session immediately, record a
  deterministic system/provenance event so the session is not invisible or
  ambiguous. If it deliberately does not create a journal session until the
  first turn, the UI must still visibly state that the next input will go to
  a newly created context; document that contract in `PROJECT.md`.
- Existing `Continue` / fork behavior must remain explicitly source-linked
  and must not be used as the blank-context affordance.
- Hidden mode must suppress or neutralize the control consistently with the
  Journal surface privacy rules.
- All new strings go through the localization catalog (ru/en).

## Acceptance criteria

- [x] A human can start a blank context from the UI without sending a
      message first.
- [x] The active context state is visible after creation.
- [x] Starting a blank context does not mutate any source Journal session.
- [x] Fork/Continue remains distinct from blank context creation.
- [x] Unsaved memory edits are not silently discarded.
- [x] Hidden mode behavior is covered.
- [x] `python -m pytest` and Ruff checks are green.

## Human-run verification checklist

Run from the repository root after automated checks are green:

```powershell
python -m jarvis --status-console
```

Manual pass:

- Open the Journal view and confirm `New context` / `Новый контекст` is
  visible beside the session controls.
- With no active context, type a Journal message and confirm the UI asks to
  start a new context first, keeping the typed text.
- Click `New context`, confirm if prompted, and verify a new Journal session is
  selected before sending any message.
- Confirm the selected new session contains a system/context provenance row and
  is titled `New context` in the session list.
- Send a typed message and confirm it appends to that new session.
- Start another new context and confirm the previous session log is not
  mutated.
- Switch to Hidden and confirm the control is suppressed with the Journal
  surface and the endpoint returns Hidden behavior.

Record the human result here before moving the task card to `tasks/done/`.

## Human verification result

Executed by the human on 2026-07-19.

- Full checklist passed.
- Explicit `New context` / `Новый контекст` behavior works normally.
- The Journal no longer relies on implicit typed-input context creation.
