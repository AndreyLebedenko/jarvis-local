# Story v1.7.0: Interrupting Jarvis (hotkey default, experimental voice barge-in for headphones)

**Status:** Proposed. Task 1 (spike) completed and closed; tasks 2+ not
opened yet.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.7.0 section). Resequenced
from the unversioned v1.7.x "Conversational fluidity" list to v1.7.0
(owner decision, 2026-07-26), ahead of memory consolidation/retrieval,
which shifted to v1.7.1/v1.7.2 accordingly. Wake-word addressing, the
emotion2vec+ side channel, and the MCP egress watchdog stay separate
future stories in the unversioned v1.7.x list.
**Created:** 2026-07-26.
**Replaces:** the v1.0/v1.1 timing-window mitigations for Jarvis hearing
its own TTS output - `Orchestrator.finish_turn()`'s busy-cooldown and
`AudioInput.auto_pause_for_speech()`/`auto_resume_after_speech()` (mic
stops capturing the moment Jarvis starts speaking, resumes after
`vad.resume_cooldown_seconds`). See PROJECT.md's "No echo cancellation in
v1.0" verified-facts entry for the full history of both mitigations.
Whether either mitigation stays as a fallback for turns that produce no
speech at all is a task-2 decision.

## Pivot note (2026-07-26)

This story originally bet everything on general-hardware AEC: task 1 was
a hard-gate spike to find an echo-cancellation approach good enough to
keep the mic open on arbitrary desktop-speaker setups. The spike ran
(see `tasks/done/task-v1.7.0-1-aec-spike.md` and PROJECT.md's
"Architecture v1.7.0 spike" section) and came back no-go for that goal:
Bluetooth headphones already show near-zero self-hearing with no AEC at
all, but desktop speakers on the owner's actual hardware chain (PC ->
HDMI -> TV -> HDMI ARC -> soundbar) kept producing VAD false positives
on self-heard TTS in every tested condition, even after fixing a real
delay-alignment bug in the check script and sweeping filter parameters.

Discussing that result surfaced a wider problem with the original
premise, not just a weak candidate: this is free software shipping to
arbitrary user hardware, with no equivalent of a commercial smart
speaker's fixed, lab-tuned acoustic path, and ambient noise (traffic, a
washing machine, birds) compounds with imperfect echo cancellation into
a harder joint problem than noise alone - it does not reduce to the
project's existing not-currently-speaking noise-robustness problem even
when AEC nominally "works." General-hardware voice barge-in is
therefore parked, not pursued further in this story.

The story keeps its name and version because the user-facing goal -
"give the user a way to interrupt Jarvis" - is unchanged; only the
mechanism changed. A hotkey (deterministic, hardware-independent) is now
the primary path. Voice-triggered interruption survives as an opt-in,
default-off, headphones-only experimental feature, justified
specifically by the headphone finding above.

## User-facing goal

The user can interrupt Jarvis mid-response with a hotkey: TTS playback
stops, the in-flight backend response stops generating, and Jarvis
starts listening for the next request. This works identically regardless
of speakers, room, or microphone - no acoustic assumptions at all.

Separately, a user who listens over headphones (Bluetooth or wired) may
opt into voice-triggered interruption - speaking while Jarvis talks
interrupts it the way interrupting a person works - by explicitly
enabling an experimental, default-off config setting that says clearly
it is unsupported outside headphone playback.

## What is already known (from the original spike planning, still valid)

- Cancelling the in-flight Ollama stream looks tractable without new
  research: `OllamaBackend.iter_chat()` (`src/jarvis/dialog/backend.py`)
  is an async generator wrapping `httpx`'s streaming POST, with stream
  cleanup already in a `finally` block. `Orchestrator._handle_new_turn()`
  currently awaits `self._backend.chat(...)` directly; wrapping that call
  in an `asyncio.Task` and cancelling it from an interrupt handler should
  propagate cleanly through the generator's `finally`. This is a task-2
  implementation detail, not an open research question.
- `TtsOutput.wait_for_pending()` is today's only "stop" concept, and it
  means the opposite of interruption: it waits for in-flight speech to
  finish for a graceful shutdown. A real interrupt needs a genuine
  cancellation path through `OrderedPlayback` and the pending synthesis
  tasks, which does not exist yet.
- `HotkeySettings` (`src/jarvis/core/config.py`) already holds five
  `ctrl+alt+<letter>` bindings (`screenshot_full`, `screenshot_region`,
  `shutdown`, `mic_sleep_toggle`, `clipboard_submit`, `thinking_toggle`);
  a new interrupt hotkey should follow that convention and pick a letter
  that does not collide, via the existing `run_hotkey_provider()` seam in
  `src/jarvis/inputs/hotkeys.py`.

## Boundaries

In scope:

- A hotkey that cancels the in-flight TTS playback and backend stream
  and returns Jarvis to listening, unconditionally - no acoustic
  detection, no AEC, works on any hardware.
- Recording what happens to an interrupted turn in history and the
  journal - the journal's append-only invariant (roadmap cross-cutting
  rule 6) means an interrupted turn is a recorded event, not a silently
  discarded one. Exact shape is a task-card decision. This applies to
  both the hotkey and voice paths, since both end a turn the same way.
- An opt-in, default-off, headphones-only experimental voice-triggered
  interruption, reusing the hotkey's cancellation mechanism but
  triggered by VAD-during-playback instead of a keypress. No AEC: the
  spike found headphone self-hearing already near-zero without it, so
  the feature's safety rests entirely on the user actually wearing
  headphones, which the config makes explicit and prominent (precedent:
  `config.example.toml`'s camera clear-text-credential warning).

Out of scope:

- Any general-hardware / desktop-speaker AEC path - parked per the
  pivot note above, not attempted further in this story.
- Wake word / addressing, the emotion2vec+ prosody side channel, the MCP
  egress watchdog - separate future v1.7.x stories.
- Resuming or continuing an interrupted turn - once interrupted (by
  either mechanism), that turn is over; there is no "continue where I
  left off."
- Any change to the user-triggered mic sleep/privacy toggle contract.
  The toggle remains non-delegable per cross-cutting rule 9, and neither
  interruption path activates while the mic is asleep or privacy-paused.
- Detecting whether the user is actually wearing headphones. The config
  warning is the only guard; there is no runtime enforcement, and that
  is a deliberate, disclosed limitation, not a gap to silently close.

## Design decisions (proposed here, confirmed by card approval)

- **Hotkey is the primary, default-available mechanism.** It ships
  enabled like the project's other hotkeys; no opt-in needed, because it
  carries no acoustic risk.
- **Voice barge-in is opt-in, default off, headphones-only by
  documentation, not by enforcement.** The config's warning must be
  prominent and explicit that it is unsupported/experimental outside
  headphone playback, matching the camera credential-warning precedent
  in tone and placement.
- **Both mechanisms share one cancellation core.** The hotkey and the
  experimental voice path both end at the same "cancel this turn" logic
  (TTS playback, backend stream, turn/journal bookkeeping); only the
  trigger differs. This is built once in task 2 and reused, not
  duplicated in task 4.
- **Interruption cancels outright; it does not pause-and-resume.** The
  interrupted turn ends; its partial answer (whatever text/audio had
  already been produced) is recorded as an interrupted turn in
  history/journal rather than discarded, per the append-only invariant.
  The exact history/journal schema addition is a task-3 decision.
- **General-hardware AEC is parked, not abandoned as an idea.** If
  revisited later, the natural next step is a production-grade AEC
  library (e.g. WebRTC's AEC3) against real hardware, not further tuning
  of the pure-numpy NLMS spike candidate - see the spike's closure note.

## Scope (ordered task cards, to be opened one at a time)

1. `tasks/done/task-v1.7.0-1-aec-spike.md` - completed; no-go for
   general-hardware AEC, headphones verified safe without it. Drove the
   pivot recorded above.
2. `task-v1.7.0-2-interrupt-hotkey-and-cancellation-core.md` - the
   hotkey, its binding, and the shared cancellation mechanism (TTS
   playback + backend stream).
3. `task-v1.7.0-3-turn-and-journal-handling.md` - interrupted-turn
   representation in history and the journal, for both trigger paths.
4. `task-v1.7.0-4-experimental-voice-barge-in.md` - the opt-in,
   default-off, headphones-only config option and its VAD-during-playback
   trigger, reusing task 2's cancellation core.
5. `task-v1.7.0-5-docs-and-release-verification.md` - PROJECT.md
   architecture update, config docs (including the headphones-only
   warning text), human-run end-to-end checklist for both mechanisms.

Only task 2 should be opened now.

## Acceptance criteria

- [ ] The hotkey reliably stops both TTS playback and the in-flight
      backend generation within a short, measured latency, and Jarvis
      begins listening for the next request, on any hardware.
- [ ] The experimental voice option is disabled by default; enabling it
      requires an explicit config change, and the config carries a
      prominent, clearly worded warning that it is unsupported outside
      headphone playback.
- [ ] With the voice option enabled over headphones, speaking while
      Jarvis talks interrupts it the same way the hotkey does.
- [ ] An interrupted turn (either mechanism) is visible in
      history/journal as interrupted, never silently dropped, and the
      journal's append-only invariant holds.
- [ ] The user's mic-sleep/privacy toggle contract is unchanged; neither
      interruption path activates while the mic is asleep or
      privacy-paused, and the toggle remains non-delegable.
- [ ] `python -m pytest` and Ruff checks are green for all non-hardware
      logic; hotkey and voice-path end-to-end checks are prepared
      human-run handoffs with exact commands.

## Stop conditions

- Stop if cancelling the in-flight Ollama stream turns out not to be as
  clean as the "what is already known" section above assumes (e.g.
  `httpx` leaves the underlying connection in a bad state on
  cancellation) - that is a wider backend-layer problem, not an
  interruption-feature detail.
- Stop if the interrupted-turn journal representation cannot be an
  additive schema change and would require reworking existing recorded
  event shapes.
- Stop if no unused `ctrl+alt+<letter>` binding is available without
  reassigning an existing hotkey - reassignment is a user-facing breaking
  change needing its own explicit decision, not a default.
