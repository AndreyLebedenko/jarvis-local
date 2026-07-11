# Task: Evaluate advisory quality tools

**Story:** `tasks/story-quality-tooling-and-package-layout.md`
**Status:** Not started.

## Summary

Evaluate Pyright and Semdup against the final package layout and record whether
each has enough signal and stability to become a future project check.

## Acceptance Criteria

- [ ] Pyright findings are classified by defect signal and remediation cost.
- [ ] Semdup findings are classified as actionable duplication, intentional
      similarity, or false positive.
- [ ] Cold/incremental runtime and operational dependencies are recorded.
- [ ] A direct recommendation is recorded for each tool: gate, advisory, or
      reject.

