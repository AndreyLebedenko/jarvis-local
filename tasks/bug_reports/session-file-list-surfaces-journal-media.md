# list_session_files surfaces journal event media

**Detected at commit:** 9f1a5b2 (task-v1.8.1-3 branch, before merge).
**Status:** Won't fix in v1.8.1 by decision. Documented intentional consequence.

## Symptoms

During the task-v1.8.1-3 manual handoff a voice turn asked Jarvis to save a
note. Instead of calling `write_session_file`, the model called
`list_session_files`, saw the current session's own voice recordings
(`utterance-<ts>-<counter>.wav`) listed as session files, and answered about
being unable to transcribe them. Writing the same note by text immediately
after worked correctly (`plan-<uuid>.md`).

The session-file tools themselves behaved to spec:
- `write_session_file` produced a generated storage name (verified by text).
- `list_session_files` returned the files that are physically in the session
  directory - which includes journal event media, not only loose files.

## Suspected current cause

Loose session files and journal event media share one directory
(`root/<session_id>/`). `SessionFileRepository.list()` returns every top-level
file except `events.jsonl`, so the journal's own `.wav`/`.png` event media are
reported alongside loose files. There is no stored marker distinguishing the
two: by story decision 1 no sidecar/manifest records a file's origin, and loose
files use `stem-<uuid>.ext` names that a hand-written media name could also
resemble. The model reading event-media names as "session files" is what
misled it.

## Temporary decision

Keep current behavior. story-v1.8.1's Boundary section already locks this as an
intentional consequence of sharing the session directory, and the human
confirmed (2026-08-23) not to change the architecture now. `list`/`read`/`view`/
`stat` continue to see whatever is in the readable session directories.

Rejected alternative (for now): filtering `list` to loose files only by
excluding paths present in the session's `events.jsonl` media lists. It was
declined because it re-opens the locked story decision and, done properly,
either couples the deliberately pure `SessionFileRepository` to journal-event
parsing or widens `SessionFileScope` to carry known-media names - an
architectural change out of scope for the current work.

## Future considerations and boundaries

- If a later story wants `list` to show only model/UI-authored loose files, do
  it by passing the set of known event-media relative names into
  `SessionFileScope` (resolved by the scope builder, which already reads the
  journal), so the repository stays free of a `JournalStore` dependency. Do not
  add a per-file origin sidecar - decision 1 forbids it.
- Any such change is a behavior change to a shipped capability and must update
  story-v1.8.1's Boundary wording in the same commit.
- Independent of `list`, the model-facing prompt/tool descriptions could steer
  the model to prefer `write_session_file` for "save a note" intents; that is a
  prompt-tuning lever, not a repository change.
