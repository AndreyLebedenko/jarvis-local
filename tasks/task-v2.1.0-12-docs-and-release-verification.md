# Task v2.1.0-12: Docs and release verification

Status: Prepared 2026-10-25; waiting for the owner review and the human-run handoff.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 12. Precedent:
`tasks/done/task-v2.0-8-docs-and-release-verification.md`.

## Owner decisions (2026-10-25)

1. Scope includes the version bump: `pyproject.toml` 2.0.1 -> 2.1.0 and the README headline.
   No git tag, no publication, no release notes beyond the README.
2. The roadmap section "v2.1 - Canvas-guided voice" becomes "v2.2 - Canvas-guided voice";
   v3.0 stays as is.
3. One consolidated release handoff, in English and in Russian
   (`manual/personal-proxy-release-handoff.md` and `.ru.md`), self-sufficient: it does not
   depend on the per-task handoffs of tasks 5-10f.
4. The recall report: a new script only if no existing tool covers it. The existing tools
   cover it (offline `manual_check_text_sanitize score` for the leak rate by group,
   `manual_check_doubt_trigger run` for the asked share and the covered errors), so the
   handoff names those commands and no script is added.
5. `README.md` and `README.ru.md` both get the setup note.

## Boundary

Docs, the version string and a human-run handoff. No production logic change; if one is
needed, report it instead (stop condition of the story).

## What to build

1. `PROJECT.md`: a section "Architecture v2.1.0 (personal proxy)" that summarizes the settled
   design and points to the detailed records, with the honest limits; "Current roadmap" marks
   v2.1.0 delivered and v2.2 as the canvas direction. The runtime locality contract already
   names the capability (task 1); check that it is current.
2. `tasks/roadmap-v1.9-v2.0.md`: the renumbering, and v2.1.0 recorded as delivered.
3. `README.md` and `README.ru.md`: the endpoint, the key environment variable, the topics
   file, the optional speech-to-text dependencies and the weights setup, the start command,
   dry run, `/force`, session rename, the privacy limits.
4. Version 2.1.0.
5. The release handoff (EN, RU) per the story text: dry run on the recorded corpora, a real
   send, a block case for each gate category, a refusal on a topics-file topic, restoration
   on Russian cases, a request that makes the system ask (yes, no, timeout), silence that
   sends nothing, the Journal and Status Console labels, and the recall report.

## Acceptance criteria

- [x] `PROJECT.md`, roadmap, both READMEs and the version are updated.
- [x] The handoff (EN, RU) is self-sufficient and passes
      `tools/check_handoff_self_sufficiency.py`.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` are green.
- [x] Docs state the honest limits.

## Done

- `PROJECT.md`: "Architecture v2.1.0 (personal proxy)" and the roadmap list (v2.1.0 delivered,
  v2.2 canvas, v3.0 self-model); the locality contract was already current.
- `tasks/roadmap-v1.9-v2.0.md`: renumbered to v2.2.
- `README.md`, `README.ru.md`: headline, status and the section "Personal proxy mode".
- `pyproject.toml`: version 2.1.0.
- `manual/personal-proxy-release-handoff.md` and `.ru.md`, both pass
  `tools/check_handoff_self_sufficiency.py`. No recall script was added: part 9 uses the
  existing `manual_check_text_sanitize score` (offline, verified to run and to print the
  recorded reference 0.052), `manual_check_doubt_trigger run` and
  `manual_check_sanitize_false_refusals run`.
- Gates: `python -m pytest` 5998 passed, 1 skipped; `ruff check`; `ruff format --check`.

## Found during the owner's run (2026-10-25)

- The live sanitize model answered a lone person with `<PERSON>` (no number) and the base
  form was not used, so "Напиши Марине Крыловой ..." failed with `bad_placeholder` twice.
  Fix: a numbering rule and one worked example in the sanitize prompt (the prompt was
  frozen by hash; the pin was moved on purpose). After it: 5 of 5 raw replies accepted;
  false refusals 0 of 80 trials in both retry arms, no topics file.
- The Journal wrote the answer only after its speech ended. `AnswerPresenter` now reads the
  answer in its own task, shows each sentence at once and closes the answer when the last
  sentence arrived.
- The failure log line of a refused start now holds the readable message of the kind, not
  its code.
- New tool: `manual/manual_check_sanitize_raw_reply.py` prints the raw model reply to the
  console for one request text.

## Open

- The rest of the release handoff has not been run by the human. Measured since the prompt
  change: false refusals without a topics file (0 of 80). Not measured: false refusals with
  a topics file, the leak rate on the new prompt.
- Not changed on purpose: no git tag and no publication.
