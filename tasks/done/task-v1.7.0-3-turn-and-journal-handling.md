# Task v1.7.0-3: Turn and journal handling for the interrupted turn

**Status:** Completed. Automated logic tests and Ruff green (1438 passed, 1
skipped); five independent human review rounds run and all findings resolved
(see Review round 1-5 below). Human-run end-to-end interrupt handoff is not
re-required for this task: it changes only turn/journal bookkeeping around the
already-verified cancellation core (task-v1.7.0-2, passed live 2026-07-27),
and the interrupted/failed journal rendering was verified in the Browser pane
static preview. The consolidated story-level manual checklist stays task 5's
job (`task-v1.7.0-5-docs-and-release-verification.md`).
**Story:** `tasks/story-v1.7.0-barge-in.md`
**Depends on:** `tasks/done/task-v1.7.0-2-interrupt-hotkey-and-cancellation-core.md`
(completed). That task's boundary explicitly deferred this: "A minimal
placeholder for history (e.g. not calling `ConversationHistory.add()` for a
cut-short turn) is acceptable here and is expected to be revisited by task 3,
not perfected now." Gates task 4 (experimental voice barge-in), which ends a
turn through the same `_cancel_current_turn()` path this task fixes.

## Summary

Today, an interrupted turn (hotkey mid-response) never reaches
`ConversationHistory` or the journal's assistant side at all:
`_cancel_current_turn()` cancels the backend task and TTS, then - if it wins
`claim_turn_end()` - runs `finish_turn()` directly, skipping
`Orchestrator.on_response_complete()` entirely. Net effect: the user's own
message *was* journaled at turn start (`record_voice_user`/`record_text_user`),
but there is never a matching assistant entry, in either the journal or the
model's own conversation history - a silent gap, not an explicit "this was
interrupted" record, contradicting the story's append-only invariant
("Recording what happens to an interrupted turn in history and the journal ...
is a recorded event, not a silently discarded one").

This task adds a shared "turn aborted" recording path, called both from the
interrupt handler and - per an explicit scope decision below - from the
pre-existing hard-failure path in `_dispatch_backend_request()`, which has the
exact same shape of gap through a different trigger.

## Design decisions (confirmed 2026-07-28, before implementation)

- **History marker shape: a separate `system`-role `Turn`, not text appended
  to the assistant's own words.** `record_aborted_turn()` adds (in order):
  the user's `Turn` (never added on this path before), the partial assistant
  `Turn` only if any tokens actually streamed (an empty assistant message is
  never added), then one `system`-role `Turn` carrying a short outcome note.
  This reuses the pattern already established and *verified against the real
  model* by the v1.3.2 time-context injection - PROJECT.md records that
  `gemma4:12b-it-qat` honors a second `system`-role message in one
  `/api/chat` call - rather than a novel mechanism. It keeps the assistant's
  recorded words literal (never contaminated with a bracketed annotation) and
  means the empty-partial-text case never needs a placeholder empty
  `Turn`. `Turn`/`ConversationHistory` need no schema change - `role` is
  already an unrestricted `str`.
- **Scope also covers `_dispatch_backend_request()`'s hard-failure path**
  (`except Exception:`, `app.py` around line 696), found while reading this
  code, not part of the story's original boundary. It has the identical
  shape of gap for a different trigger: a backend/dispatch exception today
  clears `_busy` directly and never calls `record_assistant()`/
  `history.add()` either, leaving the same kind of orphaned user-only journal
  entry forever. Fixing it costs two lines once the shared helper exists, so
  it is folded into this task's commit rather than filed as a separate
  bug report. Gated on its own `claim_turn_end()` call (new) purely to avoid
  a double-record race against a hotkey interrupt landing in the same
  window - this does **not** change any of that path's existing
  busy-clearing/cue/mic behavior, which stays exactly as it is today; only
  the new recording call is added and only when the claim is won.
  `_on_full_response_complete()`'s own `except Exception:` branch (the
  trailing-TTS-flush failure case) was initially left untouched with the same
  reasoning, filed as a separate bug report, then - in review round 1 -
  reconsidered and given a new `TurnOutcome.PLAYBACK_FAILED` after finding
  the bug report conflated two sub-cases with different risk. Review round 2
  found *that* fix itself was untestable-in-reality (the real `TtsOutput`
  cannot raise from that call at all) and removed it again - see Review
  round 1 and Review round 2 below for the full back-and-forth. Net effect:
  this branch ends up **unchanged from before this task**, which turned out
  to be the correct answer all along, arrived at the hard way.

## Context you need

- `Orchestrator._start_turn()` (`app.py:559`) sets
  `self._current_turn_history_text`/`self._response_tokens` **after**
  `messages` is built (today, around what is currently line 629), which is
  itself after the journal-recording await and both existing
  `if self._interrupt_requested: return` checks (task-v1.7.0-2, review
  finding 2). A second-or-later turn's interrupt landing in that window would
  otherwise make `record_aborted_turn()` describe the *previous* turn's
  leftover text/tokens, since this turn's own values have not been assigned
  yet. Must be moved earlier (with no `await` between `_busy = True` and the
  new assignment point) before this task's recording path is safe to call
  unconditionally once `claim_turn_end()` succeeds. Not a hypothetical: the
  existing `test_interrupt_before_backend_dispatch_prevents_the_call_entirely`
  regression already proves this exact window is reachable; it just happened
  not to matter yet because task 2 recorded nothing there.
- `_cancel_current_turn()` (`app.py:1119`) - the shared cancellation core.
  Only the branch that wins `claim_turn_end()` may record anything; the
  losing branch means `_on_full_response_complete()` already ran the turn's
  real, complete `on_response_complete()` before the interrupt landed, so
  recording anything there would double up.
- `JournalRecorder.record_assistant()` (`journal/recorder.py:87`) currently
  takes only `text`; needs an optional `outcome` parameter that lands in the
  `JournalEvent.metadata` dict (already free-form JSON, no `JournalEvent`
  schema change needed) only when set, so a normal completion's recorded
  event is byte-for-byte unchanged from today.
- `status_console_ui/app.js`'s `_journalEventElement()`
  (~line 1943) already has a precedent for a metadata-driven annotation line
  below the message text: `_journalProvenanceDetail()` (~line 1989), used
  today only for a fork session's seed-truncation note. The interrupted/failed
  note follows the same shape (same CSS class, `amber` accent).
- Not in scope: any change to the mic-sleep/privacy toggle, TTS cancellation,
  or the hotkey binding itself (task 2's job, already shipped). Not in scope:
  the experimental voice barge-in trigger (task 4) - it reuses whatever this
  task ships, unmodified.

## Requirements

- `TurnOutcome(Enum)` in `journal/events.py` (`INTERRUPTED = "interrupted"`,
  `FAILED = "failed"` only - a third `PLAYBACK_FAILED` was tried and removed
  in review round 2, see below), exported from `journal/__init__.py`.
- `JournalRecorder.record_assistant(text, *, outcome: TurnOutcome | None = None)`
  - metadata carries `{"outcome": outcome.value}` only when `outcome` is not
    `None`; unchanged (`{}`) otherwise.
- `Orchestrator._start_turn()`: relocate the
  `_current_turn_history_text`/`_response_tokens`/`_spoke_this_turn` reset to
  immediately after `_journal_turn_started = False`, before the
  journal-recording `await` - no functional change to the normal path, only
  removes the staleness window described above.
- `Orchestrator.record_aborted_turn(*, outcome: TurnOutcome)`: adds the
  user `Turn`, the partial-assistant `Turn` (only if non-empty), and a
  `system`-role outcome-note `Turn` to `ConversationHistory`; then, if a
  journal recorder is configured and a user turn was actually journaled this
  turn (`_journal_turn_started`), writes the journal outcome - immediately if
  the user's own recording call has already returned
  (`_journal_recording_done` set), or via a non-blocking deferred background
  task that waits for it first otherwise (review round 2 - see below for why
  this ordering guard exists and why it must not block the caller).
- Call `record_aborted_turn(outcome=TurnOutcome.INTERRUPTED)` from
  `_cancel_current_turn()`, only in the branch that wins `claim_turn_end()`,
  before `finish_turn()`.
- Call `record_aborted_turn(outcome=TurnOutcome.FAILED)` from
  `_dispatch_backend_request()`'s `except Exception:` branch, gated on
  `self.claim_turn_end()` (new call there), without altering that branch's
  existing `_busy`/cue behavior otherwise.
- `Orchestrator._interrupt_requested` is an `asyncio.Event`, not a `bool`
  (review round 3). `_start_turn()` creates fresh `Event`s for both this and
  `_journal_recording_done`, captures them as **local variables**, and uses
  those locals - not `self.xxx` - for every check/`.set()` within its own
  body and in `_dispatch_backend_request()` (which now takes
  `interrupt_requested` as a parameter for the same reason). See Review
  round 3 for why: without this, a later turn replacing these two
  attributes while an earlier, already-interrupted turn's own `_start_turn()`
  is still suspended would make that earlier turn misread the *later*
  turn's fresh signals as its own.
- `_dispatch_backend_request()` re-checks `interrupt_requested` a second
  time, immediately after `await self._bus.publish(ModelRequestStarted, ...)`
  and before creating `self._active_chat_task` (review round 4) - the single
  check at the top of the function is not enough, since that publish is
  itself a real suspension point with no `_active_chat_task` yet for
  `cancel_active_turn()` to cancel.
- Journal UI: an outcome annotation line (reusing
  `.journal-provenance-detail`'s styling) on an assistant journal entry whose
  `metadata.outcome` is set, localized (`journal_outcome_interrupted`,
  `journal_outcome_failed`) in both `strings.js` locales.
- Automated tests (pure logic, per the project's testing protocol): the
  journal recorder's `outcome` metadata; the relocated reset's staleness
  regression (interrupt during journal-recording await on a *second* turn
  must not record the first turn's text, must still record that turn's
  journal outcome, and must record it *after* that turn's own user entry,
  never before); a genuinely later turn B starting while an interrupted
  turn A's own `_start_turn()` is still suspended must not let A dispatch a
  stale backend request or lose its deferred journal write - four findings
  across three review rounds, see below; `record_aborted_turn()`'s
  history/journal shape for a partial-text interrupt, a zero-token
  interrupt, and a hard dispatch failure; the `claim_turn_end()` race guard
  against a concurrent interrupt for the dispatch-failure path; that a
  normal (non-aborted) turn's recorded journal event and history stay
  byte-for-byte identical to before (no regression).

## Acceptance criteria

- [x] An interrupted turn (hotkey, any point after `_start_turn()` begins)
      leaves the user's message and whatever partial assistant text existed
      (possibly none) in `ConversationHistory`, plus a `system`-role note
      explaining it was interrupted - never a silent gap, and never the
      *previous* turn's text.
      (`test_record_aborted_turn_records_partial_text_and_interrupted_outcome`,
      `test_record_aborted_turn_with_no_streamed_text_skips_the_assistant_turn`,
      `test_interrupt_during_journal_recording_await_records_this_turns_text`.)
- [x] The same interrupted turn's journal shows an assistant entry with
      `metadata.outcome == "interrupted"` (partial text or empty), visible in
      the Journal UI with a localized annotation. Verified functionally in
      the Browser pane (static preview, synthetic events fed straight to
      `_journalEventElement()`/`_journalOutcomeDetail()` - no live backend
      needed): partial-text case renders the text plus the note and a copy
      button; the empty-text (failed) case renders no text line, just the
      note; both EN and RU strings confirmed.
- [x] A hard backend/dispatch failure gets the equivalent treatment
      (`outcome == "failed"`), without changing its existing busy-clearing or
      cue behavior, and without double-recording if a hotkey interrupt races
      it. (`test_backend_failure_records_aborted_turn_as_failed`,
      `test_backend_failure_does_not_double_record_when_interrupt_already_claimed`.)
- [x] *(Round 2)* The journal write for an aborted turn never lands *before*
      that turn's own user entry, even in the (currently unreachable with
      the real `JournalRecorder`) case where the user-recording call is
      still in flight when the interrupt lands - and does not block
      `_cancel_current_turn()`/`finish_turn()` while doing so.
      (`test_interrupt_during_journal_recording_await_records_this_turns_text`,
      asserting `journal_recorder.call_order`.)
- [x] *(Round 1, reverted in round 2)* A dedicated `PLAYBACK_FAILED` outcome
      for a TTS-flush failure was implemented, then removed after finding the
      real `TtsOutput.on_response_complete()` cannot raise at all - see
      Review round 2. `_on_full_response_complete()`'s `except Exception:`
      branch ends up unchanged from before this task.
- [x] *(Round 3)* An interrupted turn A's own `_start_turn()` invocation,
      resuming after a genuinely later turn B has already been accepted and
      started (possible because `_cancel_current_turn()` clears busy without
      waiting for A's own coroutine to exit), must still recognize it was
      interrupted and must not dispatch a stale backend request into B's
      state, and A's own deferred journal write (round 2) must not be lost
      just because B replaced the attributes A's write was waiting on.
      (`test_stale_interrupted_turn_does_not_dispatch_after_a_later_turn_starts`.)
- [x] *(Round 4)* An interrupt landing while `_dispatch_backend_request()`
      is suspended inside `EventBus.publish(ModelRequestStarted, ...)` -
      before `_active_chat_task` exists, so `cancel_active_turn()` has
      nothing to cancel - must still prevent the backend dispatch once that
      publish resolves.
      (`test_interrupt_during_model_request_started_publish_does_not_dispatch`.)
- [x] *(Round 5)* A stale dispatch's cleanup must never erase a *later*
      turn's `_active_chat_task` reference: when turn A's dispatch returns
      late (via the round-4 check) after turn B has already stored its own
      backend task, B's task survives and a subsequent interrupt still
      cancels it.
      (`test_stale_dispatch_cleanup_does_not_erase_a_later_turns_active_task`.)
- [x] A normal, uninterrupted turn's recorded history and journal event are
      unchanged from before this task (no `outcome` key, no extra `Turn`) -
      full pre-existing suite (1435 tests) stayed green with no changes to
      any existing assertions.
- [x] `python -m pytest` and Ruff are green.

## Review round 1 (2026-07-28): three findings, all confirmed and fixed

An independent review of the first implementation found three real issues -
one in the new code, two in the bug report filed alongside it. All three
confirmed before fixing, not taken on faith.

- **Finding 1 - `_journal_turn_started` set too late.** The flag was set
  `True` only *after* `record_voice_user()`/`record_text_user()`'s `await`
  returned, not before. `record_aborted_turn()` reads this flag to decide
  whether to write the journal side at all - an interrupt landing during
  that same await (the exact window `test_interrupt_during_journal_recording_await_records_this_turns_text`
  already exercised) would see the flag still `False` and silently skip the
  journal entirely, even though the fix's whole point was to stop the
  journal from silently missing an interrupted turn's outcome. That test
  only asserted `ConversationHistory`, so it passed while missing the
  defect. Confirmed by temporarily reverting the fix and re-running the
  (now-extended) test first: it failed with exactly the predicted symptom
  (`assistant_texts == ["first answer"]` instead of
  `["first answer", ""]`). Fixed by moving `self._journal_turn_started = True`
  to immediately before each `record_voice_user()`/`record_text_user()` call
  instead of after. This also incidentally fixed a second latent bug in the
  same lines: the old post-await assignment ran even after an interrupt had
  already ended the turn (and `record_aborted_turn()` had already reset the
  flag to `False` for it), resurrecting a stale `True` until the next
  `_start_turn()` call overwrote it - moving the assignment earlier removes
  any code after the await that could touch the flag.
- **Finding 2 - `TurnOutcome.FAILED` is the wrong label for a TTS-flush
  failure.** The bug report suggested reusing `TurnOutcome.FAILED` ("no
  response - backend error") for `_on_full_response_complete()`'s
  trailing-flush failure - but in that case the backend *did* produce a
  complete answer; only flushing it to TTS failed. Labelling that "no
  response - backend error" would be factually wrong in the user's own
  journal. Fixed by adding a distinct `TurnOutcome.PLAYBACK_FAILED` ("answer
  received but not spoken") rather than broadening `FAILED`'s meaning -
  keeps both outcomes honest and specific rather than one vague "something
  failed" bucket.
- **Finding 3 - the bug report conflated two sub-cases with different risk
  profiles, and misattributed a test.** It grouped "the exception came from
  step 1 or step 3" as both meaning "step 2 (recording) already succeeded" -
  but if step 1 (`tts_output.on_response_complete()`) raises, step 2
  (`orchestrator.on_response_complete()`) never runs at all; only a step-3
  failure *after* step 2 succeeded has the double-record risk. The report
  also cited `test_on_full_response_complete_clears_busy_and_plays_error_when_tts_fails`
  as covering a `CancelledError` path - it actually raises a plain
  `RuntimeError`, exercising the generic `except Exception:` branch, not the
  separate `except asyncio.CancelledError:` one (that one is
  `test_interrupt_racing_full_response_complete_only_finishes_once`).
  Once corrected, the step-1 sub-case turned out to be safely fixable now
  (no double-record risk, since nothing was recorded yet) - fixed directly
  in this task with a local `recorded` flag inside
  `_on_full_response_complete()` (parallel to `claim_turn_end()`, but scoped
  to this one function since it already holds that claim and cannot take it
  a second time): `except Exception:` now calls
  `record_aborted_turn(outcome=PLAYBACK_FAILED)` only when `recorded` is
  still `False`. The step-3-already-recorded sub-case needs no equivalent
  call at all, on reflection: that turn's text is already complete and
  correctly recorded; only audio playback failed afterward, so there is
  nothing missing from history/journal to add - confirmed by extending
  `test_on_full_response_complete_clears_busy_and_plays_error_when_tts_fails`
  to assert history has exactly the two entries `on_response_complete()`
  wrote, no more. The bug report this all lived in
  (`2026-07-28-tts-flush-failure-leaves-turn-unrecorded.md`) is deleted
  rather than corrected-in-place, since its premise (the gap is unfixed) no
  longer holds.
  **Residual, deliberately unhandled edge (documented, not fixed):** if
  `orchestrator.on_response_complete()` itself raised *synchronously partway
  through its own body* (after already mutating `ConversationHistory` but
  before returning), the `recorded` flag - set only after the whole call
  returns - would still read `False`, and `record_aborted_turn()` would then
  duplicate the history entries `on_response_complete()` had already added.
  Not fixed: the only realistic trigger is `JournalRecorder._now()` raising
  `ValueError` on a misconfigured clock (a construction-time contract
  violation - `Orchestrator._clock` is guaranteed to return timezone-aware
  datetimes by `build_app()`'s wiring), not a runtime condition to defend
  against per the project's "trust internal guarantees" rule; the real
  `JournalRecorder.record_assistant()` never raises synchronously otherwise
  (`_schedule()` only creates a background task, whose own failures are
  caught and logged by `_on_task_done()`, never propagated to the caller).

## Review round 2 (2026-07-28): two more findings, both confirmed and fixed

A second independent review, run against round 1's fixes, found two more
real issues - both confirmed before fixing.

- **Finding 1 - round 1's flag-reordering fix broke append-only write
  order.** Round 1 moved `self._journal_turn_started = True` to *before*
  the `record_voice_user()`/`record_text_user()` `await`, so
  `record_aborted_turn()` would not skip the journal side. But this let
  `record_aborted_turn()` call `journal_recorder.record_assistant()` *before*
  the user's own call had actually reached the recorder, in the exact test
  scenario that exercises this window (a slow-mocked `record_text_user()`) -
  the assistant "interrupted" entry would be appended to the journal *before*
  the user message it answers, corrupting the append-only log's causal
  order, not just risking a skip. Confirmed by temporarily making
  `record_aborted_turn()` always write immediately (round 1's actual
  behavior) and re-running the extended test first: it failed with the
  outcome entry appended before the user entry, exactly as predicted.
  Fixed with `Orchestrator._journal_recording_done` (an `asyncio.Event`,
  fresh every turn, set right after the journal-recording decision in
  `_start_turn()` is carried out): `record_aborted_turn()` writes
  immediately if it is already set (true for every real call today, since
  neither `record_voice_user()` nor `record_text_user()` has an internal
  `await` before scheduling its own write - confirmed by reading both
  implementations, not assumed), or otherwise defers to a background task
  that waits for the event first. That background task is deliberately
  **not awaited** by `record_aborted_turn()`/`_cancel_current_turn()`:
  an earlier draft made it block, which correctly preserved order but
  deadlocked the *existing* `test_interrupt_before_backend_dispatch_prevents_the_call_entirely`
  regression from task-v1.7.0-2 (that test also exercises a slow-mocked
  recording call, and calls `_cancel_current_turn()` directly, expecting
  it to return before unblocking the mock) - confirmed by actually running
  into the hang, not just reasoning about it. Non-blocking means the
  deferred branch (currently unreachable in production) has an accepted,
  narrow cost: `finish_turn()`'s `wait_for_pending()` will not wait for it,
  so the live Journal view could theoretically lag in that one case - the
  same class of eventual-consistency gap already accepted for the Journal
  tab-inactive case, not a new one, and never reachable with the real
  `JournalRecorder` today.
- **Finding 2 - the round-1 `PLAYBACK_FAILED` fix cannot be triggered by the
  real `TtsOutput`.** Read `audio/tts.py` to check: `TtsOutput.
  on_response_complete()` (line 370) only iterates `self._units.flush()`
  (an in-memory buffer) and calls `self._schedule()` (pure `asyncio.
  create_task()` bookkeeping) - there is no `await` on anything that can
  raise. Every real synthesis failure is caught *inside*
  `_synthesize_and_submit()`'s own `try`/`except` (logged, and
  `OrderedPlayback.submit(index, None)` keeps the ordering intact) and never
  escapes as an exception. The one thing that *can* raise into
  `wait_for_pending()`'s `gather()` is a real playback error (e.g.
  `sd.play`/`sd.wait()` failing inside `_default_play()`, called via
  `OrderedPlayback.submit()` outside any try/except) - but that always
  surfaces through `wait_for_pending()`, i.e. always *after*
  `orchestrator.on_response_complete()` (step 2) has already succeeded.
  Round 1's own `_FlushFailingTts` test double raised from
  `on_response_complete()` directly to reach the "step 2 never ran" branch -
  behavior the real class cannot exhibit. There is no real, producible
  scenario left for `PLAYBACK_FAILED` to label. Also independently correct:
  even if reachable, "answer received but not spoken" would already be
  wrong wording for a multi-sentence answer, since `on_response_complete()`
  only flushes the *trailing* buffered sentence - earlier sentences of the
  same answer would typically have already been synthesized and spoken via
  `on_token()`'s progressive scheduling during streaming.
  Fixed by removing the mechanism entirely rather than keeping it as
  speculative defensive code, per the project's "don't handle scenarios
  that can't happen" rule: `TurnOutcome.PLAYBACK_FAILED`,
  `_PLAYBACK_FAILED_HISTORY_NOTE`, the `recorded`-flag branch in
  `_on_full_response_complete()`, its test, and the
  `journal_outcome_playback_failed` UI strings are all removed.
  `_on_full_response_complete()`'s `except Exception:` branch is back to
  exactly what it was before this task - confirmed correct, not merely
  reverted on faith.

## Review round 3 (2026-07-28): a genuine cross-turn collision in round 2's own fix

A third independent review, run against round 2's fixes, found that round
2's ordering guard introduced (or rather, exposed - see below) a real
cross-turn state collision.

- **Finding - a later turn B can start while an interrupted turn A's own
  `_start_turn()` is still suspended, and B's own setup clobbers state A's
  suspended coroutine will read/write when it resumes.**
  `_cancel_current_turn()` clears busy (via `finish_turn()`) as soon as it
  wins `claim_turn_end()` - it does not, and per its own design must not
  (see Review round 2, finding 1), wait for A's own `_start_turn()` coroutine
  to actually exit. If that coroutine is still suspended (round 2's example:
  a slow journal-recording call) when busy is cleared, a genuinely new turn
  B can be accepted immediately - and B's own `_start_turn()` setup
  overwrites `self._interrupt_requested` and `self._journal_recording_done`
  with its own fresh objects. When A's suspended call finally resumes:
  `self._journal_recording_done.set()` would set *B's* Event, not A's - A's
  own deferred write (round 2), still waiting on the *original* Event object
  it captured when created, would then never be signalled and hang forever.
  Separately, `if self._interrupt_requested: ...` would read *B's* fresh,
  unset flag - A would wrongly conclude it was never interrupted and go on
  to publish `TurnAccepted`, play the "thinking" cue, and dispatch a second,
  stale, unwanted backend request using whatever state B has since set up.
  Confirmed by temporarily reverting `_start_turn()`/`_dispatch_backend_request()`
  to read `self._interrupt_requested`/`self._journal_recording_done`
  directly (i.e. round 2's actual shipped shape) and re-running the new
  regression test first: it hung - `await orchestrator._pending_aborted_journal_write`
  never returned, exactly the "hangs forever" symptom - confirming the
  finding by reproducing it, not just by reasoning about the code.

  Two fix shapes were considered:
  1. **Tie `_busy`'s clearing to `_start_turn()`'s own exit** (make a new
     turn genuinely impossible until the old one's coroutine has fully
     drained) - rejected: `finish_turn()` currently clears busy and is
     called directly by several existing tests expecting it to do so
     standalone (without ever calling `_start_turn()`), and moving that
     responsibility would be a much wider behavioral change to an
     already-shipped, human-verified task-v1.7.0-2 contract than this
     finding calls for - the risk of quietly breaking something outside
     this task's boundary was judged too high for the benefit.
  2. **Local-variable capture** (chosen): `_start_turn()` creates its two
     fresh `Event`s, assigns them to `self.xxx` (so `cancel_active_turn()`
     and other *current-turn* readers still reach them normally), and also
     keeps its own **local** references (`interrupt_requested`,
     `journal_recording_done`). Every subsequent check/`.set()` within
     `_start_turn()`'s own body - and in `_dispatch_backend_request()`,
     which now takes `interrupt_requested` as a parameter instead of
     reading `self._interrupt_requested` - uses the local names. A later
     turn rebinding `self.xxx` to its own objects therefore cannot affect
     what an *already-suspended* earlier invocation reads or sets, since it
     was never re-reading `self.xxx` in the first place once past its own
     setup. `self._interrupt_requested` changed from a `bool` to an
     `asyncio.Event` to make this possible (a `bool` can't be "the same
     object" across a reassignment the way an `Event` reference can).
     No other per-turn field needed this treatment: `_turn_end_claimed`/
     `claim_turn_end()` and `_current_turn_history_text`/`_response_tokens`
     are only ever read by callers gated on `claim_turn_end()`, which always
     run promptly against whichever turn is *actually* current at the time,
     never by a resuming `_start_turn()` reading its own state back after a
     suspension - audited each read site to confirm this before deciding no
     further change was needed there.

## Review round 4 (2026-07-28): one more real interrupt window, same class as round 3

A fourth independent review, run against round 3's fix, found that the
local-capture fix (round 3) made `interrupt_requested` reliable to read, but
`_dispatch_backend_request()` still only read it **once**, too early to
cover every real suspension point in the function.

- **Finding - no re-check after `ModelRequestStarted`'s publish.**
  `_dispatch_backend_request()` checks `interrupt_requested` once, at the
  very top, before its own `try` block - a check whose own docstring
  (written in round 3) already named "still awaiting ModelRequestStarted's
  publish" as an example suspension window, without actually adding a check
  for it. `EventBus.publish()` awaits every subscriber - a real, producible
  suspension point, not test-mock-only like some of the earlier findings -
  and at that point `self._active_chat_task` does not exist yet (it is only
  created afterward), so `cancel_active_turn()` has nothing to cancel if an
  interrupt lands during it. `_cancel_current_turn()` still completes its
  full cleanup regardless (busy cleared, `TurnCompleted` published,
  `record_aborted_turn()` run) since none of that depends on
  `_active_chat_task` existing. Once the publish resolves,
  `_dispatch_backend_request()` resumed with no further check and went
  straight on to create `_active_chat_task` and dispatch to the backend -
  a stale request for a turn already fully ended, into whatever a later
  turn's own state looks like by then (same consequence class as round 3).
  Confirmed by reverting the fix and re-running the new test with a hard
  timeout this time (round 3's manual verification had to kill a genuinely
  hung Python process): it failed cleanly with `len(backend.calls) == 1`
  instead of `0` - the stale dispatch actually happened, not just an
  assertion mismatch.
  Fixed with a second `if interrupt_requested.is_set(): return` immediately
  after the `ModelRequestStarted` publish, inside the same `if self._bus is
  not None:` block, before `self._active_chat_task` is created. Uses the
  same local parameter already threaded through in round 3, so it is
  immune to a later turn's own `self._interrupt_requested` reassignment for
  the same reason round 3's other checks are.
  **Audited adjacent suspension points for the same gap, found none
  needing a fix:** `_start_turn()`'s own `await self._sound_cues.play(
  "thinking")` (right before building `messages` and calling
  `_dispatch_backend_request()`) has no re-check after it either, but needs
  none - `_dispatch_backend_request()`'s own first-line check already
  covers that window, since it runs immediately after and before doing
  anything else. The pre-`_start_turn()` cue play in `on_clipboard()`
  (`"clipboard"`/`"input_error"`) also has no check after it, but does not
  need one either: at that point `_busy` has not been set yet, so
  `_cancel_current_turn()` sees `is_busy` false and correctly no-ops,
  matching the hotkey's documented "no-op while idle" contract rather than
  being a gap.

## Review round 5 (2026-07-28): round 4's early return left a destructive finally behind

A fifth independent review, run against round 4's fix, found that the fix
itself was correct as far as it went - the stale dispatch is prevented - but
its `return` exits from *inside* the `try`, so the function's `finally`
still ran, and that `finally` unconditionally set
`self._active_chat_task = None`.

- **Finding - a stale dispatch's `finally` erases a later turn's task
  reference.** Sequence: turn A's `ModelRequestStarted` publish blocks on a
  slow subscriber; an interrupt ends turn A (full cleanup, busy cleared);
  turn B starts, dispatches, and stores its own backend task in
  `self._active_chat_task`; A's publish finally resolves, A's dispatch
  returns via the round-4 check - and A's `finally` then wiped
  `self._active_chat_task` to `None` even though it now held *B's* task.
  B's backend request kept running normally (its own `await` is on a local
  reference), but the next interrupt found `_active_chat_task` `None` and
  had nothing to cancel: TTS would stop, but generation would keep running
  to completion in the background - exactly the class of stuck state the
  interrupt feature exists to prevent. Confirmed by reverting the fix and
  re-running the new test first: it failed with
  `orchestrator._active_chat_task is None` while B's task object was still
  pending - the reference erased mid-flight, exactly as predicted.
  Fixed with an ownership guard: the dispatch stores the task it creates in
  a local `own_chat_task` (assigned to `self._active_chat_task` as before),
  and the `finally` clears the attribute only `if self._active_chat_task is
  own_chat_task` - a dispatch may only ever clear the task *it* created.
  For a dispatch that never created one (`own_chat_task` still `None`),
  the guard is a no-op unless the attribute is also `None`, in which case
  clearing it changes nothing. See
  `test_stale_dispatch_cleanup_does_not_erase_a_later_turns_active_task`,
  which also asserts the follow-through: a second interrupt after A's late
  return still finds and cancels B's task.

## Implementation notes

- `journal/events.py`: `TurnOutcome(Enum)` (`INTERRUPTED`, `FAILED`),
  exported from `journal/__init__.py`. `JournalRecorder.record_assistant()`
  gained `outcome: TurnOutcome | None = None`, stored as
  `metadata["outcome"]` only when set - a normal completion's event is
  byte-for-byte unchanged.
- `app.py` `Orchestrator._start_turn()`: relocated the
  `_current_turn_history_text`/`_response_tokens`/`_spoke_this_turn` reset to
  immediately after `_journal_turn_started = False` (no `await` in between,
  so no interleaving is possible there). **Real bug found while
  implementing, not just anticipated by the task card**: with the original
  ordering, an interrupt landing during the journal-recording `await` (on
  the second turn or later) would have made the new recording path describe
  the *previous* turn's leftover text/tokens - proven by
  `test_interrupt_during_journal_recording_await_records_this_turns_text`,
  which fails against the pre-relocation ordering.
- `Orchestrator.record_aborted_turn(*, outcome)`: adds the user `Turn`, the
  partial-assistant `Turn` only if non-empty, and a `system`-role note
  (`_INTERRUPTED_HISTORY_NOTE` / `_FAILED_HISTORY_NOTE`) to
  `ConversationHistory`; then records the journal assistant event with
  `outcome` when a journal recorder is configured and this turn was actually
  journaled, ordered against `_journal_recording_done` (round 2 - see Review
  round 2). Called from `_cancel_current_turn()` (module-level, `app.py`)
  after it wins `claim_turn_end()`, and from
  `_dispatch_backend_request()`'s `except Exception:` branch gated on a new
  `self.claim_turn_end()` call there - guards against a hotkey interrupt and
  a hard failure racing each other into a double record, without changing
  that branch's existing busy-clearing behavior otherwise.
- `Orchestrator._journal_recording_done` (`asyncio.Event`, fresh every turn)
  and `Orchestrator._pending_aborted_journal_write` (test-introspection only,
  mirrors `_active_chat_task`'s existing pattern) - the round-2 ordering fix,
  see Review round 2.
- `Orchestrator._interrupt_requested`: `bool` -> `asyncio.Event` (round 3).
  `_start_turn()` now captures **local** `interrupt_requested`/
  `journal_recording_done` variables alongside the `self.xxx` assignments,
  and uses the locals for every check/`.set()` in its own body;
  `_dispatch_backend_request()` takes `interrupt_requested` as a new
  parameter instead of reading `self._interrupt_requested`. See Review
  round 3 for the cross-turn collision this closes and why a `_busy`-lifetime
  redesign was considered and rejected in favor of this narrower fix.
- `_dispatch_backend_request()` re-checks `interrupt_requested` again right
  after the `ModelRequestStarted` publish, before creating
  `_active_chat_task` (round 4) - the single top-of-function check left a
  real (not test-mock-only) window open, since `EventBus.publish()` awaits
  every subscriber. See Review round 4.
- `_dispatch_backend_request()`'s `finally` clears `self._active_chat_task`
  only if it still holds this dispatch's own task (local `own_chat_task`,
  round 5) - a stale dispatch returning late must not erase a later turn's
  reference, or the next interrupt cannot cancel that turn's backend
  request. See Review round 5.
- Journal UI (`status_console_ui/app.js`/`strings.js`): a new
  `_journalOutcomeDetail()` reads `event.metadata.outcome` and renders a
  localized note reusing `_journalProvenanceDetail()`'s
  `.journal-provenance-detail` styling (same accent as the fork
  seed-truncation note) - `journal_outcome_interrupted`/
  `journal_outcome_failed` in both `strings.js` locales.
- `_on_full_response_complete()`'s own `except Exception:` branch is
  **unchanged from before this task** - a round-1 addition
  (`TurnOutcome.PLAYBACK_FAILED`) was reverted in round 2 after finding it
  could never actually trigger with the real `TtsOutput`. See Review round 2.
- PROJECT.md is **not** updated by this task, matching task 2's own
  precedent: the story's task 5
  (`task-v1.7.0-5-docs-and-release-verification.md`) explicitly owns the
  consolidated architecture write-up for the whole story; task 2's commits
  did not touch PROJECT.md either.

## Stop conditions

- Stop if `_on_full_response_complete()`'s own `except Exception:` branch
  turns out to need the same fix after all (e.g. if a reviewer finds the
  double-record risk is not real) - that would mean the "explicitly not
  touched" scope decision above was wrong and needs revisiting, not a
  silent fix folded in later. *(Triggered by review round 1: the
  double-record risk was real for one sub-case (step 3) but not the other
  (step 1) - the original bug report had conflated them. Round 1 then fixed
  the step-1 sub-case with `TurnOutcome.PLAYBACK_FAILED` - but round 2 found
  that sub-case cannot actually occur with the real `TtsOutput` either, so
  the branch ends up unchanged from before this task after all. See Review
  round 1 and Review round 2.)*
- Stop if a fix for one race turns out to introduce or worsen another -
  applies here even though it was not written down in advance: round 2's
  first attempt at the ordering fix (blocking `record_aborted_turn()` on the
  in-flight journal write) deadlocked a pre-existing, previously-passing
  task-v1.7.0-2 regression test. Caught by actually running the full suite
  before considering the fix done, not by reasoning about it in the
  abstract - resolved by making the fix non-blocking instead (see Review
  round 2, finding 1). *(Triggered again in round 3, same class of issue:
  round 2's own ordering guard assumed only one turn's `_start_turn()` is
  ever "in flight" at a time - not true, since `_cancel_current_turn()`
  clears busy before that coroutine necessarily exits. Fixed with local
  reference capture rather than a wider `_busy`-lifetime change, for the
  same reason a blocking fix was rejected in round 2 - see Review round 3.)*
