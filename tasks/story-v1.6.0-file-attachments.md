# Story v1.6.0: File attachments

**Status:** Planned, task cards approved.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (entry-point decision,
2026-07-18: attachments are added from the Journal view's input dock -
attach control and drag-and-drop - building on the v1.5.2 text input;
no new hotkey. Turn-source contract, limits, and media rules below are
unchanged.)
**Release:** v1.6.0 (moved from v1.5.0 by human decision, 2026-07-16: the
dialog journal took the v1.5.0 slot - see
`story-v1.5.0-dialog-journal.md` - because a persistent journal
adds a reason to keep using Jarvis and is infrastructure the attachments
story can later build on, while attachments improve input paths that
already have workarounds. Earlier move from v1.4.0: MCP integration was
promoted because it unlocks otherwise-impossible capabilities)

## User-facing goal

Let the user attach files to a Jarvis turn, including audio files, so Jarvis can
answer questions about their content without pretending that file upload is the
same feature as realtime microphone listening.

## Boundaries

- This story is planned for v1.6.0, after the v1.3.0 Control Center,
  v1.4.0 MCP integration, and v1.5.0 dialog journal foundations.
- Activation/warmup is not a prerequisite; its backlog story may land
  independently of file attachments.
- Task cards exist for planning, but implementation still depends on the
  Journal input dock from v1.5.2. Memory work from v1.5.3 may land before
  this story, but file attachments must not depend on memory retrieval or
  curated memory files.
- Treating MCP tool results/resources as attachments is out of scope here,
  but the turn-source contract must not preclude it.
- Treat model self-description as a capability hint only, not as a verified
  project fact.
- Audio and images must follow the verified Ollama media rule: both go through
  the `/api/chat` `images` field.
- Media is current-turn only by default; conversation history remains text-only
  unless a later verified design changes that.
- No new external capability beyond the v1.4.0 two-tier locality contract:
  attachments are processed locally; this story neither adds external
  network access nor relaxes the contract further.

## Preliminary Scope

- Add a file attachment turn source separate from microphone and clipboard.
- Initial file classes:
  - audio files, such as WAV/MP3/M4A;
  - image files, such as PNG/JPG;
  - text files with explicit size limits.
- Normalize audio into model-safe clips, respecting known audio constraints.
- Make truncation, chunking, or unsupported format decisions visible to the
  user.
- Add pure tests for validation, chunk planning, and payload construction.
- Add human-run checks for real uploaded audio behavior through local Ollama.

## Out of Scope for First Iteration

- Realtime listening changes.
- Broad PDF/DOCX/document ingestion.
- Long-form media summarization beyond model-safe chunks.
- Storing uploaded binary media in history.
- Cloud file processing.

## Acceptance Criteria Draft

- [ ] A file attachment creates a distinct turn source.
- [ ] Audio files are normalized/chunked before reaching the backend.
- [ ] Image files reuse the current-turn media path.
- [ ] Text files have explicit limits and visible truncation.
- [ ] Unsupported formats fail clearly.
- [ ] Payload construction follows verified Ollama media behavior.
- [ ] Human-run checks verify real uploaded audio behavior before `PROJECT.md`
      records it as a fact.

## Task cards

- `tasks/task-v1.6.0-1-attachment-policy-and-format-gate.md`
- `tasks/task-v1.6.0-2-attachment-domain-plan.md`
- `tasks/task-v1.6.0-3-text-attachments.md`
- `tasks/task-v1.6.0-4-image-attachments.md`
- `tasks/task-v1.6.0-5-audio-attachments.md`
- `tasks/task-v1.6.0-6-turn-orchestration.md`
- `tasks/task-v1.6.0-7-journal-upload-api.md`
- `tasks/task-v1.6.0-8-journal-attachment-ui.md`
- `tasks/task-v1.6.0-9-code-quality-entropy-review.md`
- `tasks/task-v1.6.0-10-release-verification.md`

## Stop Conditions

- Stop if uploaded audio behavior differs from microphone audio behavior in
  local Ollama and the difference affects architecture.
- Stop if file size/chunking policy has non-obvious privacy or UX trade-offs.
- Stop if supporting a file type requires a large parser/runtime dependency
  that is not justified by the first iteration.
