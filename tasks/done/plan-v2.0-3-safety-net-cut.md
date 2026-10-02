# Plan: cut the worker-cancellation safety net (task v2.0-3 rework)

**Status:** Completed. (2026-10-02)
**Card:** `tasks/done/task-v2.0-3-voice-guide-pipeline.md`.
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Starting point:** the WIP commit that follows this file on
`feat/v2.0-3-voice-guide-pipeline`.

## Why

`VoiceGuideService` journals unfinished requests on a second path: when its
worker task is cancelled from outside without `close()`. The story already
accepts that a crash loses queued canvases, and in the app `close()` is the
only shutdown path (task 4 wires it before the journal flush). A worker
cancelled without `close()` is the same class as a crash. Defending it costs
most of the service's complexity: a single shared drain task, a done-callback
drain, a `CancelledError` branch, a test that counts calls to a private
method, and a "can lose, never duplicate" caveat. The cut removes that path
and keeps every guarantee of the orderly path.

## Decisions (owner, 2026-10-02)

1. A worker cancelled from outside without `close()` is a crash: unfinished
   canvases may be lost, as the story accepts.
2. A worker that dies from a bug in the middle of an item loses that item's
   journal event. Same class as a crash; accepted. (In practice the worker
   cannot die from an `Exception`: `_serve`, `_journal`, and `_cue_error`
   catch it.)
3. `ReplayPlayer.start_run()` becomes a plain (sync) method. It never
   awaited anything; being `async` forced a text-only invariant ("must not
   suspend once it has started a run") into the `GuidePlayer` protocol. As a
   plain method the language enforces it. `replay_items()` stays `async` and
   its behavior for existing callers is unchanged.
4. The Journal Stop button keeps its name. It stops the Journal's own
   replay sequence; the guide's speech never shows a Stop control (no
   `ReplayProgress` is published for it). The real issue is a race: the stop
   route calls the player-wide `cancel()`, so a Stop click landing just after
   the user's replay ended can cut the guide that started in its place. Fix
   direction: the Journal Stop cancels its own `ReplayRun`. This belongs to
   task 4, recorded there by this plan; not implemented here.

## Steps

0. This file, then a WIP commit of the current branch state (git protocol:
   commit before a wide change), so the cut is a separate reviewable diff.

1. Remove the safety net from `src/jarvis/dialog/voice_guide.py`:
   - the `except asyncio.CancelledError` branch in `_serve_forever`;
   - `_drain_task` and `_drain_once`;
   - the drain in `_on_worker_done`. Keep the callback only to mark the
     service closed (a dead worker must not keep accepting requests) and to
     log a crash;
   - the recorder caveat in the `GuideRecorder` docstring;
   - in `tests/test_voice_guide.py`: `test_one_drain_serves_a_worker_end_and_every_close`
     (counts `_drain_unfinished` calls) and the `test_worker_cancelled_*`
     tests. Before deleting each, check whether it actually pins a
     `close()`-path or interrupt-path property that no remaining test covers;
     such a property is kept by porting the test to the orderly path, not
     dropped. Report the per-test verdict.

2. Make `close()` one linear path: mark closed, interrupt the item in
   flight, await the worker if it was started, journal the remaining
   dropped/pending requests `skipped`, reset the in-flight slot so the final
   `VoiceGuideQueueChanged` is empty, settle background tasks. `_settle` is
   no longer needed: on the orderly path the worker journals its own item.
   Keep: `_status_of`, the per-item interrupt signal, `ReplayRun` use,
   `close()` before `start()`, idempotent `close()`, `CLOSED` rejection,
   `close()` shielded from a cancelled caller.

3. `ReplayPlayer.start_run()` -> plain method (`src/jarvis/audio/replay.py`);
   `replay_items()` calls it without `await`. `GuidePlayer.start_run` becomes
   a plain method and loses the "must not suspend" note; the service calls it
   without `await`. Update fakes and `tests/test_replay.py` callers (a sync
   `start_run` still needs a running loop for `create_task`).

4. Docs:
   - `PROJECT.md`: replace the "A cancelled worker is only a safety net"
     paragraph with one sentence (decisions 1 and 2); make the `start_run`
     paragraph and the lifecycle paragraph match the code.
   - story card "Write timing" bullet and task 3 card section 4: consistent
     with decisions 1 and 2. The card's "see completion notes" reference must
     point at something that exists when the card is closed.
   - task 4 card: replace "Cancelling the worker task directly is only a
     safety net" with decision 1; add decision 4 (the Stop race and its fix
     direction) next to the existing Journal Stop bullet.

5. Verify: `python -m pytest`, `ruff check`, `ruff format --check`. Then a
   separate reviewer pass with deliberate mutations, limited to the paths
   that remain (orderly `close()`, interrupt, status mapping, BUSY wait,
   `start_run`), to confirm the cut removed no coverage of the orderly path.

## Out of scope

- Any behavior change on the orderly path.
- Implementing the Journal Stop fix (task 4).
- Closing task 3, merging, or starting task 4 (waits for owner review).
