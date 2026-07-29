# Backlog: Experimental voice barge-in (opt-in, headphones-only)

**Status:** Backlog. Deferred 2026-07-29 (owner decision) - not abandoned,
just not next.

**Origin:** `tasks/story-v1.7.0-barge-in.md`, task 4
(`task-v1.7.0-4-experimental-voice-barge-in.md`, never opened as a task
card). Story scope, item 4:

> The opt-in, default-off, headphones-only config option and its
> VAD-during-playback trigger, reusing task 2's cancellation core.

Task 2 (hotkey and cancellation core) and task 3 (interrupted-turn
history/journal handling) are both completed and closed
(`tasks/done/task-v1.7.0-2-interrupt-hotkey-and-cancellation-core.md`,
`tasks/done/task-v1.7.0-3-turn-and-journal-handling.md`). The shared
cancellation core this task would reuse already exists.

**Why deferred:** owner has higher-priority work ahead of it right now.
No technical blocker - the design decisions in the story card (opt-in,
default-off, headphones-only by documentation not enforcement, reusing
the task-2 cancellation core, prominent config warning matching the
camera credential-warning precedent) still stand and were not
reconsidered.

**When picked back up:** open `task-v1.7.0-4-experimental-voice-barge-in.md`
from the story card's scope section as originally planned. Re-read
`tasks/story-v1.7.0-barge-in.md` in full first, since task 5 (docs and
release verification) was scoped assuming task 4 exists and may need
re-checking once this lands.
