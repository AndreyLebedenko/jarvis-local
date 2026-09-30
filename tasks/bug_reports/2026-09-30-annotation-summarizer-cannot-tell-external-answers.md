# Bug report: annotation summaries attribute external answers to "the assistant"

Commit: `924a5af` (main after v2.0 task 1). Detected during the independent
review of v2.0 task 2 (`task-v2.0-2-external-canvas-provenance.md`), on
branch `feat/v2.0-2-external-canvas-provenance` before its commit.

## Symptoms

Not yet observed by a user; found by code review. When the owner generates an
annotation for an `--mcp-mode` journal session, the local summarizer receives
each external answer as a line labeled `assistant / mcp_canvas` inside the
source block, with no explanation of what that source means. The instruction asks it to
attribute each claim to "user or assistant" (`DEFAULT_ANNOTATION_INSTRUCTION` in
`src/jarvis/journal/annotation_generator.py`, the "Указывай, кто сделал каждое
утверждение" sentence). The generated summary will therefore describe claims
from Claude (or another external model) as "the assistant's" claims, which
reads as Jarvis's own.

## Suspected cause

`format_source_block()` in `src/jarvis/journal/annotation_generator.py`
renders each event as `role / source`, so an external answer appears as
`assistant / mcp_canvas`. Nothing tells the summarizer what `mcp_canvas`
means, and the instruction offers only two authors.

## Temporary decision

Leave it for now. The provenance contract is already safe: v2.0 task 2 maps
any annotation of a session containing an `mcp_canvas` event to
`EXTERNAL_ANNOTATION`. That kind is never auto-retrieved and is labeled as
external with its caller in `search_history`. Only the wording inside the
generated text stays ambiguous. Fixing it means changing the annotation
prompt or the source-block format, which is outside task 2's boundary (no
prompt or generator changes). A prompt change also needs its own examples
before it ships.

Rejected nearby alternatives:
- Skipping annotation generation for `--mcp-mode` sessions would contradict
  the owner's constraint that annotations keep working in that mode.
- Relabeling the role in the source block alone, without an instruction
  change, leaves the summarizer with an author category it was never told
  about.

## Future considerations

- Candidate fix: `format_source_block()` renders external events with an
  explicit author label (for example "external answer from <caller>"), and the
  annotation instruction names that third author kind. It fits v2.0 task 6
  (Journal surfaces) or a small follow-up card after v2.0.
- Verify with a real `--mcp-mode` session: the summary must name the external
  model, not "the assistant".
- Boundary: this is about annotation text only. Retrieval eligibility and
  labeling are settled by task 2 and must not change here.
