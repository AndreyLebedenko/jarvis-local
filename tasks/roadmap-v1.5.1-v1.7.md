# Roadmap: v1.5.1 stabilization toward memory, delegated control, camera, and conversational fluidity (v1.7.x)

**Status:** Accepted roadmap (planning dialog, 2026-07-18).
**Branch:** roadmap-v1.5.1-v1.7.
**Predecessor:** `tasks/done/roadmap-v1.2-v1.4.md` (extends through v1.6.0;
this roadmap re-plans v1.5.1+ and supersedes that file's forward-looking
notes about "v1.5.1 or later" journal follow-ups).
**Context:** v1.5.0 (dialog journal) is released. Open bug reports from its
release verification are the starting point of this roadmap.

## Goal

Grow Jarvis from a fast local voice assistant into an AI companion through
small, dependency-ordered releases. The companion qualities targeted by this
roadmap, in priority order agreed with the owner:

1. **Memory across sessions** - the journal becomes the substrate of
   long-term memory: session continuation, curated fact files, and later a
   consolidation/retrieval pipeline modeled on human long-term memory.
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
  report with the near/far consolidation decision (see v1.7.0) and define
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

## v1.7.0 - Memory layer B, part 1: consolidation (near/far journal)

Purpose: human-modeled long-term memory. The journal splits into a "near
log" (recent sessions, full media, replayable) and a "far log" (archive):
text only, voice transcribed to text, images heavily compressed, and -
central to the design - every archived session carries a model-written
annotation of what was discussed, which points matter, and why.
Consolidation is a comprehension step, not mechanical compression (owner
design, 2026-07-18).

Scope:

- Archiver pipeline: transcription of voice turns (gemma4's verified
  verbatim transcription; fills the journal schema's reserved
  `transcript` field), image downscaling, annotation generation, and the
  near-to-far transition by session age (configurable boundary; the
  active session is never archived).
- Explicit trigger first (owner decision, 2026-07-18): archiving runs on
  command or schedule ("Jarvis, process the archive"), never silently in
  the background. A background idle mode is a later, separate decision
  once an idle concept exists - this is the first workload where Jarvis
  uses the GPU outside a user turn, and VRAM/turn-latency contention must
  stay predictable.
- Annotations and transcripts are visible and editable in the Journal
  view; raw archived text is preserved in full (cross-cutting rule 7 -
  the annotation is an overlay, drift is always checkable against the
  source). Audio files are removed only after their transcript exists
  (rule 8).
- Extend the FTS index over transcripts and annotations (currently
  assistant answers only).
- Resolves the retention-policy report: this pipeline is the retention
  policy.

Boundary:

- No retrieval tool yet; this story produces the substrate.
- No change to the near log's fidelity guarantees: near sessions keep
  bit-identical audio.

Story/task readiness: needs a story card; boundary age and image
compression parameters are story-card decisions.

## v1.7.1 - Memory layer B, part 2: retrieval

Purpose: "remember when we discussed X" - on-demand enrichment of the
current turn's context from the journal and archive.

Scope:

- A retrieval builtin tool searching annotations and transcripts: FTS
  first; local embeddings with a Qdrant write path as a second step if
  exact/prefix matching proves insufficient (Russian morphology is the
  known FTS5 weakness).
- Retrieved passages enter the current turn's context with explicit
  provenance (which session, when), within a budget.

Boundary:

- Local inference/embedding only; no external services.
- Retrieval augments the current turn; it never silently rewrites
  memory.md or history.

Story/task readiness: needs a story card after v1.7.0 lands.

## v1.7.x - Conversational fluidity

Purpose: turn request-response into conversation. Ordered candidates, each
its own story:

- **AEC spike, then barge-in.** Echo cancellation on Windows so the
  microphone stays open while Jarvis speaks; user speech interrupts TTS
  and the response stream. Replaces the v1.0/v1.1 timing-window
  mitigations (busy-cooldown, mic auto-pause). The spike is a genuine
  research task; no timeline promises until it lands.
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
