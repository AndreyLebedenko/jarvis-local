# Story v1.7.0: Interruption of playback and voice call (barge-in)

**Status:** Proposed. Draft for review; no task cards opened yet.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.7.0 section). Resequenced
from the unversioned v1.7.x "Conversational fluidity" list to v1.7.0
(owner decision, 2026-07-26), ahead of memory consolidation/retrieval,
which shifted to v1.7.1/v1.7.2 accordingly. Wake-word addressing, the
emotion2vec+ side channel, and the MCP egress watchdog stay separate
future stories in the unversioned v1.7.x list.
**Created:** 2026-07-26.
**Replaces:** the v1.0/v1.1 timing-window mitigations for Jarvis hearing its
own TTS output - `Orchestrator.finish_turn()`'s busy-cooldown and
`AudioInput.auto_pause_for_speech()`/`auto_resume_after_speech()` (mic
stops capturing the moment Jarvis starts speaking, resumes after
`vad.resume_cooldown_seconds`). See PROJECT.md's "No echo cancellation in
v1.0" verified-facts entry for the full history of both mitigations. This
story does not layer onto them; a working AEC path removes the need for
the auto-pause step specifically (the busy-cooldown fallback may still be
useful for turns that produce no speech at all - a task-card decision).

## User-facing goal

Speaking while Jarvis is talking interrupts it, the way interrupting a
person works: TTS playback stops, the in-flight backend response stops
generating, and Jarvis starts listening to the new request as a fresh
voice call. Today the mic is deliberately deafened for the whole time
Jarvis speaks, specifically to avoid Jarvis hearing itself - so barge-in
requires keeping the mic live during playback without reintroducing that
self-hearing bug.

## Why a spike gates this story

Removing the auto-pause means the mic is open while the speakers play
Jarvis's own voice. Whether that is viable at all depends on facts nobody
has measured yet on this hardware/OS combination:

1. Can echo cancellation suppress Jarvis's own TTS output enough that VAD
   does not fire on it, while still firing promptly on real user speech
   over it? Windows exposes AEC at the OS/driver level for
   "communications" audio sessions; there are also userspace libraries
   (e.g. WebRTC's audio processing module, speexdsp) that take the
   outgoing TTS PCM as an explicit reference signal. Which of these is
   reachable from a Python/`sounddevice` stack, and whether either
   actually cancels well enough, is unknown.
2. If a software AEC library is the answer, it needs the exact TTS
   playback waveform as a reference signal in real time. `TtsOutput`
   (`src/jarvis/audio/tts.py`) currently only exposes ordered playback
   through `OrderedPlayback`/`_play_unit`; there is no tap for a
   reference signal today, and adding one may or may not be cheap.
3. Added latency/CPU cost of running AEC continuously during every
   response, on top of the existing VAD pass.
4. False-trigger rate after AEC: does room reverb, or `SoundCuePlayer`'s
   cues sharing the same output device, still leak through as apparent
   user speech?

The spike is a hard gate on the rest of the story, following the
established precedent (v1.3.1 graded-reasoning spike, v1.4.0 tool-calling
spike, v1.6.2 camera spike): a human-run check script exercises candidate
AEC approaches against live TTS playback, and the results - suppression
quality, latency, CPU cost, dependency shape - are recorded in
`PROJECT.md` before any module code is written.

## What is already known (narrows the spike's scope)

- Cancelling the in-flight Ollama stream looks tractable without new
  research: `OllamaBackend.iter_chat()` (`src/jarvis/dialog/backend.py`)
  is an async generator wrapping `httpx`'s streaming POST, with stream
  cleanup already in a `finally` block. `Orchestrator._handle_new_turn()`
  currently awaits `self._backend.chat(...)` directly; wrapping that call
  in an `asyncio.Task` and cancelling it from a barge-in handler should
  propagate cleanly through the generator's `finally`. The spike does not
  need to investigate this path - it is a task-2 implementation detail,
  not an open research question.
- `TtsOutput.wait_for_pending()` is today's only "stop" concept, and it
  means the opposite of barge-in: it waits for in-flight speech to finish
  for a graceful shutdown. Barge-in needs a genuine cancellation path
  through `OrderedPlayback` and the pending synthesis tasks, which does
  not exist yet.

## Boundaries

In scope:

- The AEC spike: candidate approaches tried against live TTS playback,
  go/no-go facts recorded in `PROJECT.md`.
- If the spike is a go: a mechanism that keeps the mic capturing during
  Jarvis's own speech, detects genuine user speech distinct from
  self-heard TTS output, and on detection cancels the in-flight TTS
  playback (including already-scheduled units) and the in-flight backend
  stream, then starts a new turn from the detected speech (the voice
  call).
- Recording what happens to an interrupted turn in history and the
  journal - the journal's append-only invariant (roadmap cross-cutting
  rule 6) means an interrupted turn is a recorded event, not a silently
  discarded one. Exact shape is a task-card decision.

Out of scope (separate v1.7.x stories per the roadmap, or unrelated):

- Wake word / addressing.
- The emotion2vec+ prosody side channel.
- The MCP egress watchdog.
- Resuming or continuing an interrupted turn - once barged in on, that
  turn is over; there is no "continue where I left off."
- Any change to the user-triggered mic sleep/privacy toggle contract.
  Barge-in only applies while the mic is already awake; it removes the
  automatic pause-during-Jarvis-speech behavior, not the user's own
  sleep/wake control, and the toggle stays non-delegable per cross-cutting
  rule 9.
- Wider VAD/turn-detection quality work beyond what barge-in specifically
  needs.

## Design decisions (proposed here, confirmed by card approval)

- **Spike is a hard gate.** No module code changes until `PROJECT.md`
  records suppression quality, latency, CPU cost, and the dependency
  decision, following the v1.3.1/v1.4.0/v1.6.2 precedent.
- **Barge-in cancels outright; it does not pause-and-resume.** The
  interrupted turn ends; its partial answer (whatever text/audio had
  already been produced) is recorded as an interrupted turn in
  history/journal rather than discarded, per the append-only invariant.
  The exact history/journal schema addition is a task-3 decision.
- **This replaces the existing mitigations, it does not stack with
  them**, per the roadmap's own framing ("Replaces the v1.0/v1.1
  timing-window mitigations").
- **Scope stays to barge-in only.** Wake word, prosody, and the egress
  watchdog are explicitly separate stories, even though they used to
  share an unversioned roadmap bucket with this one.

## Scope (ordered task cards, to be opened one at a time)

1. `task-v1.7.0-1-aec-spike.md` - human-run spike, hard gate; verified
   facts (or a no-go) into `PROJECT.md`.
2. `task-v1.7.0-2-core-mechanism.md` - AEC-backed capture path,
   speech-during-playback detection, cancellation of TTS playback and the
   backend stream. Depends on task 1 being a go.
3. `task-v1.7.0-3-turn-and-journal-handling.md` - interrupted-turn
   representation in history and the journal.
4. `task-v1.7.0-4-docs-and-release-verification.md` - PROJECT.md
   architecture update, config docs, human-run end-to-end checklist.

Only task 1 should be opened now; tasks 2-4 depend on its outcome and may
need to be re-scoped or the story stopped entirely if the gate fails.

## Acceptance criteria

- [ ] Spike facts (suppression quality, latency, CPU cost, dependency
      decision) are recorded in `PROJECT.md` before any module
      implementation starts.
- [ ] Speaking while Jarvis is talking reliably stops both TTS playback
      and the in-flight backend generation within a short, measured
      latency, and Jarvis begins listening to the new request.
- [ ] Ordinary playback (no user interruption) is not falsely triggered
      by Jarvis's own voice or by sound cues after AEC is in place -
      measured false-trigger rate is recorded.
- [ ] An interrupted turn is visible in history/journal as interrupted,
      never silently dropped, and the journal's append-only invariant
      holds.
- [ ] The user's mic-sleep/privacy toggle contract is unchanged; barge-in
      never activates while the mic is asleep or privacy-paused, and the
      toggle remains non-delegable.
- [ ] `python -m pytest` and Ruff checks are green for all non-hardware
      logic; the AEC spike and end-to-end barge-in check are prepared
      human-run handoffs with exact commands.

## Stop conditions

- Stop (report a no-go, do not proceed to task 2) if no candidate AEC
  approach suppresses self-hearing enough to keep the false-interrupt
  rate acceptable, or only does so at an unacceptable latency/CPU cost -
  the roadmap's hard gate.
- Stop if a viable AEC approach requires a dependency with licensing or
  Windows packaging problems comparable to the parked XTTS-v2/Kokoro
  spike outcome (see PROJECT.md's roadmap-after-v1.0 notes).
- Stop if cancelling the in-flight Ollama stream turns out not to be as
  clean as the "what is already known" section above assumes (e.g.
  `httpx` leaves the underlying connection in a bad state on
  cancellation) - that is a wider backend-layer problem, not a barge-in
  detail.
- Stop if the interrupted-turn journal representation cannot be an
  additive schema change and would require reworking existing recorded
  event shapes.
