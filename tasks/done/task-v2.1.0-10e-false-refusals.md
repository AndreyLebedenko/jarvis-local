# Task v2.1.0-10e: False refusals of the local sanitize model

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 10e. Follows
`tasks/done/task-v2.1.0-10d-force-command.md` and builds on
`tasks/done/task-v2.1.0-5-sanitize.md` (the stage, its strict parser, "nothing is sent or
retried"). Origin: two live false refusals of harmless requests on 2026-10-23 with no topics
file present: `bad_placeholder` on "tell briefly what a relay is", and a refusal with the
reason `DATE` on "what happened with the internet on Wednesday, 21 October this year?".

## Summary

The local sanitize model sometimes refuses or breaks harmless requests. Both are
fail-closed (nothing leaves the machine), but the request is lost. Three fixes and one
measurement:

1. With an empty topics list the sanitize prompt must not carry the topics rule and the
   empty "Sensitive topics:" section: there is nothing to refuse by topic.
2. One retry of the local sanitize call when the model returned a refusal without any topics
   (other than "no speech") or a malformed answer.
3. The notices for a failed or refused request tell a typed request how to send it as is
   (`/force`).
4. A prepared live measurement of the false refusal rate on harmless requests, run by the
   owner.

## Boundary

The sanitize prompt builder, the sanitize stage (one retry), the failure classes, the
notice texts and their hint, tests, a handoff and the measurement script. No change to the
gate, the external client, restoration, the `/force` flow, the topics file format or any
setting. No new setting (the retry is not configurable). No live call by the agent.

## Owner decisions (2026-10-24)

1. **One retry, only of the local sanitize call.** It goes to the local Ollama, so nothing
   leaves the machine and no leak is added; the retried output is parsed and validated, and
   then goes through the same gate as any other. A real refusal by a topic from the owner's
   file, and the "no speech" refusal, are never retried.
2. **A /force hint** in the "request could not be prepared" and "refused" notices for typed
   requests only; spoken requests keep the plain text.

## Design

**Prompt.** `sanitize_system_prompt(topics)` omits rule 6 (refusal by topic) and the
"Sensitive topics:" section when `topics` has no visible text; rule 7 (no speech) stays; the
numbering is consistent. With topics present the prompt is unchanged byte for byte (pin it
with a test so the measured baselines of task 5 stay valid).

**Retry.** In `sanitize()`: run the call and parse. Retry once, with the same request, when
the first outcome is (a) a refusal whose reason is not "no speech" and the topics list is
empty, or (b) a failure of a malformed-answer class (`EMPTY`, `BAD_PLACEHOLDER`,
`EMPTY_SANITIZED_TEXT`, `EMPTY_MAPPING_VALUE`, `NO_JSON`, `EXTRA_PROSE`, `MISSING_FIELD`,
`WRONG_TYPE`, `BAD_VERDICT`). Not retried: `BACKEND_FAILED` (Ollama unreachable), a refusal
with topics present, "no speech". The second outcome is final. A second refusal without
topics becomes a typed failure (a new class, for example `UNEXPECTED_REFUSAL`), so the notice
says the local model could not prepare the request, not that it was refused. The retry count
is a module constant with a test; the docstring "nothing is retried" is updated.

**Notices.** The sanitize-failed and refused notices gain the `/force` hint for typed
requests (the pipeline knows the source); texts in en and ru, fixed, content-free. A refusal
by a real topic keeps its text.

**Documents.** `PROJECT.md` (the sanitize bullet) and the task-5 invariant in the story state
the one retry and its limits.

## Required behavior

1. Everything in Design, written test first.
2. Tests: the prompt without topics lacks rule 6 and the section and has the same other
   rules; the prompt with topics is byte-identical to today's; the retry on each retryable
   class and on a topic-less refusal calls the backend exactly twice; no retry on
   `BACKEND_FAILED`, a refusal with topics, "no speech", a valid send; the second result is
   final (a valid send after a bad first answer is used; a second failure is reported with
   its own class; a second topic-less refusal becomes the new failure class); the retried
   request is identical to the first; no text in `caplog`, `repr` or exceptions; the notices
   with and without the hint (typed versus spoken), both languages; the 9a-10d invariants
   (full suite). Mutation checks by the developer on: retrying a topic refusal, retrying
   `BACKEND_FAILED`, a third call, dropping the topics from the prompt when they exist.
3. A measurement script and handoff (`manual/sanitize-false-refusals-handoff.md`,
   self-sufficient, passing `tools/check_handoff_self_sufficiency.py`) for the owner: about
   40 harmless requests (dates, numbers, places, news, how-to, general knowledge, short and
   long, Russian and English) run through the real sanitize stage on the production
   configuration, repeated twice, with the retry on and off, reporting the refusal and failure
   counts per class (no request text in the report) and two or three example IDs to
   inspect. The agent does not run it.

## Acceptance criteria

- [x] With an empty topics list the prompt carries no topics rule or section; with topics it
      is unchanged.
- [x] One retry on a topic-less refusal and on a malformed answer; no retry on a real topic
      refusal, "no speech" or an unreachable backend.
- [x] Notices for typed requests carry the `/force` hint; spoken ones do not.
- [x] Nothing leaves the machine through the retry; logs hold no request text.
- [x] The measurement handoff is prepared.
- [x] `python -m pytest`, `ruff check` and `ruff format --check` are green.


## Outcome (2026-10-24)

Accepted by the owner. Developer subagent; one independent review round. Fixed after review,
test first: the topics check is one shared helper (`topics_present()`) used by the prompt
builder and the stage, an empty answer of the model is retried, `CancelledError` from the
backend is neither turned into `BACKEND_FAILED` nor retried, "No speech" in any case or
spacing is never retried, handoff notes. Suite: 5881 passed, 1 skipped; ruff clean.

Built: the sanitize prompt without the topics rule and section when the topics list has no
visible text (byte-identical with topics); one retry (`SANITIZE_RETRIES = 1`) of the local
sanitize call on a topic-less refusal and on malformed answers (`BAD_PLACEHOLDER`,
`EMPTY_SANITIZED_TEXT`, `EMPTY_MAPPING_VALUE`, `NO_JSON`, `EXTRA_PROSE`, `MISSING_FIELD`,
`WRONG_TYPE`, `BAD_VERDICT`, `EMPTY`), never on `BACKEND_FAILED`, a refusal with topics,
"no speech" or `TRUNCATED`; a second topic-less refusal is the failure `UNEXPECTED_REFUSAL`;
the `/force` hint in the "could not be prepared" and "refused" notices for typed requests
(shown text only, not spoken, not in the Journal); the measurement script and handoff
(`manual/sanitize-false-refusals-handoff.md`).

Live measurement (owner, no topics file, 40 harmless requests, twice, retry on and off):
6 of 80 trials failed with `bad_placeholder` in both modes, and the retry rescued 0 of 6 in
one run and 1 of 6 in the other. The failures are the same three requests every time, all
with a date or a day of the week: "what happened with the internet on Wednesday, 21 October
this year?" (English and Russian) and a polite message moving a meeting from Tuesday to
Thursday afternoon. The other 37 always pass. So the failure is stable, not random, and the
retry does not cure it; it is kept (it costs a local call only on a failure and does no
harm).

Decisions beyond the card, accepted: the /force hint is also shown on a refusal by a real
topic; the topics file has no comment syntax, so a file of `#` lines counts as topics and
disables the retry.

Follow-up (separate task): fix how the sanitize prompt treats dates and days of the week
(the model builds a placeholder in a wrong format), then re-run the same 40 requests.
Open observations: a false refusal with topics present is not retried; the "no speech"
exemption from the retry protects nothing.
