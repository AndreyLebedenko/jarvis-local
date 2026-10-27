# Personal proxy: the Journal answer of a failed stream appears only after all speech

Detected at commit d6bdc64 (branch feat/v2.1.0-12a-public-names), live run 2026-10-27,
session `20261027-100105-926fcb`.

**Status:** Resolved 2026-10-27 by `tasks/done/task-v2.1.1-2-incomplete-answer-journal.md`
(live confirmation pending the next real stream failure).

## Symptoms

The whole spoken answer plays first; the answer text appears in the Journal only afterwards,
marked "Incomplete: the answer was cut short" with the notice "Answer incomplete (timed out)".
Journal events of that session: `proxy_sent` 10:01:05.749, then `proxy_answer`
(`incomplete=true`, 373 characters) and `proxy_notice` (`answer_incomplete`, `timeout`) both at
10:02:35.324 - 89.6 s after the send, although the external deadline is 60 s.

## Suspected cause (code reading, not yet reproduced)

`answer/answer_presenter.py`: on a stream error `_show_arriving` queues the exception and
posts no `AnswerCompleteBlock`. `present()` meets the exception only after it has spoken every
earlier sentence. Only then the pipeline posts `ANSWER_INCOMPLETE`, and only that notice makes
`reporting/journal_writer.py` flush the buffered answer. The commit 3debd11 fix covers the
success path only (`AnswerCompleteBlock` posted while the first sentence is still spoken).
The extra ~30 s in the session above is consistent with speech of the queued sentences
finishing before the notice; the exact timing was not measured.

## Temporary decision

Not fixed in task 12a (unrelated scope). Reported only.

## Future considerations

- Flush the buffered answer to the Journal as soon as the stream fails or ends, not after
  speech; speech of already shown sentences may continue.
- The same asymmetry applies to a user interrupt (`INTERRUPTED` notice).
- The existing test uses an instantly delivered fake stream; add a failing-stream case with a
  held speaker asserting the Journal event precedes the end of speech.
- Separate from this: the Status Console drops proxy blocks while Hidden
  (`ui/transport.py`), so the text can then be seen only from the Journal.
