# Task: Solo session mode - runtime toggle isolating the current session from past ones

**Story:** none (standalone, owner request 2026-08-10, follow-up to a Q&A about
whether Jarvis can create a session that does not reach into past sessions'
data).
**Status:** Completed. Human review passed 2026-08-10; merged to main.
**Created:** 2026-08-10.
**Scope class:** engine + transport + front-end. No config default (runtime-
only toggle, like visibility mode/TTS mute).

## Summary

Three independent channels currently let Jarvis reach past-session data
regardless of "New context": automatic retrieval (`Orchestrator.
_resolve_automatic_retrieval`, always unrestricted `session_ids=()`), the
`search_history`/`read_history`/`read_history_ranges` model tools (no
session boundary enforced), and `memory.md`/`self.md` injection into the
system prompt at session start. The owner wants a live, freely toggleable
"Solo" switch: while on, the current session must not read from any other
session through any of these three channels.

## Settled sub-decisions (owner, 2026-08-10)

- **Read-side only.** Solo restricts what the CURRENT session can read.
  Turns recorded while Solo is on are journaled normally and remain
  findable by future non-Solo sessions once Solo is turned off - no
  write-side/permanent isolation, no JournalStore/corpus schema changes.
  This is explicitly a v1 boundary, not an oversight - see Boundary below.
- The toggle is a runtime-only switch (no config default), mirroring
  `VisibilityModeState`/`TtsMuteState`: starts OFF at every process start,
  freely settable/clearable at any time, never persisted.

## Proposed direction

1. **State owner** `SoloSessionState` (`src/jarvis/core/solo_session.py`):
   holds `enabled: bool`, publishes `SoloSessionChanged` on a real change
   only - same shape as `TtsMuteState`.

2. **Automatic retrieval scoping** (`Orchestrator._resolve_automatic_
   retrieval`): when solo is on, pass `session_ids=(current_session_id,)`
   into `build_automatic_retrieval_request`. If there is no current
   session id yet (no journal recorder / no session started), skip
   retrieval outright (return `(), None`) rather than falling through to
   unrestricted search.

3. **History tool scoping** (`HistoryToolProvider`, `tools/history.py`):
   gains `solo_session_state` and a `current_session_id` callable
   (mirrors `journal_active_session_id`'s existing callable pattern).
   - `search_history`: while solo, force `session_ids` to
     `(current_session_id,)` regardless of what was requested, and mark
     the result `"solo_restricted": true` so the model can honestly
     explain a narrower-than-expected result instead of silently getting
     less.
   - `read_history` / `read_history_ranges`: while solo, reject the whole
     call with a clear error if any requested reference/range/anchor
     belongs to a session other than the current one - explicit
     rejection, not folded into the existing `missing_references` signal
     (a forbidden reference is not the same fact as an absent one).

4. **Memory file scoping**: `MemoryFileLoader.compose_system_prompt` gains
   `include_memory: bool = True`; when `False`, skips `self.md`/
   `memory.md` injection entirely (base `[prompts].system` text only).
   `Orchestrator`'s `system_prompt_provider` changes shape from
   `Callable[[], str]` to `Callable[[bool], str]` (the bool is "solo
   active right now"), read at `__init__` and every `clear()` call
   (covers `start_new_context`/`fork_from_journal_session`/
   `reset_context`, the existing three session-start moments - see
   PROJECT.md's "System prompt composition is sampled at session start").
   **Boundary carried over from that existing invariant**: toggling Solo
   mid-conversation does not retroactively strip memory text already
   baked into the running system prompt - it takes effect from the next
   session-start moment, exactly like every other prompt-composition-time
   setting already behaves. Not a new limitation this task introduces.

5. **Control command** `set_solo_session_enabled` (boolean): `transport.py`
   `_dispatch_control`, `ControlApi.set_solo_session_enabled`,
   `StatusConsoleApi.set_solo_session_enabled` scheduling
   `SoloSessionState.set_enabled`, validated exactly like
   `set_tts_enabled`.

6. **Status projection**: `UiStateStore` projects a `solo_session:
   {enabled}` snapshot/delta key (own top-level key, like `tts`), driven
   by `SoloSessionChanged`.

7. **Front-end**: a "Соло" checkbox in the Journal view's sessions
   sidebar, next to "+ Новый контекст" (that sidebar is literally the
   session UI the owner asked for), non-optimistic like every other
   control here - it only flips once the real `solo_session` state delta
   comes back.

8. Update `PROJECT.md` in the same commit (new architectural facts: a
   fourth runtime state owner, the tool-rejection contract, the system-
   prompt-provider signature change).

## Boundary

- Read-side only (see Settled sub-decisions) - no write-side/permanent
  isolation, no corpus/index changes. A future task could add that if
  actually needed.
- No config default / no persistence - matches visibility mode, not TTS's
  `[tts].enabled` pattern.
- No new HealthStatus/module-health integration - Solo is a session
  policy toggle like visibility mode, not a hardware-adjacent module.
- Does not touch Hidden-mode semantics, MCP, or camera/microphone
  controls.

## Acceptance criteria

- [x] `SoloSessionState` holds enabled state and publishes its change
      event; starts OFF; freely toggleable.
- [x] While solo, automatic retrieval is scoped to the current session id
      only, or skipped entirely if there is no current session id yet.
- [x] While solo, `search_history` forces `session_ids` to the current
      session and reports `solo_restricted: true`.
- [x] While solo, `read_history`/`read_history_ranges` reject any
      reference outside the current session with a clear, explicit error
      (not folded into `missing_references`).
- [x] While solo, freshly composed system prompts (session start only)
      omit `self.md`/`memory.md`; already-running sessions are unaffected
      until their next session-start moment.
- [x] `set_solo_session_enabled` is validated and dispatched like
      `set_tts_enabled`; a bad payload raises `ProtocolError`.
- [x] The Journal sessions sidebar shows a working, non-optimistic "Соло"
      checkbox.
- [x] Pure tests cover: retrieval scoping/skip, search_history forcing +
      flag, read_history/read_history_ranges rejection, memory-file
      omission at session-start boundaries only, control validation.
- [x] `python -m pytest` passes; `ruff check` and `ruff format --check`
      are clean.

## Verification record

- `python -m pytest`: 2018 passed, 1 skipped (full suite).
- `ruff check .`: all checks passed (fixed import ordering, one E501
  line-length violation).
- `ruff format --check .`: 223 files formatted.
- Browser-preview verification: done against `index.html` directly
  (`demo.html` has never carried a Journal view - its own header comment
  says so - so there was nothing to update there). Confirmed: the "Solo"
  checkbox renders in the Journal sessions sidebar under "+ New context";
  clicking it sends `set_solo_session_enabled` with the requested value
  and immediately reverts the native checkbox to its last-confirmed
  state; simulating the real `solo_session` state delta
  (`applySoloSessionState({enabled: true})`) flips the checkbox for real.
- New pure-test coverage: `tests/test_main.py` (automatic retrieval
  scoping/skip, solo vs off, system-prompt-provider solo argument and
  its session-start-only timing, `build_app()` wiring identity),
  `tests/test_history_tools.py` (search_history force-narrowing +
  `solo_restricted` flag, read_history/read_history_ranges rejection for
  references/anchors/ranges outside the current session, both positive
  and negative cases), `tests/test_memory_files.py`
  (`include_memory=False` omits both files), `tests/test_ui_transport.py`
  / `tests/test_status_console.py` (control validation, state
  snapshot/delta projection).
- Human hardware handoff: none required - this task touches no
  hardware-adjacent path (no microphone/speaker/hotkey/screen-capture
  code).
