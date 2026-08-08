# Task v1.8.0-26: Retrieval quality regression

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-20 and v1.8.0-23.

## Summary

Rerun the fixed retrieval-quality benchmark after transcripts and annotations
join the retrieval corpus.

## Current boundary

In scope: extending benchmark slices for transcript and annotation text,
recording final metrics, and stopping release if retrieval quality regresses.

Out of scope: selecting a new backend, changing thresholds after seeing
results, altering automatic retrieval wiring, and adding runtime dependency.

## Deferred check from task 23

Before closing this card, revisit
`tasks/bug_reports/2026-08-08-edited-annotation-recall-miss-in-new-context.md`:
a manual playtest during task 23 slice 4 saw an edited annotation fail to be
recalled at all from a fresh context shortly after saving. Determine whether
this was the PUT-edit/reprojection race described there or a plain ranking
miss, using this card's benchmark harness or a log-backed repro; the report
lists the concrete follow-up for each case.

## Requirements

- Reuse the task 11 benchmark labels, thresholds, and metric definitions
  unless an explicit documented revision is approved before results.
- Add transcript and annotation cases only as new labeled slices.
- Run without live Ollama, network access, or hardware.
- Record final corpus version, retrieval mode, metrics, result, and release
  decision in `PROJECT.md`.
- Confirm exact/prefix fallback still works for literal cases.
- Stop before scale/release verification if the final retrieval surface fails.

## Acceptance criteria

- [ ] The benchmark remains deterministic and pure.
- [ ] Raw-text quality labels are preserved.
- [ ] Transcript and annotation slices are explicit.
- [ ] Final decision is reproducible from repository files.
- [ ] No new runtime dependency is introduced by this regression task.

## Stop conditions

- Stop if transcript or annotation integration changes benchmark meaning.
- Stop if passing requires weakening thresholds after seeing results.
- Stop if fixing failure requires reopening settled lifecycle or wiring.

## Verification

- Focused retrieval benchmark regression tests.
- `python -m pytest`
- Ruff checks.
