# Roadmap: v1.5.1 stabilization through unlimited conversation history (v1.8.0)

**Status:** Accepted roadmap (planning dialogs, 2026-07-18 and 2026-07-29).
**Branch:** roadmap-v1.5.1-v1.7.
**Predecessor:** `tasks/done/roadmap-v1.2-v1.4.md` (extends through v1.6.0;
this roadmap re-plans v1.5.1+ and supersedes that file's forward-looking
notes about "v1.5.1 or later" journal follow-ups).
**Context:** v1.5.0 (dialog journal) is released. Open bug reports from its
release verification are the starting point of this roadmap. The 2026-07-29
extension replaces the separate v1.7.1 consolidation and v1.7.2 retrieval
plan with one v1.8.0 architecture: an unbounded journal-backed history and a
bounded model-facing working context.

## Goal

Grow Jarvis from a fast local voice assistant into an AI companion through
small, dependency-ordered releases. The companion qualities targeted by this
roadmap, in priority order agreed with the owner:

1. **Memory across sessions** - the journal becomes the substrate of
   long-term memory: session continuation, curated fact files, and an
   unlimited conversation history that Jarvis can search and read without
   growing the normal Ollama request with the journal.
2. **New senses on command** - a camera module (local USB and LAN/RTSP),
   captured by Jarvis's own tool call, not only by hotkey.
3. **Delegated control** - Jarvis can switch a strict allowlist of its own
   settings on voice command, starting with the reasoning level.
4. **Conversational fluidity** - barge-in (interrupting Jarvis mid-speech),
   wake-word addressing, and later the emotion side channel.

Each release keeps the established rule: at most one major architectural
output per release; a second major decision splits into a later item.

## Cross-cutting rules

Rules 1-5 of `tasks/done/roadmap-v1.2-v1.4.md` (measurement before
architecture, pure-CI boundary, two-tier runtime locality, manual hardware
handoffs, stop conditions as real gates) remain in force unchanged. This
roadmap adds:

6. **The journal's append-only invariant is inviolable.** Every memory
   feature reads the journal or writes derived layers beside it; nothing
   rewrites or deletes recorded events as a side effect. Session
   continuation is a fork into a new session with provenance metadata,
   never appending to a closed session's log.
7. **Model-written memory is always user-auditable.** Any text the model
   writes and later reads back as its own memory (memory.md, self.md,
   archive annotations) must be size-capped, visible and editable in the
   UI, and written only through the audited tool path. Annotations
   augment raw records; they never replace them.
8. **No audio is auto-deleted before its transcript exists.** Interim
   disk-growth relief is visibility and manual deletion only; automatic
   media reduction arrives only with the consolidation pipeline
   (transcription first, then trim).
9. **Delegated settings control has a strict allowlist.** Privacy-relevant
   controls (microphone sleep, visibility mode, MCP module toggles, MCP
   server enablement) are never delegable to the model. Every delegated
   change flows through the audited tool path and is reflected by the
   existing engine-state-to-UI contract.
10. **The Status Console grows into a chat surface deliberately.** Text
    input, attachments, and memory editing enter through the Journal
    view's reserved input dock. This is a recorded identity decision
    (2026-07-18), not scope drift: surfaces stay thin clients sending
    explicit commands per `VISION.md`.

## v1.5.1 - Stabilization after the journal release

Purpose: close the reliability and honesty debts recorded during v1.5.0
release verification before any new feature work.

Scope:

- Fix the microphone shutdown/executor race
  (`tasks/bug_reports/2026-07-17-shutdown-microphone-executor-race.md`):
  a deterministic stop boundary for the blocking `stream.read()` before
  task cancellation and executor teardown, with a pure regression test and
  the human-run scenario re-check.
- Resolve the stale pywebview crash-guard question
  (`tasks/backlog/status-console-api-stale-pywebview-crash-guard.md`):
  either remove the silent-reject pattern or re-document its real reason.
- Triage the two non-code reports from 2026-07-17: annotate the retention
  report with the near/far consolidation decision (now part of v1.8.0) and define
  a recurrence protocol for the distorted-capture report (no blind fix).
- Microphone device-type quality and stability matrix (owner addition,
  2026-07-18): a human-run check script covering USB and Bluetooth
  microphones - capture quality, sleep/wake, stall/disconnect, clean
  shutdown - with verified per-device-class facts recorded in
  `PROJECT.md`.

Boundary:

- No new features, no journal UX work, no capture-path changes for the
  unreproduced distortion. Device-matrix findings become bug reports, not
  in-release fixes.

Story/task readiness: completed story card exists as
`tasks/done/story-v1.5.1-stabilization.md`; completed task cards 1-4 exist as
`tasks/done/task-v1.5.1-*.md`.

## v1.5.2 - Journal UX pack

Purpose: small, user-visible quality-of-life work on the Journal view that
v1.5.0 deliberately deferred, plus the interim disk-growth valve.

Scope:

- Copy to clipboard: select a whole Jarvis answer or an arbitrary fragment
  from the feed and copy it (explicit owner request, 2026-07-18).
- Thumbnails for images sent to the model (screenshots today) in the feed,
  served through the existing authenticated media transport.
- Disk-usage visibility for the journal (total and per-session size) and
  manual per-session deletion with a confirmation flow. Interim measure
  only; no automatic deletion (cross-cutting rule 8). Deletion must also
  update the rebuildable FTS index and respect Hidden mode.
- Text input from the Journal view's reserved input dock: a typed message
  becomes a new turn source on the existing shared `_start_turn()` path.
  Already planned in v1.5.0's layered design ("v1.5.1 or later"); pulled
  here because it is cheap and is the direct predecessor of v1.6.0's
  attachment entry point.

Boundary:

- No STT, no attachments, no session continuation.
- No re-layout of the feed: the input dock and audio tiles were reserved
  for exactly these extensions.

Story/task readiness: story card exists as
`tasks/done/story-v1.5.2-journal-ux-pack.md` with task cards
`tasks/done/task-v1.5.2-1..8-*.md` (created 2026-07-19 to unblock
task-v1.6.0-7; implemented on branches from current main, not from the
v1.5.1 tag - owner decision 2026-07-19).

## v1.5.3 - Memory layer A: session fork and curated memory files

Purpose: the first memory features, sized as journal extensions - continue
past conversations and give Jarvis persistent curated context.

Scope:

- **Session fork ("continue this conversation").** From the Journal view,
  the user selects a past session; a new session starts with
  `ConversationHistory` seeded from the tail of that session's turns
  within an explicit character budget, text-only, oldest-dropped-first.
  The new session records `continued_from: <session_id>` provenance
  metadata. Fork, not in-place continuation (cross-cutting rule 6):
  the source log is never appended to, context size stays controlled,
  and the seed is honest about being text-only. Time gaps between the
  source session and now are made explicit to the model (revised
  2026-07-19 at story review: the existing time-context mechanism
  renders only the current time, so the gap is carried by a
  deterministic provenance seed line in the fork - see
  `tasks/story-v1.5.3-memory-layer-a.md`).
- **memory.md** - a curated file of durable facts (user preferences,
  ongoing projects, standing context) injected into the system prompt at
  session start. Size-capped; readable and editable in the UI.
- **self.md** - Jarvis's persona file: identity, style, and knowledge
  about its own capabilities (for example, that it has switchable
  reasoning modes - data that later makes offers like "want me to raise
  the reasoning level?" possible without code changes). Same mechanism as
  memory.md: prompt injection, size cap, UI editing.
- Revise `PROJECT.md`'s "the journal is not fed back into model context"
  statement in the same change that implements the fork - this is an
  explicit contract revision, not an erosion.

Boundary:

- Both memory files are user-edited only in this release. Jarvis's own
  write path ("remember this") requires the builtin tool provider and
  lands in v1.6.1. This ordering is deliberate: files-and-injection first,
  tool write second.
- No summarization of forked sessions; seed is a verbatim tail within
  budget. Summary-plus-tail compression remains later work.
- No retrieval, no embeddings, no archive.
- Fork requires no transcripts: voice turns seed with the same text the
  model-facing history recorded for them (placeholder or transcript when
  one exists later). Do not block the fork on STT.

Story/task readiness: story card exists as
`tasks/story-v1.5.3-memory-layer-a.md` with task cards
`tasks/task-v1.5.3-1..7-*.md` (created 2026-07-19); the fork design
above records the owner's decisions from the 2026-07-18 planning dialog.

## v1.6.0 - File attachments via the journal chat surface

Purpose: deliberate file input as a new turn source (existing story), now
entered through the Journal view rather than a new hotkey.

Scope: as defined in `tasks/done/story-v1.6.0-file-attachments.md`, with the
entry-point decision (2026-07-18): attachments are added from the Journal
view's input dock (attach control and drag-and-drop), building on v1.5.2's
text input. The turn-source contract, normalization, limits, and verified
Ollama media rules from the story card are unchanged.

Additional planning note: the turn-source contract must not preclude media
arriving from a tool result - v1.6.2's camera depends on that seam (the
story card already records this boundary).

Story/task readiness: story card exists; task cards to be created after
v1.5.3.

## v1.6.1 - Builtin tool provider and delegated control

Purpose: extend the v1.4.0 tool registry with in-process builtin tools and
give Jarvis its first delegated control over its own settings.

Scope:

- **Builtin provider concept in the tool registry.** Registered tools whose
  dispatch is an in-process call, not an MCP client: same registry, same
  single interception point, same `ToolCallStarted`/`ToolCallFinished`
  audit events and localized `SystemEvent`s, `data_boundary = local`
  always. Visible in the Control Center tool list like MCP tools.
- **`set_reasoning_level`** - the first builtin tool. Semantics decided
  2026-07-18: the tool mutates the existing reasoning-level state and the
  change applies from the next accepted turn - the established
  "sampled at turn start" contract is untouched. The confirming reply
  ("Done, ready to reason") is an ordinary tool round trip. Hotkey, UI,
  and voice paths all mutate the same single state owner; the UI stays
  honest via the existing engine-state events.
- **Memory write tools** - append/update within memory.md and self.md size
  caps, making "remember this" work by voice. Writes are audited tool
  calls (cross-cutting rule 7).
- Record the delegation allowlist boundary in `PROJECT.md` (cross-cutting
  rule 9) in the same change.

Boundary:

- Exactly the tools above; no camera, no settings beyond reasoning level.
- Builtin tools are not toggled by the MCP module switch; their
  availability contract (always-on vs own switch) is a story-card
  decision, but they must never be silently conflated with the external
  MCP capability on the data-source axis.

Story/task readiness: story card exists as
`tasks/story-v1.6.1-builtin-tools-delegated-control.md` with task cards
`tasks/task-v1.6.1-1..4-*.md` (created 2026-07-20).

## v1.6.2 - Camera

Purpose: Jarvis's first on-command sense - static image capture from a
local USB camera and a LAN camera (owner's target device: TP-Link Tapo
C230), triggered by Jarvis's own tool call.

Scope:

- **Spike first, as a hard gate** (precedent: v1.3.1/v1.4.0 spikes): a
  human-run check script that grabs a frame from a local USB camera and
  from the Tapo C230 via RTSP (camera account required; stream URL of the
  form `rtsp://user:pass@<ip>:554/stream1`), sends each through the
  existing `images` path, and records answer quality, capture latency,
  and RTSP connect behavior in `PROJECT.md` before the module is built.
- **Native sensor module, not an MCP server** (owner decision,
  2026-07-18): the camera is a privacy-sensitive sensor like the
  microphone - it gets a module health chip, sound cues, and a
  user-facing privacy toggle with parity to mic sleep. Capture is exposed
  as a builtin tool (v1.6.1's provider) so "look at the camera" is a
  model-initiated tool call.
- **Media-from-tool-result contract**: the tool's image result enters the
  current turn's media through `ToolAwareDialog`, following the same
  current-turn-only rule as every other media source. This is the story's
  main architectural output.
- LAN camera capture carries `data_boundary = lan` and is reported on the
  data-source axis exactly like LAN MCP tools; the local USB camera is
  `local`. Off by default, enabled explicitly, per the two-tier locality
  contract.
- RTSP credentials live in the local config file in plain text; record
  this honestly in the config documentation.

Boundary:

- Static frames only; no video streams, motion detection, or recording.
- No cloud APIs of any kind; the Tapo cloud is never contacted.
- If frame quality from the spike is insufficient for useful answers,
  stop and re-plan before building the module.

Story/task readiness: story card exists as
`tasks/story-v1.6.2-camera.md` with task cards
`tasks/task-v1.6.2-1..5-*.md` (created 2026-07-20); task 1 is the spike
and remains the hard gate for tasks 2-5.

## v1.6.3 - Status Console UI reorganization

**Completed 2026-07-22.** Story and task cards are in `tasks/done/`.

Purpose: replace the accumulated scatter of buttons and inline forms
with three tabs - Status, Journal, Settings - organized by the nature
of the data (owner decision, 2026-07-20): live engine state on Status,
the conversation surface on Journal, cold configuration on Settings.

Scope:

- Three tabs plus a global header (honesty indicators and Open/Hidden
  visible on every tab).
- Status keeps runtime state and immediate controls: avatar/state,
  module chips, reasoning level, MCP toggle with the tool list, system
  events, Shutdown as the single destructive action.
- The configuration form (model, microphone, UI language, TTS voices,
  VAD) moves wholesale to Settings; the scroll-to-settings button
  disappears. MCP server configuration stays in `config.toml` - it
  never had a UI to relocate (owner decision, 2026-07-21).
- Status fits the default window without an initial scrollbar, and a
  growing MCP tool list cannot displace Shutdown.
- Context reset is deduplicated: the Journal's explicit "Новый
  контекст" (task-v1.5.3-8) remains the only reset control.

Boundary:

- Layout-only: no new features, no new engine state, no transport
  changes beyond what relocation strictly requires. Hidden mode
  semantics unchanged.

Story/task readiness: story card exists as
`tasks/done/story-v1.6.3-status-console-ui-reorg.md` with task cards
`tasks/done/task-v1.6.3-1..4-*.md` (1-3 created 2026-07-20; card 4,
Status vertical density, added 2026-07-21 from the review dialog).

## v1.6.4 - Observability: system log and user-facing request log

**Completed 2026-07-22.** Story and task cards are in `tasks/done/`.

Purpose: make failures diagnosable after the fact, and make "what did
Jarvis send to the model" answerable in the user's own language (owner
decision, 2026-07-21, from the v1.6.3 review dialog).

The split already exists in the code and is only half wired:
`publish_system_event()` takes both a detailed English `log_message`
and a `ui_message`, but `logging` is configured with no file handler,
so the detailed stream is lost outside a terminal, and `ui_message` is
a free-form engine string that never passes through the UI language
catalog.

Scope:

- A rotating system log on disk: detailed, English, local-only, not a
  UI surface. This is what a user attaches to a problem report.
- A user-facing record of each turn's request modalities in the events
  panel, delivered as a typed event and localized in the UI from the
  existing `last_request_*` keys.

Boundary:

- Content rule, binding for both logs: kinds, counts, durations, and
  sizes; never payload content - no transcripts, clipboard text, image
  data, or attachment contents.
- Local-only. No log shipping, no network sink, no telemetry; a local
  file sink opens no socket and is not a network capability under the
  runtime locality contract.
- Hidden mode semantics unchanged; the events panel must stay at the
  level of abstraction that makes it safe to leave visible.
- The Status chip strip from task-v1.6.3-4 stays. A log answers "what
  happened"; the strip answers "what is true now".

Story/task readiness: story card exists as
`tasks/done/story-v1.6.4-observability-and-logging.md` with task cards
`tasks/done/task-v1.6.4-1..3-*.md` (created 2026-07-21) and
`tasks/done/task-v1.6.4-4-system-log-model-request-line.md` (added
2026-07-22: task 2 found the file log had no record of any turn's
request, which inverted the scope statement above - the file was the
half assumed to already exist). **Completed 2026-07-22**: all four cards
done and the combined v1.6.3 + v1.6.4 human verification run passed.
Story and task cards are in `tasks/done/`. One gap is deliberately left
open and needs an owner decision before any code - the system log records
neither the opened microphone device name nor any capture level, so the
first real diagnosis made with these logs still had to be reconstructed
from journal wav files (see
`tasks/bug_reports/2026-07-22-quiet-microphone-capture-and-unselectable-device.md`).

## v1.7.0 - Interrupting Jarvis (hotkey default, experimental voice barge-in for headphones)

**Resequenced from the unversioned v1.7.x "Conversational fluidity" list
to v1.7.0 (owner decision, 2026-07-26)**. Consolidation and retrieval were
first shifted to v1.7.1 and v1.7.2, then superseded by the unified v1.8.0
history architecture on 2026-07-29. Wake-word addressing, the emotion2vec+
side channel, and the MCP egress watchdog stay in the unversioned v1.7.x
list.

**Re-scoped 2026-07-26 after task 1's spike came back no-go for
general-hardware AEC** (see `PROJECT.md`'s "Architecture v1.7.0 spike"
section and the story card's pivot note): Bluetooth headphones already
show near-zero self-hearing without any echo cancellation, but desktop
speakers kept producing VAD false positives on self-heard TTS across
every tested condition, even after fixing a real bug in the check script
and tuning the candidate. Owner decision: a hotkey becomes the primary,
hardware-independent interruption mechanism; voice-triggered
interruption survives only as an opt-in, default-off, headphones-only
experimental feature. General-hardware AEC is parked, not pursued
further - free software shipping to arbitrary user hardware has no
equivalent of a commercial smart speaker's fixed, lab-tuned acoustic
path, and ambient noise compounds with imperfect echo cancellation into
a harder problem than either alone.

Purpose: give the user a reliable way to interrupt Jarvis mid-response -
TTS playback and the in-flight backend response stop, and Jarvis starts
listening for the next request.

Scope:

- A hotkey (default-available, no opt-in) that cancels in-flight TTS
  playback and the in-flight backend stream unconditionally, on any
  hardware.
- Interrupted-turn representation in history/journal (append-only
  invariant, cross-cutting rule 6): an interrupted turn is recorded as
  interrupted, never silently dropped - for either trigger path.
- An opt-in, default-off, headphones-only experimental voice-triggered
  interruption, reusing the hotkey's cancellation mechanism, with a
  prominent config warning that it is unsupported outside headphone
  playback. No AEC.

Boundary:

- No general-hardware / desktop-speaker AEC path.
- Wake-word addressing, the emotion2vec+ side channel, and the MCP
  egress watchdog are separate future stories, not part of this one.
- No change to the user's mic-sleep/privacy toggle contract; the toggle
  stays non-delegable (cross-cutting rule 9).
- No resuming an interrupted turn - once interrupted, that turn is over.

Story/task readiness: story card exists at
`tasks/story-v1.7.0-barge-in.md`. Task 1 (AEC spike), task 2 (hotkey and
cancellation core), and task 3 (turn and journal handling) are completed
and closed. Task 4 (experimental voice barge-in) is deferred to backlog
(`tasks/backlog/experimental-voice-barge-in.md`, owner decision,
2026-07-29, not a technical blocker) - not scheduled next. Task 5 (hotkey
docs and release verification) is completed and closed. When task 4 is
picked back up, its voice-path docs and verification need a new task or an
explicit reopening of the completed card.

## v1.7.1 and v1.7.2 - Superseded memory-layer split

The original roadmap split long-term history into two releases:

- v1.7.1 built a near/far consolidation pipeline with voice transcription,
  session annotations, media reduction, and searchable derived text;
- v1.7.2 added a model-facing retrieval tool over that substrate.

Owner decision, 2026-07-29: do not implement that split. It described storage
and search mechanisms separately, but neither release delivered the actual
user-facing result on its own, and it left the unbounded in-memory
`ConversationHistory` unchanged. Both entries are superseded by v1.8.0 below.

The settled decisions from the old entries remain binding in v1.8.0:

- the journal is the immutable source of truth and derived data lives beside
  it;
- voice is transcribed before any automatic audio deletion;
- the active session is never archived and the near log keeps its original
  media;
- consolidation starts explicitly, not as silent background GPU work;
- model-written annotations remain size-capped, visible, editable, and
  traceable to source events;
- retrieval is local, provenance-bearing, and bounded;
- exact FTS retrieval is implemented and measured before a local semantic
  index is selected;
- retrieval never silently rewrites `memory.md`, `self.md`, or raw journal
  events.

## v1.7.3 - Reasoning-mode prompt sections

Purpose: let the user attach optional system-prompt guidance to the active
reasoning level without changing Ollama's existing `think` mapping or exposing
reasoning traces.

Scope:

- Optional `[prompts].reasoning_low`, `[prompts].reasoning_medium`, and
  `[prompts].reasoning_high` sections.
- Prompt values may be inline strings or prompt-file references using
  `@<file-path>`, resolved only under `./.jarvis/`.
- Effective prompt composition at turn start: base system prompt, memory/self
  material, then the sampled reasoning-level prompt section.
- A code optimization pass after implementation, focused on keeping config
  parsing, memory loading, and prompt composition responsibilities separate.

Boundary:

- No `reasoning_off` prompt. Off mode remains the base prompt only.
- No live reload, UI prompt editor, backend message-shape change, or exposure
  of `message.thinking`.
- Bad prompt references are startup config errors; they are not silently
  ignored.

Story/task readiness: story card exists as
`tasks/story-v1.7.3-reasoning-mode-prompts.md` with task cards
`tasks/task-v1.7.3-1..4-*.md` (created 2026-07-29).

Dependency note: complete this story before v1.8.0 replaces the current
message assembly. v1.8.0 consumes its effective system-prompt composition
contract; it must not reimplement reasoning-level prompt selection.

## v1.8.0 - Unlimited conversation history

Purpose: separate the complete conversation record from the finite working
context sent to Ollama. Jarvis retains a journal-backed history whose size is
limited by local storage and retention policy, while each model request stays
within a measured budget and can read relevant past events through local
Jarvis APIs and native tools.

Scope:

- An immutable raw journal plus a rebuildable, incrementally maintained
  derived history corpus for transcripts, annotations, exact search, event
  ranges, and provenance.
- Voice transcription and near/far consolidation as supporting mechanisms of
  unlimited history, not independent user-facing memory layers.
- Typed local read APIs and a dedicated read-only history tool provider.
  Common search-and-read operations are batchable so they remain useful
  inside the bounded tool loop.
- A working-context assembler that combines the effective system prompt,
  recent verbatim turns, bounded automatically retrieved passages, the
  current-turn time context, and the current request while reserving capacity
  for thinking, tool results, and the final answer.
- Prompt/context observability including Ollama prompt-token metrics, context
  composition metrics, index latency, and deterministic degraded behavior.
- FTS first. A measured Russian-language retrieval gate decides whether a
  later task inside the story adds local embeddings and which local index it
  uses.
- The existing retention-policy report is resolved by the consolidation and
  media lifecycle delivered inside this story.

Boundary:

- Jarvis-native APIs and tools only. No MCP history server or MCP adapter.
- No active-task planner, autonomous initiative, graph memory, or general
  agent runtime.
- No silent writes to curated memory files, raw journal events, transcripts,
  or annotations.
- No cloud inference, embedding, storage, or external service dependency.
- No change to the verified Ollama media transport, reasoning-trace isolation,
  current-turn-only media rule, or current-turn time-context semantics.
- "Unlimited" means independent of the Ollama context window, not infinite
  disk capacity. Storage use remains visible and governed by explicit
  retention rules.

Story/task readiness: umbrella story card exists at
`tasks/story-v1.8.0-unlimited-conversation-history.md`. Implementation task
cards are opened one at a time in the dependency order recorded there.

## Unversioned - Conversational fluidity candidates

Purpose: turn request-response into conversation. Barge-in was pulled
forward as v1.7.0 above (owner decision, 2026-07-26). The rest stay
unversioned candidates after v1.8.0, each its own story:

- **Wake word / addressing** (local openWakeWord or similar): Jarvis
  distinguishes being addressed from ambient speech, prerequisite for
  always-on room presence. Deliberately separate from the deferred
  proactive-initiative idea, which stays out of this roadmap.
- **emotion2vec+ side channel** (long-standing roadmap item): prosody of
  the user's speech as an input signal, CPU-capable bus subscriber.
- **MCP egress watchdog** (`tasks/backlog/mcp-egress-watchdog.md`): as
  external capabilities accumulate (MCP servers, LAN camera), declared
  data boundaries gain an observed-behavior check.

## Floating: activation and warmup

The existing backlog story (5 task cards under
`tasks/backlog/activation-warmup-*.md`) remains valid and depends on
nothing in this roadmap. Slot it into any pause between releases at the
owner's discretion.
