# Story: Code entropy reduction practice

**Status:** Completed.
**Release:** Maintenance.

## User-facing goal

Catch duplicated logic that neither Ruff nor Pyright nor the test suite can
see, before two independent implementations of the same contract quietly
drift apart. Semdup (semantic-duplication tooling) was rejected in
`tasks/done/story-quality-task-8-advisory-tool-evaluation.md`: no
installable tool of that name exists, and its swarm-duplication use case
does not match this project's sequential, human-supervised workflow. This
story documents the manual practice that replaces it, and applies it to
the two instances found while closing that evaluation.

## What counts as entropy here

- Two independent implementations of the same contract or invariant (a
  validation rule, a load-once-with-error-caching pattern) that must be
  kept in sync by hand, with no single source of truth enforcing it. Risk
  is proportional to how likely the contract is to change (new field
  type, new engine) without both sides being touched together.
- Sibling classes or functions solving the same problem with diverging
  rigor: one fully typed, one not; one handling an edge case the other
  quietly doesn't.
- **Not** entropy: incidental structural similarity with no shared
  invariant behind it. Per this repo's core engineering principles, three
  similar-looking but independently-varying lines do not need a forced
  abstraction - only extract where a real contract is duplicated.

## How to look for it (there is no tool)

- After closing a quality-tooling or architecture initiative, read sibling
  implementations side by side: parallel adapter/engine classes, parallel
  construction sites for the same data across layers (e.g. a config
  loader and a transport/API layer both building the same settings
  object), and functions Ruff's complexity check flags - not for the
  number, but because a nontrivial function is exactly where a second,
  independently-written copy is expensive to keep in sync.
- Prefer this over waiting for a bug report: divergence found by reading
  code is cheap to fix immediately; divergence discovered because a fix
  landed in only one sibling is a live bug.

## Boundaries

- Extract shared behavior only where an actual invariant/contract is
  duplicated; do not force an abstraction over incidental similarity.
- This is refactoring: preserve runtime behavior and existing error
  messages/types exactly. No behavior change.
- Each task card below is an independently verifiable slice.

## Acceptance Criteria

- [x] The TTS engine lazy-load-and-cache-error pattern
      (`SileroEngine`/`PiperEngine`) is implemented once, not twice.
- [x] TTS field-type validation (`core/config.py` vs `ui/transport.py`) is
      enforced by one implementation, not two.
- [x] `python -m pytest`, `python -m ruff check .`,
      `python -m ruff format --check .`, and `python -m pyright` all stay
      at least as green as the pre-story baseline. (663 passed vs. 657
      pre-story; Pyright 271 findings vs. 274 pre-story.)
- [x] `PROJECT.md` records this as the project's code-entropy review
      practice.

## Task Card Sequence

1. `tasks/done/story-code-entropy-task-1-tts-engine-lazy-load-helper.md`
   Extract `SileroEngine`/`PiperEngine`'s duplicated load-once/cache-error
   pattern into one shared helper.
2. `tasks/done/story-code-entropy-task-2-tts-field-validation-consolidation.md`
   Consolidate `core/config.py`'s and `ui/transport.py`'s independent TTS
   field-type validation into one implementation.

## Review note

`tasks/done/code-review-code-entropy-reduction.md` requested changes on
the first pass (preserve `ConfigError` wording exactly; do not erase the
Piper voice type to `object`; add concurrency coverage for the shared
lazy-load helper). All three were fixed and re-verified before this story
closed; see each task card's "Review fix(es)" section for detail.

## Stop Conditions

- Stop if extracting the shared helper would require changing either
  engine's public behavior or load timing.
- Stop if consolidating validation would require changing an error
  message or type an existing test asserts on.
- Stop if either task reveals a third, previously unnoticed duplicate of
  the same contract - re-scope before continuing.
