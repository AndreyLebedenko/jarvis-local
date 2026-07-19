# Fork seed skipped_events mixes skip reasons

Detected at commit: `1bcef32`.

## Symptoms

`ForkSeedDropReport.skipped_events` currently counts both journal events that
have no model-facing text and journal events intentionally excluded from fork
seeding, such as `source="context"` blank-context provenance markers.

The current UI only surfaces dropped-turn truncation, so this is not a
user-visible defect today. If seed details become more visible later, a single
`skipped_events` number would be ambiguous to readers.

## Suspected Current Cause

`build_fork_seed()` represents all non-seeded events as `None` from
`_seed_turn()`, then increments one `skipped_events` counter without carrying
the reason.

## Temporary Decision

Leave the v1.5.3 critical fix unchanged: it preserves the existing metadata
shape and only fixes the tail contract, oversize semantics, fork provenance
write race, and context-marker exclusion. This avoids mixing a metadata shape
revision into the critical review-fix commit.

## Future Considerations

If fork seed reporting becomes user-facing beyond the current truncation note,
split the report into reason-specific counters, for example textless events vs
excluded provenance markers. Keep backward compatibility for existing
`metadata.seed.skipped_events` readers or introduce a schema-versioned seed
metadata shape.

## Resolution

Resolved by `tasks/task-v1.5.3-9-review-polish.md`: `skipped_events` now counts
events without model-facing text, while `excluded_events` counts intentionally
excluded provenance markers such as `source="context"`.
