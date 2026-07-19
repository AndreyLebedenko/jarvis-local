# Task v1.6.0-6: Attachment turn orchestration

**Status:** Completed.
**Story:** `tasks/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-3, task-v1.6.0-4, task-v1.6.0-5.

## Summary

Wire accepted attachment plans into Jarvis's normal turn lifecycle as a
distinct source from microphone and clipboard, while preserving the
current-turn-only media rule and the busy guard.

## Context you need

- `src/jarvis/app.py`: `Orchestrator.on_utterance()`,
  `on_clipboard()`, and `_start_turn()` own the existing turn path.
- `src/jarvis/core/lifecycle.py`: add attachment-specific
  `TurnSource`/`ModelRequestInput` values narrowly.
- `src/jarvis/journal/recorder.py`: currently records voice and text user
  events; attachment journal behavior must be explicit.
- v1.4.0 model presentation layer: current-turn media survives stateless
  tool-loop follow-up requests.

## Boundary

- Orchestration and lifecycle only. Do not add browser upload controls or
  HTTP endpoints here.
- Do not alter microphone, screenshot, clipboard, reasoning-level, or MCP
  dispatch behavior except where tests prove shared lifecycle metadata
  needs the new attachment input type.
- Do not put attachment media into `ConversationHistory`.

## Requirements

- Add an orchestrator entry point for an accepted attachment plan from the
  Journal input dock transport.
- Preserve busy-guard behavior: rejected busy submissions must not consume
  pending screenshots, play success cues, or journal a user event.
- Publish `TurnAccepted` and `ModelRequestStarted` with attachment-specific
  metadata.
- Send planned text plus planned media to `backend.chat()` for the current
  turn only.
- Record the user turn in the journal with source `attachment` or another
  task-approved stable source label, including accepted text and attachment
  media references only if the journal-recording policy explicitly allows
  them.
- Keep tool-loop follow-up requests carrying the same current-turn media,
  matching the v1.4.0 correction for media survival.

## Acceptance criteria

- [x] Tests prove accepted attachment turns call the backend with expected
      messages, media, source, and input metadata.
      `tests/test_main.py`: `test_on_attachment_submission_sends_composed_text_
      and_image_media`, `test_on_attachment_submission_normalizes_audio_and_
      appends_clip_and_cue`, `test_on_attachment_submission_orders_media_
      images_then_audio`, `test_on_attachment_submission_reports_source_and_
      input_metadata`.
- [x] Tests prove attachment media is not stored in `ConversationHistory`.
      `test_attachment_media_is_not_stored_in_conversation_history`.
- [x] Tests cover busy rejection and backend failure recovery.
      `test_attachment_submission_is_ignored_while_busy` (also pins the
      pending-screenshot-survives and no-journal-event guarantees),
      `test_attachment_submission_backend_failure_plays_error_and_clears_busy`.
- [x] Tests prove existing voice and clipboard turn behavior is unchanged.
      Full pre-existing suite (1057 tests) passes unmodified; no voice/
      clipboard test was touched, only extended (`_FakeJournalRecorder` gained
      a `user_text_sources` list, additive and unused by prior assertions).
- [x] `python -m pytest` and Ruff checks are green.
      Full suite: 1069 passed, 1 skipped. Ruff check and format: clean.

## Outcome

`Orchestrator.on_attachment_submission(typed_text, plan)` (`src/jarvis/app.py`)
is the new entry point, callable directly by task-v1.6.0-7's future transport
(mirrors `StatusConsoleApi`'s existing direct-call pattern for other transport-
driven control actions, rather than a bus event - there is no hardware-driven
producer here the way `on_utterance`/`on_clipboard` have). It composes
`compose_turn_images(plan)` for image media and `compose_turn_text(typed_text,
plan)` for the outgoing message, matching the policy's "images first" default,
then resolves the one plan item planning could not fully settle: an accepted
`pending_audio` item is run through `normalize_audio_attachment()`, and on
success its clips are appended to media (images-then-audio, per the policy's
open item) and its cue appended to the composed text. `_start_turn()` then
carries out the shared busy-guard/history/journal/backend-call path exactly as
it already does for voice and clipboard turns - no changes were needed there
beyond a new `TurnSource.ATTACHMENT` branch for journal recording.

`core/lifecycle.py` gained `TurnSource.ATTACHMENT` and three granular
`ModelRequestInput` values (`ATTACHMENT_IMAGE`, `ATTACHMENT_AUDIO`,
`ATTACHMENT_TEXT`), one entry per accepted image/audio-file/text-file present,
mirroring the existing one-entry-per-attached-thing shape voice turns already
use for `AUDIO`/`SCREENSHOT`. Journal recording reuses
`JournalRecorder.record_text_user()`'s existing `source` parameter with
`source="attachment"` - no media reference is ever written, matching that
method's pre-existing text-only contract (only `record_voice_user()` writes a
journal media file), which is what "only if the journal-recording policy
explicitly allows them" resolves to here. This `source` parameter existed
before this task but had never actually been exercised with a non-default
value by any test; `tests/test_journal.py::
test_recorder_writes_a_custom_source_label` closes that gap against the real
`JournalRecorder`/`JournalStore`, not just the orchestrator-level fake.

**Post-plan audio rejection.** `plan_attachments()` only header-probes audio
duration, so an item it accepted can still fail real decode inside
`normalize_audio_attachment()` (e.g. truncated data past a valid header).
Per the story's repeated never-silent stance, this is reported through the
existing `publish_system_event()` WARN channel (same mechanism as e.g. a
failed warm-up) rather than silently dropped - the rest of the submission
(typed text, images, any other attachment) still reaches the model.
`test_on_attachment_submission_undecodable_audio_warns_and_continues` pins
both halves: the turn proceeds without the audio, and a WARN `SystemEvent`
naming the file is published.

**Scope decision, not re-litigated by tests:** this task assumes its caller
never submits a wholly empty request (no typed text, zero accepted
attachments) - task-v1.6.0-7 owns request-level validation before an
attachment submission ever reaches the orchestrator, matching how
`ClipboardSubmitted.is_empty` is decided by `clipboard_input.py`, not
`on_clipboard()`, before the orchestrator sees it.

**Shared-lifecycle fix, in scope per this task's own boundary** ("except
where tests prove shared lifecycle metadata needs the new attachment input
type"): `TurnSource` went from two values to three, and
`RuntimeStateTracker._on_turn_accepted()` used to be a binary `if/else` that
would have silently mapped every `ATTACHMENT` turn to the wrong
"processing_text" substatus. Replaced with an exhaustive
`_TURN_SOURCE_SUBSTATUS_KEY` dict plus a new `"processing_attachment"` catalog
key (`ui/text.py`, both `en`/`ru`, covered by the existing
`test_every_message_key_exists_in_every_language` completeness test) and a
`test_turn_source_selects_the_thinking_substatus` extension.

**Tool-loop media survival** (the v1.4.0 correction) needed no code change:
`ToolAwareDialog.chat()` already keeps whatever `images_b64` it receives on
the original user message across every follow-up request, generically, not
keyed to voice/screenshot specifically (`tests/test_tool_presentation.py::
test_native_tool_followup_retains_media_on_the_original_user_message` already
exercises this with plain placeholder strings). Since attachment media flows
into `_start_turn()`'s existing `media_b64` parameter the same way voice/
clipboard media does, it automatically inherits this guarantee.

No browser upload controls or HTTP endpoints were added, per the task
boundary; `tasks/task-v1.6.0-7-journal-upload-api.md` is the future caller of
`on_attachment_submission()`. The one JS/UI touch is Review fix 2 below - a
direct consequence of the new `ModelRequestInput` values reaching the
already-shipped Status Console, not new attachment UI (still task-v1.6.0-8's
job).

**Review fix 1 (P1):** the three new `ModelRequestInput` values reach the
already-wired Status Console through the existing `ModelRequestStarted` ->
`last_model_request` projection. `status_console_ui/app.js`'s
`applyLastModelRequest()` looks up `uiString("last_request_" + item.kind)`,
and `uiString()` throws on an unrecognized key - `strings.js` had entries
only for `audio`/`screenshot`/`clipboard`, so the first live attachment turn
would have thrown inside that delta handler. Fixed by adding
`last_request_attachment_image/audio/text` to both the `en` and `ru`
catalogs. The existing static-analysis completeness test
(`test_every_uistring_lookup_key_exists_in_the_dictionary`) cannot catch this
class of gap - it explicitly excludes the `"last_request_"` prefix because
the lookup key is built dynamically - so this closes it from the Python side
instead: `tests/test_ui_i18n.py::
test_every_model_request_input_has_a_last_request_label` asserts every
`ModelRequestInput` member has a matching catalog key, and will fail the
same way for any future addition to that enum.

**Review fix 2 (P2):** `applyLastModelRequest()` also only rendered the
duration suffix for `item.kind === "audio"`, so an attachment-audio turn's
`audio_duration_seconds` (which `on_attachment_submission()` does populate)
silently never appeared in the UI even once fix 1 stopped it from throwing.
The same narrowness existed on the Python side that builds the payload:
`ui/transport.py`'s `_on_model_request_started()` gated
`audio_duration_seconds` on `input_kind is ModelRequestInput.AUDIO`
specifically, dropping it from the JSON payload entirely for
`ATTACHMENT_AUDIO`. Fixed on both sides: `transport.py` now checks
membership in `_AUDIO_DURATION_INPUTS = {AUDIO, ATTACHMENT_AUDIO}`, and
`app.js` checks membership in the parallel `_AUDIO_DURATION_KINDS` set.
`tests/test_ui_transport.py::
test_server_projects_attachment_audio_duration_like_mic_audio` drives a real
`ATTACHMENT_AUDIO` `ModelRequestStarted` through the actual bus-wired
`UiTransportServer` and pins `duration_seconds` in the resulting snapshot.
Both new tests were confirmed to fail without their respective fix (git
stash of the fix showed both red) before being confirmed passing with it.

Reviewed and approved by the human (no findings); card marked `Completed.`
and moved to `tasks/done/`.

