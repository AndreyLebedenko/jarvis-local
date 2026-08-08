"""Consolidation executor (task v1.8.0-25).

Executes a far-consolidation plan: removes the audio files
`ConsolidationPlanner` (task v1.8.0-24) marks REMOVE, records the outcome to
the archive metadata store, and reports honestly on partial failure. Never
rewrites the raw journal or any overlay text - the only mutation is deleting
audio bytes that already have a transcript overlay.

Crash/restart recovery is idempotent re-derivation (owner decision,
2026-08-08; see the consolidation planner/executor contract in `PROJECT.md`):
`execute_far_consolidation` always builds a *fresh* plan through the planner
right before acting, rather than trusting a plan the caller fetched earlier.
An already-removed file resolves to `MediaActionReason.ALREADY_ABSENT` on
that fresh plan, so re-invoking execute after a crash, restart, or partial
failure simply continues with whatever the current state still proposes - no
separate "resume" operation, no durable in-progress marker that could drift
out of sync with reality. This is also what makes the active-session guard
unconditional: every execution re-checks `active_session_id` against a fresh
plan, so no stale or tampered plan can bypass it.

A per-file failure (permission error, disk error, ...) does not abort the
run: the remaining files are still attempted, and the run is reported
PARTIAL_FAILURE rather than raising. Aborting on the first failure would
leave the archive record silently understating what was actually attempted;
continuing and reporting every outcome is what "surface partial failure and
recovery state honestly" (task 25 requirements) means in practice.

Concurrent execute calls for the *same* session are serialized by a per-
session lock (Codex stop-time review, 2026-08-08). The transport dispatches
`execute_far_consolidation` through `asyncio.to_thread`, so two overlapping
HTTP requests for one session run this method on two real OS threads. Without
serialization both threads plan from the same pre-deletion state, both mark
the same file REMOVE, and the loser of the `os.unlink()` race gets
`FileNotFoundError` - a real, freshly-deleted-by-the-winner file reported as a
false `PARTIAL_FAILURE` even though the plan's goal (the file is gone) was
achieved. The lock makes the second call's fresh re-plan run strictly after
the first call's deletions commit, so it correctly sees `ALREADY_ABSENT` and
reports KEEP instead of racing a second delete. Different sessions still run
fully in parallel; only same-session calls serialize.

That same lock can make a call wait an unbounded time behind another
same-session execution (Codex stop-time review, 2026-08-08). If the caller
had captured `active_session_id` *before* the wait, a session could become
active while this call sat blocked on the lock, and the call would still act
on the stale "not active" snapshot once it finally acquired the lock -
bypassing the active-session guard through the wait itself, not through a
stale plan. `execute_far_consolidation` therefore takes an
`active_session_id_provider` callable instead of a value, and calls it only
*after* acquiring the lock, immediately before planning - the same freshness
guarantee the fresh-plan design already gives every other part of this
method, extended to cover the lock's own wait.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from jarvis.journal.archive import (
    ArchiveMediaOutcome,
    ArchiveOverlayRepository,
    ArchiveRun,
    ArchiveRunRead,
    ConsolidationRunStatus,
    MediaOutcome,
    utc_now_iso,
)
from jarvis.journal.consolidation import (
    ConsolidationPlanner,
    ConsolidationPlanStatus,
    MediaAction,
)


class ConsolidationExecutionSource(Protocol):
    """The media I/O the executor needs beyond the planner's read-only checks.

    `JournalStoreConsolidationSource` (task 24's planner adapter, in
    `consolidation.py`) already implements both methods, so the same instance
    passed to `ConsolidationPlanner` also satisfies this protocol.
    """

    def media_size(self, session_id: str, name: str) -> int: ...

    def delete_media(self, session_id: str, name: str) -> None: ...


class ConsolidationExecutionOutcome(Enum):
    EXECUTED = "executed"
    ACTIVE_SESSION = "active_session"
    UNKNOWN_SESSION = "unknown_session"


@dataclass(frozen=True)
class ConsolidationExecutionResult:
    session_id: str
    outcome: ConsolidationExecutionOutcome
    run: ArchiveRun | None = None

    @property
    def executed(self) -> bool:
        return self.outcome is ConsolidationExecutionOutcome.EXECUTED


class ConsolidationExecutor:
    """Executes a freshly re-derived plan. Never mutates the raw journal."""

    def __init__(
        self,
        planner: ConsolidationPlanner,
        source: ConsolidationExecutionSource,
        archive: ArchiveOverlayRepository,
    ) -> None:
        self._planner = planner
        self._source = source
        self._archive = archive
        self._session_locks_guard = threading.Lock()
        self._session_locks: dict[str, threading.Lock] = {}

    def read_last_run(self, session_id: str) -> ArchiveRunRead:
        """The last recorded run for this session, if any (read-only)."""
        return self._archive.read_run(session_id)

    def _lock_for(self, session_id: str) -> threading.Lock:
        with self._session_locks_guard:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[session_id] = lock
            return lock

    def execute_far_consolidation(
        self,
        session_id: str,
        *,
        active_session_id_provider: Callable[[], str | None],
    ) -> ConsolidationExecutionResult:
        # Evaluated only after the lock is held, not before: a call can wait
        # here an unbounded time behind another same-session execution, and
        # the active-session guard must see the state at the moment it is
        # about to act, not the state when it first asked to run.
        with self._lock_for(session_id):
            return self._execute_far_consolidation_locked(
                session_id, active_session_id=active_session_id_provider()
            )

    def _execute_far_consolidation_locked(
        self, session_id: str, *, active_session_id: str | None
    ) -> ConsolidationExecutionResult:
        plan = self._planner.plan_far_consolidation(
            session_id, active_session_id=active_session_id
        )
        if plan.status is ConsolidationPlanStatus.ACTIVE_SESSION:
            return ConsolidationExecutionResult(
                session_id, ConsolidationExecutionOutcome.ACTIVE_SESSION
            )
        if plan.status is ConsolidationPlanStatus.UNKNOWN_SESSION:
            return ConsolidationExecutionResult(
                session_id, ConsolidationExecutionOutcome.UNKNOWN_SESSION
            )

        started_at = utc_now_iso()
        outcomes: list[ArchiveMediaOutcome] = []
        bytes_reclaimed = 0
        for item in plan.media_items:
            if item.action is MediaAction.KEEP:
                outcomes.append(
                    ArchiveMediaOutcome(
                        item.reference,
                        item.media,
                        MediaOutcome.KEPT,
                        item.reason.value,
                    )
                )
                continue

            try:
                size = self._source.media_size(item.reference.session_id, item.media)
                self._source.delete_media(item.reference.session_id, item.media)
            except OSError as exc:
                outcomes.append(
                    ArchiveMediaOutcome(
                        item.reference, item.media, MediaOutcome.FAILED, str(exc)
                    )
                )
                continue

            bytes_reclaimed += size
            outcomes.append(
                ArchiveMediaOutcome(
                    item.reference,
                    item.media,
                    MediaOutcome.REMOVED,
                    item.reason.value,
                )
            )

        status = (
            ConsolidationRunStatus.PARTIAL_FAILURE
            if any(item.outcome is MediaOutcome.FAILED for item in outcomes)
            else ConsolidationRunStatus.COMPLETED
        )
        run = ArchiveRun(
            session_id=session_id,
            status=status,
            event_count=plan.event_count,
            annotation_count=plan.annotation_count,
            media_outcomes=tuple(outcomes),
            bytes_reclaimed=bytes_reclaimed,
            started_at=started_at,
            completed_at=utc_now_iso(),
        )
        self._archive.record_run(run)
        return ConsolidationExecutionResult(
            session_id, ConsolidationExecutionOutcome.EXECUTED, run
        )
