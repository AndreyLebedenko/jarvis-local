# Story v1.4.0: File attachments

**Status:** Backlog, not ready for task cards.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.4.0

## User-facing goal

Let the user attach files to a Jarvis turn, including audio files, so Jarvis can
answer questions about their content without pretending that file upload is the
same feature as realtime microphone listening.

## Boundaries

- This story is planned for v1.4.0, after the v1.3.0 Control Center foundation.
- Do not create task cards until v1.3.0 scope is clearer.
- Treat model self-description as a capability hint only, not as a verified
  project fact.
- Audio and images must follow the verified Ollama media rule: both go through
  the `/api/chat` `images` field.
- Media is current-turn only by default; conversation history remains text-only
  unless a later verified design changes that.
- Runtime locality remains unchanged.

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

## Stop Conditions

- Stop if uploaded audio behavior differs from microphone audio behavior in
  local Ollama and the difference affects architecture.
- Stop if file size/chunking policy has non-obvious privacy or UX trade-offs.
- Stop if supporting a file type requires a large parser/runtime dependency
  that is not justified by the first iteration.
