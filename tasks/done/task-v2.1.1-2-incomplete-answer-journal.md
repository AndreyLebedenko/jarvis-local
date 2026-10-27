# Task v2.1.1-2: An incomplete answer reaches the Journal without waiting for speech

Status: Completed.

Story: `tasks/story-v2.1.1-proxy-speech-modes.md`, task 2 (Size: S).
Origin: `tasks/bug_reports/proxy-incomplete-answer-journal-written-after-speech.md`.

## Problem

On a failed external stream (timeout, bad stream, truncated), `answer/answer_presenter.py`
queues the exception behind the sentences already shown; `present()` sees it only after
every earlier sentence is spoken. Only then the pipeline posts `ANSWER_INCOMPLETE`, and only
that notice makes `reporting/journal_writer.py` flush the buffered answer. Live run
2026-10-27: the Journal `proxy_answer` and `proxy_notice` were written 89.6 s after the send
although the stream failed at the 60 s deadline.

## Design

1. When the stream or restoration fails, the Journal write of the answer shown so far
   (`proxy_answer` with `incomplete=true`) and the notice happen at the moment of the
   failure, not after speech. Speech of the sentences already shown continues to the end.
2. Exactly one `ANSWER_INCOMPLETE` notice per failed request, with the same detail as today.
   The user-visible order in the chat is: shown sentences, then the notice.
3. The reader of the stream still never waits for speech (the 3debd11 behavior stays).
4. A normal completion and a user interrupt behave exactly as before. If the interrupt path
   shows the same delay, report it in the outcome instead of changing it here.
5. Reproduce first: a test with a stream that yields sentences and then raises, and a held
   speaker; assert the Journal write and the notice happen while the speaker is still held.

## Boundary

`answer/answer_presenter.py`, `request/request_pipeline.py`, and
`reporting/journal_writer.py` only where the failure requires it, with their tests. No change
to the external client, the timeout, restoration, TTS, the gate, config, or the UI.

## Acceptance criteria

- [x] The failing-stream test with a held speaker fails before the change and passes after.
- [x] Tests: exactly one notice; shown sentences still spoken; normal completion unchanged;
      failure before any sentence (no answer text) unchanged.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` are green.

## Outcome (2026-10-27)

Option A (owner): the presenter owns the incomplete notice for stream and restoration
failures. `_show_arriving` posts `ANSWER_INCOMPLETE` at the moment of failure without
speech (the Journal writer flushes the answer then) and returns the notice; `present()`
speaks the fixed sentence after the shown sentences and swallows a later voice-session error
when the failure was already reported, so exactly one notice results. The pipeline except
path stays for errors outside the stream. New `Reporter.speak_notice` and
`external_error.error_kind_of`. Four new tests in
`tests/test_personal_proxy_service_pipeline.py`. Full suite green except the known timezone
failure of `tests/test_journal.py::test_new_session_id_uses_sortable_local_timestamp_prefix`.
Limits: when the voice is already failing, the spoken sentence is skipped (the notice is
still shown and journaled); the Journal flush is verified through a fake sink, not yet in a
live run.
