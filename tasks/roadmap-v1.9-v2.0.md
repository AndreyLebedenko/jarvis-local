# Roadmap: v1.9.0 through v2.1

**Status:** Accepted roadmap update (owner planning dialog, 2026-08-30). Amended
2026-08-31 (owner planning dialog): v2.0 is now the functional self-model
(idle-time reflection); the former v2.0 "Canvas-guided voice" moves to v2.1.
**Branch:** codex/document-mode3-canvas-voice-contract.
**Predecessor:** `tasks/done/roadmap-v1.5.1-v1.8.0.md`, which planned the v1.5.1
stabilization through the v1.8.0 unlimited-history arc and is now removed as
the active roadmap. Historical story/task references to it remain provenance
for already-completed work.
**Context:** v1.8.x made the Journal a durable, searchable conversation
substrate. v1.9.x turns response shape itself into a user-facing capability:
Text-only, voice-only, and Text + voice.

## Goal

Make Jarvis better at producing answers that can be inspected, remembered, and
heard without forcing one format to serve every purpose. The central product
direction is a two-layer answer model:

- a canonical visual/text canvas that is authoritative for memory, retrieval,
  provenance, and later reasoning;
- a spoken guide/commentary that helps the user understand or navigate that
  canvas without pretending to be a separate source of facts.

This is explicitly not a lowest-latency-only roadmap. Jarvis keeps single-pass
low-latency modes, but Text + voice is allowed to spend extra local inference
when that buys a better human experience.

## Naming note

Working name for the future capability: **Canvas-guided voice**.

Rejected names for now:

- `Voice-rich`: too vague; it sounds like better TTS quality rather than a
  structured relationship between visible content and speech.
- `Rich voice`: same problem, and it underplays the authoritative canvas.
- `Voice canvas`: suggests voice itself is the source artifact, which is the
  opposite of the current provenance model.

Use "Text + voice" for the shipped mode label. Use "canvas-guided voice" when
discussing the broader v2.1 direction.

## Cross-cutting rules

1. **The canvas stays authoritative.** If a spoken derivative or future spoken
   block diverges from the visible text canvas, the canvas wins. The spoken
   layer is a rendering/navigation problem, not a competing fact source.
2. **Indexing must preserve provenance.** New searchable text surfaces must
   identify what they are: raw event text, transcript overlay, annotation,
   spoken derivative, archive summary, or another derived layer. The model must
   be able to tell what a retrieved passage is based on and where it came from.
3. **Locator search is different from memory retrieval.** A human may search by
   a phrase they heard. That can locate a turn, but it must not silently promote
   spoken derivative text into model memory.
4. **Latency trade-offs are user-facing.** Single-pass modes remain the
   low-latency path. Any multi-pass or interleaved voice experience must say
   what latency it adds and why the experience is worth it.
5. **No raw-journal rewrites.** New indexes and overlays remain rebuildable
   derived data beside the append-only journal.
6. **Filename identity beats prose path drift.** Planning docs may refer to a
   unique project file by filename even when the file later moves between
   workflow directories. Strict paths are required only where the path is part
   of an executable or storage contract.

## v1.9.0 - Response modes

Purpose: ship the user-facing response-mode foundation.

Scope:

- Mode 1: Text-only, the default low-latency visual answer.
- Mode 2: Voice-only, a single-pass self-contained spoken answer.
- Mode 3: Text + voice, a two-pass answer where pass 1 streams the canonical
  text canvas and pass 2 speaks a reasoning-off derivative over that exact
  canvas.
- Hotkey and UI controls for switching modes, with the running mode separate
  from the restart-to-apply default.
- Journal persistence of the spoken derivative inside the same assistant event,
  shown as a collapsed "spoken aloud" block and excluded from retrieval/memory.

Boundary:

- No indexer changes beyond preserving the current exclusion of
  `spoken_derivative`.
- No single-pass tagged multi-channel protocol.
- No interleaving of canvas and voice blocks.

Story/task readiness: story card exists at
`tasks/story-v1.9.0-response-modes.md`; completed task cards 1, 2, 3, and 3b
exist under `tasks/done/`. Task 4 and task 5 remain the next story work unless
the owner resequences them.

## v1.9.1 - Provenance-aware indexing and search surfaces

Purpose: make the history/indexing layer understand not only *text*, but what
kind of text it is and what it is based on.

Scope:

- Review every text-bearing surface currently available to search/retrieval:
  raw user/assistant event text, voice transcript overlays, generated/edited
  annotations, archive summaries, and mode-3 spoken derivatives.
- Define a typed indexing contract that preserves source kind, derivation kind,
  target event/range/session, and whether a surface is eligible for automatic
  retrieval, explicit model-facing search, UI-only Journal search, or
  locator-only search.
- Add locator-only support for `metadata.spoken_derivative` if the design
  proves clean: a query may match phrases the user heard, but the result must
  return the owning assistant event and hydrate/display the canonical
  `event.text` as the authoritative canvas.
- Ensure model-facing retrieval can distinguish "this is raw text", "this is a
  transcript", "this is an annotation", and "this is a locator match from a
  spoken derivative" rather than flattening derived text into ordinary memory.
- Update tests around retrieval candidates, Journal search, working-context
  rendering, and search tool output so provenance is visible at the boundaries
  that matter.

Boundary:

- No change to the mode-3 generation pipeline unless needed to expose already
  stored metadata cleanly.
- No automatic promotion of spoken derivatives into memory.
- No semantic meaning assigned to voice phrasing beyond locating the canonical
  turn it came from.

Open design questions:

- Should spoken-derivative locator search live in a physically separate index,
  a separate FTS table, or a typed field in a unified projection?
- Should locator-only matches be available to the model through
  `search_history`, or only to the Journal UI until a stricter model-facing
  contract is designed?
- How should ranking blend a locator match against a canonical-text match
  without implying equal epistemic status?

## v1.9.x - First-pass canvas prompt experiments

Purpose: test whether Text + voice improves when pass 1 knows, explicitly, that
pass 2 will later speak a guide over the result.

Scope:

- Compare prompt variants for mode-3 pass 1:
  - current "canonical rich answer" wording;
  - "authoritative visual answer canvas";
  - "complete inspection/citation canvas; do not optimize for being read
    aloud";
  - stricter variants that ask for tables/formulas/source blocks when useful.
- Evaluate with tasks that naturally strain voice output: tables, code,
  exact formulas, lists with caveats, links, and mixed Russian/English
  technical explanation.
- Record whether the second pass produces better spoken guidance when the first
  pass is framed as a canvas.

Boundary:

- Prompt spike first; no production prompt change without recorded examples.
- The canvas must remain readable and user-facing. It must not become a raw
  scratchpad or private intermediate dump.

## v2.0 - Functional self-model (idle-time reflection)

Working name: **functional self-model**. Origin: the standalone "VAC Harness"
PoC (`D:\AI\VAC`, brief dated 2026-08-31). The PoC proves an idea, not a
delivery shape: its git-backed storage, separate `Aura/` instance directory, CLI
surface, YAML commit files, and blocking two-model loop are PoC artifacts and do
not carry into Jarvis. What carries in is the protocol idea below, re-expressed
in Jarvis primitives (event bus, append-only Journal, single local model).

Purpose: give Jarvis a stable, versioned, correctable model of its own
*observable behavior*, so it can better model the user - specifically the user's
model of Jarvis. The self-model is strictly functional and behavioral: observed
behavior is evidence, functional explanation is hypothesis. It must never claim
introspective access to weights, hidden states, hardware, or inner experience.
This aligns with the project's existing honesty discipline.

Architecture in Jarvis terms:

- **Substrate is the existing append-only Journal**, not git. Reflection events
  are journaled; the self-model is a derived, versioned projection over them,
  rebuildable beside the raw journal (cross-cutting rule 5). No new storage
  engine, no git repo, no separate instance directory.
- **General idle-time cognition queue with typed jobs.** The queue is not
  self-model-specific; "analyze self-model influence on the last answer" is job
  type 1. Other job types (review weakened observations at their `review_after`,
  consolidate observations, summarize long dialogues) reuse the same scheduler.
  Build it general, not as a one-off.
- **Enqueue is cheap and off the voice path.** On turn completion a lightweight
  pointer to the journal entry is enqueued through a simple salience filter
  ("interesting only" from the start - not every turn), so the live loop pays
  almost nothing.
- **Idle-gated worker.** A background worker drains the queue only during idle
  (`not is_busy()`), after a debounce; the debounce duration is a config option
  in seconds.
- **Single shared model, independent config block.** There is one resident model
  (VRAM is already committed). The reflection worker uses that same model, but
  its access is described by a fully independent config block mirroring
  `[backend]` - currently identical in every value except, possibly, the
  thinking/reasoning level. The independence is contractual, so the two can
  diverge later without entangling live inference config.
- **The worker is preemptible - the single hardest invariant.** Because
  reflection and live response contend for the same GPU, any in-flight
  reflection inference is cancelled the instant the user speaks and its job is
  requeued. The event bus already propagates `CancelledError` cleanly.
- **Once-coherent commits.** A reflection either commits a whole new self-model
  version or nothing; the next live turn always reads one complete version,
  never a half-applied state.
- **Quality gates on reflection output.** A one-word evaluation is not evidence
  for a self-model change (a recorded PoC finding).

Phasing:

- **Phase 1 - passive loop only.** The self-model is written and versioned but
  is NOT injected into the live system prompt. This is observable, testable with
  logic-only automated tests, and carries no persona-drift risk. Owner reviews
  the passive output before deciding the next step.
- **Phase 2 - prompt injection (deferred decision).** Only after reviewing
  Phase 1 do we decide whether and how the current self-model version feeds the
  live prompt. This is where user-facing persona-drift risk lives; PoC v0004
  already anchors stability to append-only observations as a mitigation.

Boundaries:

- **No proactive speech.** The reflection loop updates internal state only; it
  never initiates dialogue. This is a second cognition context that never speaks
  unprompted, so it sidesteps the deferred dual-context/proactive-initiative
  blocker rather than depending on it.
- **Runtime locality preserved.** Reflection uses the configured local model
  only. Any future cloud/side-model access is an explicit, off-by-default
  per-component capability per the runtime-locality contract, not a default.
- **Testing per protocol.** Automated tests cover pure logic (queue behavior,
  salience filter, idle/debounce gating, self-model projection updates,
  config parsing). Anything touching the live model or VRAM is a human-run
  handoff.

Decisions settled 2026-08-31 (owner): salience filter from the start; both a
debounce and a config'd idle-seconds option; single shared model with an
independent `[backend]`-shaped config block; passive loop first.

Open design questions (deferred until a story card):

- Salience filter definition: what makes a turn "interesting" enough to enqueue.
- Structured observations layer (confidence, scope, status, counterevidence,
  `review_after`) as the self-model's internal shape - the PoC's recommended
  next feature.
- Whether Phase 2 prompt injection is gated by a flag and how the self-model
  section is bounded in the prompt to contain drift.

## v2.1 - Canvas-guided voice

Purpose: explore the larger capability hinted by Text + voice: a structured
multi-channel answer where Jarvis can build visible content and guide the user
through it by voice with lower perceived delay than today's two-pass mode.

Candidate directions:

- **Single-pass tagged output.** One backend response contains separate
  `canvas` and `voice` channels. The UI renders only canvas text; TTS speaks
  only voice text; the Journal stores both with clear provenance.
- **Interleaved block protocol.** The model can alternate visible blocks and
  spoken guide blocks, for example a paragraph/table/formula followed by the
  voice explanation tied to that block. This could let speech begin before the
  entire answer is complete while preserving the canvas relationship.
- **Block identity and references.** Spoken blocks may target canvas block ids,
  so "look at the second column" is grounded in a specific rendered object.
- **Streaming parser and recovery.** The runtime needs a safe parser for partial
  tagged output, broken tags, cancelled turns, and incomplete blocks before this
  can be production behavior.
- **Journal and replay model.** The Journal must represent visible blocks,
  spoken blocks, and their relationships without turning spoken commentary into
  independent memory. Replay should know whether to replay a whole answer, one
  spoken block, or a block range.

Boundary:

- v2.1 is exploratory until a spike proves model compliance with the tagged or
  interleaved protocol.
- Do not replace the v1.9 two-pass Text + voice mode until the single-pass or
  interleaved design has better measured behavior on latency, tag stability,
  factual preservation, and recovery from malformed output.

## Floating candidates

- Wake-word/addressing and experimental voice barge-in remain future
  conversational-fluidity work.
- emotion2vec+ remains a possible prosody side-channel.
- MCP egress watchdog remains relevant as external capabilities accumulate.
- Activation/warmup remains valid if perceived latency becomes the next
  bottleneck.
