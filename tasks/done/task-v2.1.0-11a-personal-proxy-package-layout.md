# Task v2.1.0-11a: Subpackages for personal_proxy/

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 11 (split off from
`tasks/task-v2.1.0-11-refactoring-sweep.md`). Origin: owner request, 2026-10-24 ("big file =
bad file, same for folders; keep a tree structure").

## Problem

`src/jarvis/personal_proxy/` holds 90 modules in one folder, next to the existing
`detectors/` package. Module name prefixes (`confirmation_*`, `external_*`, `sanitize_*`,
`restoration_*`, `check_*`, `stt_*`) already show the groups; the folder does not.

## Proposed layout

Each module keeps its file name; only the folder changes. A group is a package with an
`__init__.py`; no re-exports, callers import the full path.

| Package | Modules |
|---|---|
| `common/` (8) | payload, findings, locality, spans, text, normalize, visible_text, speech_tags |
| `gate/` (5 + `detectors/`) | gate, gate_context, original_values, topic_lines, topics_file; the existing `detectors/` moves inside |
| `stt/` (9) | stt_engine, stt_result, stt_whisper, guarded_transcription, speech_guard, clip_check, clip_audio, silero_probabilities, wav_clip |
| `check/` (9) | check_backend, check_prompts, check_requests, check_result, judge_parsing, rewrite_guard, transcript_check, weak_word_marks, ollama_check_backend |
| `sanitize/` (7) | sanitize, sanitize_parsing, sanitize_prompts, sanitize_requests, sanitize_result, placeholders, verbatim_result |
| `restoration/` (7) | restoration, restoration_queue, restoration_requests, restoration_result, restoration_sentences, restoration_substitution, restoration_validation |
| `confirmation/` (9) | confirmation_blocks, confirmation_exchange, confirmation_outcome, confirmation_policy, confirmation_ports, confirmation_texts, confirmation_vocabulary, microphone_gate, resume_completely |
| `external/` (10) | external_client, external_endpoint, external_error, external_key, external_limits, external_lines, external_logging, external_request, external_scope, external_sse |
| `request/` (7) | proxy_inbox, request_commands, request_intake, request_pipeline, pipeline_stages, typed_transcript, stage_binding |
| `answer/` (5) | answer_presenter, answer_speaker, answer_transcriber, answer_voice, answer_reporter (was service_reporter) |
| `reporting/` (9) | service_blocks, service_ports, service_texts, block_payload, chat_sink, status_sink, journal_writer, notice_class, sent_view |
| `service/` (3) | proxy_service, proxy_runtime, proxy_submissions |
| `startup/` (5) | launch, proxy_assembly, startup, startup_checks, startup_failure |

The package root keeps only `__init__.py`.

## Dependency check

I mapped every `from jarvis.personal_proxy.X import` onto this layout. The package graph has
no cycle: `common`, `stt`, `external`, `gate` are leaves; `check` -> `stt`;
`confirmation`, `sanitize` -> `check`; `restoration` -> `sanitize`, `external`;
`reporting` -> `check`, `confirmation`, `restoration`, `sanitize`; `answer` -> `reporting`,
`confirmation`, `restoration`, `stt`; `request` -> `answer`, `reporting` and the stages;
`service` -> `request`, `answer`, `reporting`, `confirmation`; `startup` -> everything.

Two placements are driven by cycles in a first draft:
`proxy_inbox` sits in `request/` (it is used by the pipeline and by `service/`, and a
`service/` home made `request` and `service` import each other); `service_reporter` sits in
`answer/` (it imports `answer_voice` while `answer_*` import `service_blocks` and
`service_ports`, so a `reporting/` home made `answer` and `reporting` import each other).
Open to the owner: `service_reporter` is the odd name in `answer/`; renaming it to
`answer_reporter` would fix that at the cost of one more rename.

## Impact (from a grep, not yet a trial move)

- 152 files under `src/` and `tests/` import from `jarvis.personal_proxy.*`; all become a
  mechanical import-path rewrite (a script, then `ruff --fix` for ordering).
- Tests that monkeypatch by dotted string, and `manual/manual_check_*.py` scripts, import the
  old paths and must be rewritten the same way.
- `PROJECT.md` mentions `personal_proxy/...` paths in 12 places.
- Test files stay flat in `tests/` (they are named by feature, not by module); splitting
  them is out of this card.
- The graphify graph is rebuilt afterwards (`tools/graphify.ps1 update`).

## Plan after approval

1. Commit (already clean tree), branch `refactor/v2.1.0-11a-personal-proxy-packages`.
2. A throwaway script moves files with `git mv` and rewrites imports; run `python -m pytest`,
   `ruff check`, `ruff format --check` on the whole repository.
3. Fix the `PROJECT.md` paths in the same commit.
4. No logic change; if any assertion has to change, stop (section 0).

## Acceptance criteria

- [x] The owner approves the layout (or amends it).
- [x] No module is left in the package root except `__init__.py`.
- [x] No import cycle between the new packages.
- [x] `python -m pytest`, `ruff check` and `ruff format --check` are green; no assertion edited.
- [x] `PROJECT.md` and `manual/` scripts point to the new paths.

## Result (2026-10-25)

Layout approved by the owner with `service_reporter` renamed to `answer_reporter`. Applied
by a throwaway script (`git mv`, import rewrite in `src`, `tests`, `manual`, `tools`) and
checked: every package imports, the package graph is acyclic, `python -m pytest` (5998
passed, 1 skipped), `manual/tests` (773 passed), `ruff check`, `ruff format --check` and all
`manual/*handoff*.md` self-sufficiency checks are green. One test edit beyond imports:
`test_the_seam_has_no_production_caller` excluded files by `path.parent.name`; it now excludes
any path inside `personal_proxy/`, same intent. `PROJECT.md` has the layout paragraph and the
updated path citations.
