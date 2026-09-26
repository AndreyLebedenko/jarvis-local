# Journal turns do not record their response mode or reasoning level

**Detected at commit:** `a008e68`.
**Date:** 2026-09-12.
**Detected by:** design review of the v1.9.2 spike's Journal-based phase, which
needs to replay past turns and must know how each one was produced.

## Symptoms

For a completed assistant turn in the Journal, there is no way to determine
afterwards which `ResponseMode` produced it, or at which `ReasoningLevel` it was
generated.

Concretely, for anyone selecting or replaying past turns:

- `text` and `voice` turns are indistinguishable from each other. Only
  `text_voice` is detectable, and only indirectly, by the presence of a
  `spoken_derivative` in the event metadata.
- The reasoning level in force at the time is not recoverable at all.

The practical consequence for a replay experiment: reusing a `voice`-mode answer
as a draft and revising it under the text output contract produces a "fix" that
consists of turning the answer into a canvas. That is contract conversion, not
an improvement, and it will score as one. The same hazard applies to any future
comparison, regression check, or quality audit that samples real turns.

## Current cause

`JournalRecorder.record_assistant` (`src/jarvis/journal/recorder.py:88-117`)
builds the assistant event's metadata from exactly three fields: `outcome`,
`spoken_derivative`, and `spoken_derivative_interrupted`. Nothing else about how
the turn was produced is written.

`ResponseMode` (`src/jarvis/dialog/response_mode.py:38`) lives in the dialog
layer, the UI, and configuration. It reaches the request composition in
`src/jarvis/app.py` and never reaches the Journal.

The system log's model-request line does not close the gap either.
`model_request_log_message` (`src/jarvis/core/model_request_log.py:26`) carries
input modality kinds, their count, audio duration, and prompt-budget telemetry,
plus `pass_kind` when it is not `PRIMARY`. `ModelRequestPassKind`
(`src/jarvis/core/lifecycle.py:43`) has only `PRIMARY` and `DERIVATIVE`, which
is the same `text_voice` signal already available from the derivative itself.
No response mode, no reasoning level. It is also a rotating file log correlated
to a turn only by timestamp, not a durable per-turn record.

This is an omission, not a deliberate exclusion: the metadata block's comments
explain why the spoken derivative and the outcome are metadata rather than text,
and say nothing about mode or reasoning level either way.

## Temporary decision

For the v1.9.2 spike's Journal-based sampling, the owner marks the response mode
by hand for each selected turn, and the reasoning-level requirement is dropped
from the selection record. At a sample of roughly 30 turns this costs minutes.

Two nearby alternatives were rejected:

- **Sample only turns without a `spoken_derivative`.** Cheapest to implement and
  wrong: it excludes `text_voice` while silently mixing `text` and `voice`,
  which is precisely the defect this report exists to prevent. Being unable to
  see a distinction is not the same as the distinction being absent.
- **Persist mode and reasoning level in the event metadata now.** The correct
  fix, but it is a runtime change to an append-only store, and the spike that
  found the gap is explicitly forbidden from modifying the runtime. Making the
  change under experiment pressure would also skip the question of what the
  field means for turns recorded before it existed.

## Future considerations and boundaries

- Adding the fields is additive metadata on the same event, in the same shape as
  `outcome`. It does not need a new event type or a schema migration.
- Historical events will not have the fields. Any consumer must treat absence as
  "unknown", never as a default mode or a default level. A sampling rule that
  silently reads absence as `text` reintroduces this bug in a harder-to-see
  form.
- The reasoning level is per turn and can change between turns; recording the
  effective level at turn acceptance is the meaningful value, not the setting
  read later.
- Scope boundary: this report covers only what the Journal records about how a
  turn was produced. It is not a request to record prompts, evidence packets, or
  request options, and it does not touch the retrieval corpus, which indexes
  `event.text` only.
