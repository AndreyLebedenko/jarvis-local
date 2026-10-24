# Task v2.1.0-11: Refactoring and optimization sweep

Status: In review (findings 2, 3 and 4 applied 2026-10-24; waiting for the owner).

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 11.

## Boundary

Behavior-preserving consolidation of this story's code and tests. Gate: the whole existing
`python -m pytest` (including the Node behavior tests), `ruff check` and `ruff format --check`
stay green with no assertion edited; an assertion that has to change is a stop (section 0).
Owner decisions (2026-10-24): first a report only; no mutation checks.

## Survey method

`ruff --isolated` with C901, PLR09xx, SIM, RET, ERA, B on the story files; an AST scan of
definitions in `personal_proxy/`, `session_metadata.py`, `proxy_exchange.py` for names with no
other reference; a grep for repeated test fakes. Not done: a line-by-line read.

## Findings

Complexity is low: no C901 or PLR0912 hit in story code. Every hit is listed below.

1. **Test-only production helpers.** `restoration_validation.failed_rules` (the second
   alignment pass duplicates the logic of the validating function) and
   `confirmation_texts.shown_question` have no caller in `src/`; only tests call them.
   Options: delete with their tests, or wire them in if the UI should use them. Needs an
   owner choice (the tests would be removed, which is an assertion change).
2. **Repeated `FakeBackend` in four proxy test files** (restoration_stage,
   restoration_stream, sanitize, transcript_check): the same ~10-line class, three
   with an identical reply queue. Move one definition to a shared `tests/` module next to
   `_service_fakes.py`. Safe, no assertion change.
3. **Proxy wiring in `app.py`** (about 140 lines added at 3257+, nine story-related
   PLR0913/PLR0915 hits: `run` has 60 statements, `run_with_status_console` 55). Move the
   proxy-only helpers (`_require_console_for_personal_proxy`, `_warm_up_for_run_mode`,
   `_proxy_microphone_off`, `_proxy_host`) into `personal_proxy/` next to `proxy_assembly.py`.
   Medium risk: touches the startup order; the `main_split` tests cover it.
4. **Two RET504** (`app.py:2339`, `proxy_assembly.py:142`): trivial.
5. **Two PLR0911** (`sanitize_parsing.py:78`, `transcript_check.py:44`, 7 returns): each is a
   guard-clause chain; splitting adds names without clarity. Recommend: leave.
6. **Long argument lists**: `ProxyService.__init__` (12), `transport.py` constructors
   (14 and 30, the 30 pre-date the story). Recommend: leave; grouping into a settings object
   is a design change, not a sweep.
7. **Large test files** (`test_personal_proxy_service_pipeline.py` 1032 lines,
   `main_split/test_main_personal_proxy.py` 990). Splitting is possible but moves tests
   without removing anything; recommend: leave.
8. **Optimization:** nothing measured. No profile or hot path in the story code was
   identified; I do not recommend speculative changes.

## Acceptance criteria

- [ ] The owner picks which findings to apply.
- [ ] Chosen items applied with no assertion edited (except as agreed for finding 1).
- [ ] `python -m pytest`, `ruff check` and `ruff format --check` are green.

## Applied (owner choice: findings 2, 3, 4)

- 2: `tests/_backend_fakes.py` holds the one `FakeBackend` (replies in call order, the last
  repeats, an exception is raised). Six test files lost their own copies (including
  `ScriptedBackend` and `_Backend`, which were the same thing).
- 3: the proxy glue left `app.py` for `src/jarvis/app_proxy.py` (names lose the leading
  underscore; messages, the cue and the event source became named constants). The logger
  moved to `src/jarvis/app_logger.py` so both modules log under `jarvis.app`. `app.py` keeps
  `_warm_up_for_run_mode`, because `warm_up` lives there. Test edits are import lines and
  call-site renames only, no assertion changed.
- 4: `app.py` `create_live_status_console` fixed. The `proxy_assembly.py:142` hit is a false
  positive: `runtime` is read in the `finally` block, so it stays.
- Comments in story code are all "why not the obvious" notes (project rule 7.2); kept.
- Not applied, needs an owner decision: `personal_proxy/` has 95 flat modules; see the
  grouping proposal in the review message.
