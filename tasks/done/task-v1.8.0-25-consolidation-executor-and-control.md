# Task v1.8.0-25: Consolidation executor and control

**Status:** Completed 2026-08-08. Design decided with the owner before
implementation: crash/restart recovery is idempotent re-derivation, not a
durable step-log - execution always re-plans fresh through the task-24
`ConsolidationPlanner` (which already reports an already-removed file as
`ALREADY_ABSENT`), so a partial prior run's remaining work is simply what a
fresh plan still proposes; the new archive-metadata store keeps only the
latest run's result per session (for audit/UI), not a state machine. The
API/UI always separate preview (dry-run plan) from execute (the only
destructive step); the UI requires an explicit confirm before calling
execute. Hardened through four Codex stop-time review rounds after the
initial implementation: a per-session lock preventing concurrent executes
from racing `os.unlink()` into a false partial failure, then fixing that
lock's own wait window so the active-session guard reads live state (a
`Callable` provider invoked only after the lock is held, not a value
captured before it), proven by an `ast`-based structural test (not timing,
not substring position) that the provider call is lexically inside the
lock's `with` block. Implemented and verified by `python -m pytest` (1937
passed, 1 skipped), ruff, and `node --check` on app.js/strings.js; see the
executor contract in `PROJECT.md`. Live WebView/browser verification of the
Journal panel is the usual human-run handoff (Testing protocol) - the full
app requires audio hardware and a running Ollama endpoint this environment
does not have; structural UI tests (`tests/test_journal_view_ui.py`,
`tests/test_ui_i18n.py`) are the automated substitute this project already
uses for the same reason on every other Journal panel.
**Story:** `tasks/done/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-24.

## Summary

Execute explicit consolidation plans with restart recovery, API control, and
projection consistency.

## Current boundary

In scope: plan execution, recovery markers, local API, Journal UI control,
projection refresh, usage reporting, and tests.

Out of scope: background scheduling, changing planning policy, semantic
backend selection, and automatic deletion without user command.

## Requirements

- Execute only a previously calculated explicit plan.
- Protect active sessions.
- Use recoverable steps for file and database changes.
- Refresh derived projections after execution.
- Surface partial failure and recovery state honestly.
- Provide authenticated local controls and Hidden-mode suppression.
- Preserve raw textual history and provenance.

## Acceptance criteria

- [x] Execution is explicit and auditable.
- [x] Crash/restart recovery is tested.
- [x] Projection data remains consistent after execution.
- [x] Active-session guard cannot be bypassed.
- [x] UI/API report progress and failure states.

## Stop conditions

- Stop if file/database mutation cannot be made recoverable.
- Stop if execution can invalidate retrieval provenance.
- Stop if hidden/background behavior could surprise the user.

## Verification

- Executor, recovery, API, UI, and projection tests.
- `python -m pytest`
- Ruff checks.
