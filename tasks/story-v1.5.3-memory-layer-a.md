# Story v1.5.3: Memory layer A - session fork and curated memory files

**Status:** Completed.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.5.3 section; fork design
records the owner's decisions from the 2026-07-18 planning dialog).
**Created:** 2026-07-19. Owner decision (2026-07-19): implemented on
branches from current main, after v1.5.2 and before v1.6.0-7 resumes.

## User-facing goal

Give Jarvis its first memory across sessions: continue a past
conversation from the Journal view, and keep persistent curated context
(memory.md and self.md) that is injected into every session and remains
fully user-auditable.

## Boundaries

- Fork, not in-place continuation (cross-cutting rule 6): the source
  session's log is never appended to; a fork starts a new session with
  `continued_from: <session_id>` provenance metadata.
- The seed is a verbatim text-only tail within an explicit character
  budget, oldest-dropped-first. No summarization, no retrieval, no
  embeddings, no archive.
- Fork requires no transcripts: voice turns seed with the same text the
  model-facing history recorded for them (placeholder today, transcript
  when one exists later). Never block the fork on STT.
- Both memory files are user-edited only in this release. Jarvis's own
  write path ("remember this") requires the v1.6.1 builtin tool
  provider - deliberately files-and-injection first, tool write second.
- Cross-cutting rule 7 applies to the files: size-capped, visible and
  editable in the UI.
- Hidden mode: fork controls and memory editing are journal-surface
  features and are suppressed with it; memory file content must not be
  exposed through any unauthenticated or Hidden path.
- Runtime locality unchanged; everything is local files plus the
  existing authenticated transport.

## Design decisions (proposed here, confirmed by card approval)

- **Seed budget is a config setting** (`[memory]` section, working name
  `fork_seed_max_chars`, proposed default 12000 chars - roughly 3000
  tokens at the established 4 chars/token estimate). The budget is
  explicit and visible; a fork that drops turns to fit says so in the
  seeded session's provenance event.
- **PROJECT.md contract revision lands with the fork implementation**
  (same change): "the journal is not fed back into model context"
  becomes "not fed back except through explicit user-initiated fork
  seeding" - an explicit contract revision, not an erosion.
- **memory.md and self.md live under a config-driven directory**
  (proposed default: a `memory/` directory beside the journal root),
  each with its own size cap (config, proposed default 8000 chars per
  file). Both are injected as system-prompt additions at session start:
  memory.md as durable user/context facts, self.md as Jarvis's persona
  and self-knowledge.
- **Editing goes through the Journal-view surface** per cross-cutting
  rule 10 (the Status Console grows into a chat surface deliberately):
  a memory panel reachable from the Journal view, backed by
  authenticated GET/PUT transport endpoints.
- **The source session's age is carried by an explicit provenance seed
  line** (review decision 2026-07-19, revising the roadmap's "existing
  time-context mechanism" wording): `format_time_context()` renders
  only the current time and `ConversationHistory` stores no
  timestamps, so the existing mechanism cannot express the gap without
  new text anyway. The fork therefore prepends one system-style seed
  message rendered at fork time, stating that this session continues
  an earlier conversation and giving the source session's end
  timestamp in the same weekday + ISO 8601 format
  `format_time_context()` already uses. Together with the per-turn
  current-time context, the model sees the gap explicitly. No
  `ConversationHistory` shape change, no summarization - the line is
  deterministic template text, not generated content.

## Scope (ordered task cards)

- `tasks/done/task-v1.5.3-1-fork-seed-builder.md` - pure seed construction
  from a journal session replay.
- `tasks/done/task-v1.5.3-2-fork-orchestration-and-transport.md` - fork
  command, history seeding, provenance recording, contract revision.
- `tasks/done/task-v1.5.3-3-fork-ui.md` - "continue this conversation" in
  the Journal view.
- `tasks/done/task-v1.5.3-4-memory-files-core.md` - memory.md/self.md
  loading, caps, and system-prompt injection.
- `tasks/done/task-v1.5.3-5-memory-files-api.md` - authenticated read/write
  transport endpoints.
- `tasks/done/task-v1.5.3-6-memory-files-ui.md` - the memory panel
  (view/edit) in the Journal view.
- `tasks/done/task-v1.5.3-7-docs-and-release-verification.md` - PROJECT.md,
  config docs, human-run checklist.
- `tasks/done/task-v1.5.3-8-explicit-new-context-ui.md` - follow-up from
  release verification: make blank context creation an explicit UI action
  rather than an implicit side effect of the next input.

## Acceptance criteria

- [x] From the Journal view the user can continue a past session; the
      new session starts with a text-only verbatim tail seed within the
      configured budget and records `continued_from` provenance.
- [x] The source session's log is byte-identical after the fork.
- [x] Voice turns seed from recorded history text without transcripts.
- [x] memory.md and self.md content is injected at session start,
      size-capped, and both files are viewable and editable from the
      UI; edits apply from the next session start (or a documented
      explicit reload action).
- [x] PROJECT.md's journal-context statement is revised in the same
      change as the fork implementation.
- [x] Hidden mode suppresses fork and memory surfaces.
- [x] Blank context creation is an explicit, visible user action; the
      UI does not rely on implicit "next input creates a new context"
      semantics for a state-changing conversation boundary.
- [x] `python -m pytest` and Ruff checks are green; UI verification is
      a prepared human-run handoff.

## Stop conditions

- Stop if seeding cannot reuse `ConversationHistory` as-is and would
  require restructuring the history abstraction.
- Stop if the placeholder text recorded for voice turns turns out to be
  useless as seed material in practice (this is a design question about
  seed honesty, not something to paper over with generated text).
- Stop if prompt injection of both files plus the existing system
  prompt approaches context limits that measurably affect latency
  (measurement before architecture, cross-cutting rule 1-5 carryover).
