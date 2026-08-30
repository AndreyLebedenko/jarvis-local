# Roadmap: v1.9.0 through v2.0

**Status:** Accepted roadmap update (owner planning dialog, 2026-08-30).
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
discussing the broader v2.0 direction.

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

## v2.0 - Canvas-guided voice

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

- v2.0 is exploratory until a spike proves model compliance with the tagged or
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
