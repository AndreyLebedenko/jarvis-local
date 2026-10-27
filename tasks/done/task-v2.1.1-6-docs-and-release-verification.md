# Task v2.1.1-6: Docs and release verification

Status: Completed.

Story: `tasks/story-v2.1.1-proxy-speech-modes.md`, task 6 (Size: S-M). Precedent:
`tasks/done/task-v2.1.0-12-docs-and-release-verification.md`.

## Boundary

Docs, the version string and a human-run handoff. No production logic change.

## What was built

1. `README.md` and `README.ru.md`: the proxy section describes the response modes, their
   limits, the hotkey, the Status tab control and `spoken_pass_timeout_seconds`.
2. `PROJECT.md`: the outbound payload statement names the voice paragraph; the roadmap marks
   v2.1.1 delivered. Per-task amendments were made in tasks 3-5.
3. `pyproject.toml`: version 2.1.0 -> 2.1.1 (owner decision, 2026-10-27).
4. `manual/personal-proxy-speech-modes-handoff.md` and `.ru.md`: self-sufficient human-run
   steps for the three modes, the hotkey, the Status tab buttons, the fallback, the interrupt,
   latching and the Journal metadata, with a latency measurement of Text+voice.

## Acceptance criteria

- [x] README (EN, RU), `PROJECT.md` and the handoff name the modes and their limits.
- [x] The handoff passes `tools/check_handoff_self_sufficiency.py`.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` are green.

## Outcome (2026-10-27)

Gates: see the commit. Live runs by the owner on 2026-10-27: Voice and Text+voice worked as
intended. The handoff's latency figure for Text+voice (step 5.2) and the rest of its steps are
not yet reported; their numbers belong in the honest limits of `PROJECT.md` when reported.
No git tag and no publication, on purpose.
