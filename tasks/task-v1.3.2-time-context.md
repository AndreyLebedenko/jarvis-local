# Task: Inject current-turn time context for the LLM

**Status:** Ready for implementation.
**Release:** v1.3.2

## Summary

Give the model situational awareness of the current local date, weekday, and
time on every turn, without confusing this with the deliberately unplanned
proactive/heartbeat mode (Jarvis initiating dialog on its own - see the
project memory note recorded 2026-07-13: dual-context architecture is the
blocker for that feature, and it is intentionally not scheduled). This task
is scoped to the current turn only: no background triggers, no cross-turn
time reasoning, no config toggle in the first cut.

## Decision

- **Injection point:** `Orchestrator._start_turn()` in `src/jarvis/app.py`.
  Today it builds:

  ```python
  messages = [{"role": "system", "content": self._system_prompt}]
  messages.extend(self._history.as_messages())
  messages.append({"role": "user", "content": history_text})
  self._current_turn_history_text = history_text
  ```

  Add one more message, immediately before the user turn (closest to the
  query, not buried at the top ahead of a potentially long history block):

  ```python
  messages.append({"role": "system", "content": format_time_context(self._clock())})
  messages.append({"role": "user", "content": history_text})
  ```

  `self._current_turn_history_text` stays exactly `history_text`, unchanged -
  the time-context string must never reach `ConversationHistory.add()`. This
  mirrors the already-verified `media_b64` pattern (current-turn only, never
  resent) applied to time instead of images.
- **Clock source:** reuse the existing `self._clock` constructor seam
  (`Callable[[], float] | None`, defaults to `time.time`), already used for
  `ModelRequestStarted.timestamp`. No new seam needed; tests inject a fake
  clock the same way existing turn tests already do.
- **New pure module:** `src/jarvis/dialog/time_context.py`, one function:
  `format_time_context(epoch: float) -> str`. Pattern matches the project's
  existing small pure modules (`language_segments.py`, `speech_markup.py`):
  no bus wiring, no project-module dependencies, fully unit-testable in
  isolation.
- **Format:** `"{weekday_ru}, {isoformat}"`, e.g.
  `понедельник, 2026-07-13T14:35+01:00`.
  - `datetime.fromtimestamp(epoch).astimezone()` attaches the local system
    tzinfo; `.isoformat(timespec="minutes")` renders an explicit numeric UTC
    offset computed straight from `tzinfo.utcoffset()`.
  - Weekday name comes from a small hardcoded Russian list indexed by
    `dt.weekday()`, not `strftime("%A")` and not `%Z`: both depend on the OS
    locale/timezone-abbreviation table, which is not reliably available on
    Windows (see the `%Z` reliability concern raised and accepted during
    this feature's design discussion).
- **Why an explicit numeric offset, not a bare local time or raw epoch:**
  during a DST fall-back transition the local wall clock genuinely repeats
  an hour (verified reasoning during design: e.g. in the UK, 01:30 BST is
  chronologically before 01:15 GMT even though "01:30" > "01:15" as bare
  numbers). A bare local time can appear to run backward across that hour;
  an explicit offset keeps the two instants distinguishable. Raw epoch would
  also avoid the ambiguity, but pushes exact calendar/weekday arithmetic onto
  the model, which `gemma4:12b-it-qat` is not expected to do reliably; a
  formatted string with the weekday already spelled out avoids that failure
  mode entirely.
- **Known accepted limitation, not fixed here:** because history storage
  never records the time-context string, no two turns' timestamps are ever
  compared directly by the model. The one indirect leak: if a turn's spoken
  answer states a time in words (e.g. "сейчас 01:30") and that literal answer
  text is later resent as accumulated assistant history, a later turn taken
  within the same DST fall-back hour could show an apparently-earlier time
  next to that older spoken answer. This is a narrow window (once a year, one
  hour, only if the user is discussing time-of-day exactly then) and is
  accepted as-is, the same way the project already accepts a documented,
  narrowed-but-not-eliminated echo risk elsewhere (see PROJECT.md's Verified
  facts entry on echo mitigation). Record this limitation in the PROJECT.md
  note for this task, do not attempt to fix it here.
- **No config toggle in this first cut.** Always on. If a future need
  appears (e.g. deterministic test transcripts against real Ollama), add a
  `[prompts]`-adjacent config field then - not speculatively now.

## Current Boundary

In scope:

- `src/jarvis/dialog/time_context.py`: `format_time_context(epoch: float) -> str`
  as specified above, plus the Russian weekday table.
- `src/jarvis/app.py`: `Orchestrator._start_turn()` appends the extra system
  message as specified; `self._current_turn_history_text` unaffected.
- Unit tests for `format_time_context()`: fixed epoch values covering at
  least one ordinary case and the documented DST fall-back edge case
  (assert the offset differs and both are individually well-formed, not that
  ordering is "fixed" - it isn't, by design).
- Unit test(s) in `tests/test_main.py` alongside the existing `_start_turn()`
  /thinking-level tests: with a fake clock, assert the constructed `messages`
  list contains the expected time-context system message in the expected
  position, and assert `ConversationHistory` after `finish_turn()` does not
  contain the time-context text.
- `PROJECT.md` note recording this decision, including the DST/offset
  reasoning and the accepted indirect-leak limitation.

Out of scope:

- Any heartbeat/proactive/self-initiated dialog behavior. Deliberately not
  planned - see the 2026-07-13 project memory decision on dual-context
  architecture.
- Storing the time-context string in `ConversationHistory` or otherwise
  giving the model cross-turn time continuity.
- A config toggle or timezone override setting.
- Any change to `VOICE_PLACEHOLDER_TEXT` or clipboard/screenshot turn
  handling beyond the single shared `_start_turn()` injection point (voice,
  clipboard, and future file-attachment turns all get this for free since
  they already funnel through `_start_turn()`).

## Acceptance Criteria

- [ ] `format_time_context()` is pure, takes an injected epoch, and returns
      `"{weekday_ru}, {ISO 8601 with explicit numeric UTC offset, minute
      precision}"`.
- [ ] Every turn source (voice, clipboard) sends this as an additional
      `system`-role message immediately before the current turn's `user`
      message.
- [ ] `ConversationHistory` never records the time-context text, verified by
      a test that inspects history state after `finish_turn()`.
- [ ] No dependency on OS locale (`%A`) or timezone-abbreviation lookup
      (`%Z`) anywhere in the new code.
- [ ] `python -m pytest` passes.
- [ ] `PROJECT.md` records the decision and the accepted DST/indirect-leak
      limitation in the same commit as the code change.

## Verification

- Automated: `python -m pytest`.
- Human (live Ollama - see Stop Conditions below): ask Jarvis "какое сегодня
  число" / "какой сегодня день недели" / "который час" against the real
  backend and confirm correct, current answers. This is the one part of this
  task that touches the live model and therefore cannot be fully verified by
  the agent alone (project testing protocol: live Ollama checks are a human
  handoff).

## Stop Conditions

- **Stop if Ollama/`gemma4:12b-it-qat` does not honor a second `system`-role
  message in one `/api/chat` call the way a single combined system message
  would be honored** (e.g. only the first system message reaches the model,
  or the two are silently concatenated in a way that breaks the existing
  system prompt). This has not been verified against live Ollama and is a
  real open question, not an assumption - the human verification step above
  is the first real test of it. If it fails, the fallback is concatenating
  the time-context line onto the single existing system message instead of
  appending a second one; do not silently switch to that fallback without
  recording the negative result in `PROJECT.md` first, per the project's
  "measurement before architectural decisions" rule.
- Stop if the DST/indirect-leak limitation turns out to affect more than the
  narrow window described above once actually tested - that would mean the
  current-turn-only design assumption was wrong and needs re-review before
  proceeding.
