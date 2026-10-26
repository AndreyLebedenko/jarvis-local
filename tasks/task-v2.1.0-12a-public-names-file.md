# Task v2.1.0-12a: Public names file

Status: Proposed 2026-10-26; waiting for the owner's go-ahead to implement.

Story: `tasks/story-v2.1.0-personal-proxy.md`, after task 12. Origin: owner's live run,
2026-10-26.

## Problem

The sanitize prompt replaces the names of all people with `<PERSON_N>`. A question about a
public person ("Правда ли, что Эйнштейн отстаивал идею эфира ...") reaches the external model
as "Правда ли, что <PERSON_1> отстаивал ...". The model answers that it cannot tell who is
meant, and the restored answer even reads "шаблон Эйнштейна". The only way out today is
`/force`, which also skips the model that finds private names.

## Decision (owner, 2026-10-26)

A separate file of allowed names, kept by the owner, like the topics file. Chosen over a
prompt rule that lets the model judge who is "well known": the owner decides, so a private
person with a famous namesake can never be sent by mistake, and no classification risk is
added.

## Design

1. Config: `[personal_proxy].public_names_file`, default `personal_proxy_public_names.txt`
   next to `Jarvis.cmd`, listed in `.gitignore`, never leaves the machine. One name per line;
   the same file rules as `topics_file` (`gate/topics_file.py`: UTF-8, size limit, comment and
   blank lines, a missing default file is empty, a missing or unusable explicit file stops the
   start with a typed failure kind).
2. Prompt: when the file has at least one visible line, the sanitize system prompt gets one
   more rule and a section "Public names" with the lines: do not replace these names, keep
   them as said, in any case form. With no names the prompt is byte-identical to the one in
   `tests/test_personal_proxy_sanitize_prompts.py` (the frozen hash), so every earlier
   measurement stays valid for the default.
3. Nothing to restore: a kept name has no placeholder and no `mapping` entry. The outbound
   gate is unchanged.
4. A model that still replaces an allowed name is not worse than today; this is not a
   deterministic guarantee and the docs say so.

## Boundary

Config key and its validation, the file loader (reuse the topics file reader, no copy), the
prompt rule, the start check and its UI text (EN, RU), tests, `config.example.toml`,
`.gitignore`, README.md and README.ru.md, `PROJECT.md`, and one step in the release handoff
(EN, RU) with the Einstein request. No change to the gate, the restoration or the check
pass. A deterministic substitution after the model is out of scope (the base form in
`mapping` does not give the surface form used in the request).

## Open points

- Should the same file also be passed to the check pass (the transcript judge)? Today it
  does not see names specially; decide by reading `check/check_prompts.py` first.
- Size limit of the list (the prompt grows with it); reuse the topics limit unless the
  reading shows a reason not to.

## Acceptance criteria

- [ ] The key, the file, the start failure kind and the prompt rule exist; no names gives the
      frozen prompt.
- [ ] Tests: loader cases, prompt with and without names, start failure, config validation.
- [ ] The Einstein request keeps the name in the sanitized text (human-run, live model:
      `manual/manual_check_sanitize_raw_reply.py` with the names file present, 5 repeats).
- [ ] The false-refusal measurement is repeated with a non-empty names file and reported.
- [ ] README (EN, RU), `PROJECT.md` and the handoff name the file and the limit of the rule.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check`, and
      `tools/check_handoff_self_sufficiency.py` are green.
