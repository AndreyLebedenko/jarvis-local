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

**Open input from an earlier report:**
`tasks/bug_reports/thinking-mode-mic-window-before-autopause.md` is the only
place recording two follow-ups deliberately deferred to "roadmap item 7 (real
echo cancellation)", which is this card. Neither was implemented. When this
task is opened, read that report and decide explicitly on both:

- test voice barge-in with thinking mode both on and off, because thinking
  mode widens the window between turn start and `on_response_token()`'s
  auto-pause, during which the microphone is still live;
- whether the auto-pause trigger should move from the first spoken token to
  `_start_turn()`, closing that window entirely. That is a behavioral change
  affecting every turn, not only thinking-mode ones, and needs its own review.
