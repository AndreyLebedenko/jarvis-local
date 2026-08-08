from __future__ import annotations

import ast
import inspect
import textwrap
import threading
import time
from pathlib import Path

from jarvis.journal.annotation import AnnotationOverlayRepository
from jarvis.journal.archive import (
    ArchiveOverlayRepository,
    ConsolidationRunStatus,
    MediaOutcome,
)
from jarvis.journal.consolidation import (
    ConsolidationPlanner,
    JournalStoreConsolidationSource,
)
from jarvis.journal.consolidation_executor import (
    ConsolidationExecutionOutcome,
    ConsolidationExecutionResult,
    ConsolidationExecutor,
)
from jarvis.journal.events import JournalEvent
from jarvis.journal.lifecycle import JournalStoreEventReferenceResolver
from jarvis.journal.store import JournalStore
from jarvis.journal.transcript import TranscriptOverlayRepository, TranscriptSource

_SESSION = "20260801-120000-ab12"
_TIMESTAMP = "2026-08-01T12:00:00+00:00"


def _no_active_session() -> str | None:
    return None


def _event(*media: str) -> JournalEvent:
    return JournalEvent(
        session_id=_SESSION,
        timestamp=_TIMESTAMP,
        source="voice",
        role="user",
        text="",
        media=tuple(media),
        transcript=None,
        metadata={},
    )


class _FlakyOnceSource:
    """Wraps a real source, raising OSError once for a chosen media name.

    Simulates a single transient failure (disk hiccup, permission race) on
    one file during an otherwise-normal execution, so the test can assert the
    run continues past it and reports PARTIAL_FAILURE, without touching real
    OS-level fault injection.
    """

    def __init__(self, inner: JournalStoreConsolidationSource, fails_on: str) -> None:
        self._inner = inner
        self._fails_on = fails_on
        self.delete_attempts: list[str] = []

    def read_session(self, session_id: str):
        return self._inner.read_session(session_id)

    def media_exists(self, session_id: str, name: str) -> bool:
        return self._inner.media_exists(session_id, name)

    def media_size(self, session_id: str, name: str) -> int:
        return self._inner.media_size(session_id, name)

    def delete_media(self, session_id: str, name: str) -> None:
        self.delete_attempts.append(name)
        if name == self._fails_on:
            raise OSError(f"simulated failure deleting {name}")
        self._inner.delete_media(session_id, name)


class _SlowDeleteSource:
    """Wraps a real source, holding `delete_media` open for a fixed delay and
    counting calls (and any overlap between them).

    A second `execute_far_consolidation` call for the same session, launched
    while the first is still inside its (slow) delete, must not itself reach
    `delete_media` at all: serialized by the per-session lock, its re-plan
    only runs after the first call's deletion has already committed, so it
    sees the file as `ALREADY_ABSENT` and never attempts a second delete.
    `delete_call_count`/`concurrent_delete_calls` observe that directly,
    which is more robust than inferring serialization from the *outer*
    `execute_far_consolidation` call's wall-clock span - a blocked-on-the-
    lock second call's own span necessarily overlaps the first call's span,
    so comparing those two spans would not actually prove anything.
    """

    def __init__(
        self, inner: JournalStoreConsolidationSource, delay_seconds: float
    ) -> None:
        self._inner = inner
        self._delay = delay_seconds
        self._guard = threading.Lock()
        self._in_delete = 0
        self.delete_call_count = 0
        self.concurrent_delete_calls = 0

    def read_session(self, session_id: str):
        return self._inner.read_session(session_id)

    def media_exists(self, session_id: str, name: str) -> bool:
        return self._inner.media_exists(session_id, name)

    def media_size(self, session_id: str, name: str) -> int:
        return self._inner.media_size(session_id, name)

    def delete_media(self, session_id: str, name: str) -> None:
        with self._guard:
            self.delete_call_count += 1
            self._in_delete += 1
            if self._in_delete > 1:
                self.concurrent_delete_calls += 1
        try:
            time.sleep(self._delay)
            self._inner.delete_media(session_id, name)
        finally:
            with self._guard:
                self._in_delete -= 1


def _setup(
    tmp_path: Path,
) -> tuple[
    JournalStore,
    TranscriptOverlayRepository,
    JournalStoreConsolidationSource,
    ArchiveOverlayRepository,
]:
    store = JournalStore(tmp_path)
    resolver = JournalStoreEventReferenceResolver(store)
    transcripts = TranscriptOverlayRepository(tmp_path, resolver)
    source = JournalStoreConsolidationSource(store)
    archive = ArchiveOverlayRepository(tmp_path)
    return store, transcripts, source, archive


def _executor(
    store: JournalStore,
    source,
    transcripts: TranscriptOverlayRepository,
    archive: ArchiveOverlayRepository,
) -> ConsolidationExecutor:
    """Build an executor. `source` is the (possibly flaky) execution source;
    the planner it wraps always reads through the real, non-flaky store
    adapter, matching how a real caller only ever injects one execution
    source and lets the executor drive its own internal planner."""
    resolver = JournalStoreEventReferenceResolver(store)
    annotations = AnnotationOverlayRepository(store.root, resolver)
    planner = ConsolidationPlanner(
        JournalStoreConsolidationSource(store), transcripts, annotations
    )
    return ConsolidationExecutor(planner, source, archive)


def test_active_session_is_never_executed(tmp_path: Path) -> None:
    store, transcripts, source, archive = _setup(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"RIFFfakewav")
    reference = store.append(_event("utterance-0001.wav"))
    transcripts.upsert_transcript(reference, "привет", TranscriptSource.GENERATED)
    executor = _executor(store, source, transcripts, archive)

    result = executor.execute_far_consolidation(
        _SESSION, active_session_id_provider=lambda: _SESSION
    )

    assert result.outcome is ConsolidationExecutionOutcome.ACTIVE_SESSION
    assert not result.executed
    assert result.run is None
    assert (tmp_path / _SESSION / "utterance-0001.wav").exists()
    assert not archive.read_run(_SESSION).found


def test_unknown_session_is_reported_without_touching_disk(tmp_path: Path) -> None:
    store, transcripts, source, archive = _setup(tmp_path)
    executor = _executor(store, source, transcripts, archive)

    result = executor.execute_far_consolidation(
        "does-not-exist", active_session_id_provider=_no_active_session
    )

    assert result.outcome is ConsolidationExecutionOutcome.UNKNOWN_SESSION
    assert not archive.read_run("does-not-exist").found


def test_execution_removes_transcribed_audio_and_records_the_run(
    tmp_path: Path,
) -> None:
    store, transcripts, source, archive = _setup(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"RIFFfakewav")
    reference = store.append(_event("utterance-0001.wav"))
    transcripts.upsert_transcript(reference, "привет", TranscriptSource.GENERATED)
    executor = _executor(store, source, transcripts, archive)

    result = executor.execute_far_consolidation(
        _SESSION, active_session_id_provider=_no_active_session
    )

    assert result.executed
    assert not (tmp_path / _SESSION / "utterance-0001.wav").exists()
    run = result.run
    assert run is not None
    assert run.status is ConsolidationRunStatus.COMPLETED
    assert run.removed_count == 1
    assert run.bytes_reclaimed == len(b"RIFFfakewav")
    stored = archive.read_run(_SESSION)
    assert stored.found
    assert stored.run == run
    assert executor.read_last_run(_SESSION) == stored


def test_untranscribed_audio_is_kept_on_disk_and_recorded_as_kept(
    tmp_path: Path,
) -> None:
    store, transcripts, source, archive = _setup(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"RIFFfakewav")
    store.append(_event("utterance-0001.wav"))
    executor = _executor(store, source, transcripts, archive)

    result = executor.execute_far_consolidation(
        _SESSION, active_session_id_provider=_no_active_session
    )

    assert result.executed
    assert (tmp_path / _SESSION / "utterance-0001.wav").exists()
    run = result.run
    assert run is not None
    assert run.status is ConsolidationRunStatus.COMPLETED
    assert run.removed_count == 0
    assert run.media_outcomes[0].outcome is MediaOutcome.KEPT


def test_partial_failure_is_reported_and_recovery_completes_on_retry(
    tmp_path: Path,
) -> None:
    """The idempotent-recovery design (owner decision, task v1.8.0-25): a
    failed deletion does not abort the run, and simply re-invoking execute
    afterward (simulating a restart, with the transient problem gone)
    finishes the remaining work without any special resume operation."""
    store, transcripts, source, archive = _setup(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"aaa")
    store.write_media(_SESSION, "utterance-0002.wav", b"bbbb")
    ref1 = store.append(_event("utterance-0001.wav"))
    ref2 = store.append(_event("utterance-0002.wav"))
    transcripts.upsert_transcript(ref1, "один", TranscriptSource.GENERATED)
    transcripts.upsert_transcript(ref2, "два", TranscriptSource.GENERATED)

    flaky = _FlakyOnceSource(source, fails_on="utterance-0002.wav")
    executor = _executor(store, flaky, transcripts, archive)
    first = executor.execute_far_consolidation(
        _SESSION, active_session_id_provider=_no_active_session
    )

    assert first.executed
    assert first.run is not None
    assert first.run.status is ConsolidationRunStatus.PARTIAL_FAILURE
    assert first.run.removed_count == 1
    assert first.run.failed_count == 1
    assert not (tmp_path / _SESSION / "utterance-0001.wav").exists()
    assert (tmp_path / _SESSION / "utterance-0002.wav").exists()

    # "Restart": the transient problem is gone, use the real (non-flaky) source.
    recovery_executor = _executor(store, source, transcripts, archive)
    second = recovery_executor.execute_far_consolidation(
        _SESSION, active_session_id_provider=_no_active_session
    )

    assert second.executed
    assert second.run is not None
    assert second.run.status is ConsolidationRunStatus.COMPLETED
    # The already-removed file is ALREADY_ABSENT on the fresh plan, so this
    # retry only had one real REMOVE candidate left.
    assert second.run.removed_count == 1
    assert not (tmp_path / _SESSION / "utterance-0002.wav").exists()

    # The archive store keeps only the latest run - the prior PARTIAL_FAILURE
    # row is overwritten, not appended to.
    stored = archive.read_run(_SESSION)
    assert stored.run == second.run


def test_execution_never_mutates_the_raw_journal(tmp_path: Path) -> None:
    store, transcripts, source, archive = _setup(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"RIFFfakewav")
    reference = store.append(_event("utterance-0001.wav"))
    transcripts.upsert_transcript(reference, "привет", TranscriptSource.GENERATED)
    events_file = tmp_path / _SESSION / "events.jsonl"
    events_before = events_file.read_bytes()

    executor = _executor(store, source, transcripts, archive)
    executor.execute_far_consolidation(
        _SESSION, active_session_id_provider=_no_active_session
    )

    assert events_file.read_bytes() == events_before


def test_concurrent_execute_calls_for_the_same_session_do_not_race(
    tmp_path: Path,
) -> None:
    """Codex stop-time review (2026-08-08): two overlapping execute calls for
    the same session (the transport dispatches each through asyncio.to_thread,
    so this is two real OS threads) used to both plan from the same
    pre-deletion state, both mark the one file REMOVE, and have the loser of
    the os.unlink() race fail with "file not found" - a real success reported
    as a false PARTIAL_FAILURE. The per-session lock serializes them: the
    second call's fresh re-plan only runs after the first call's deletion
    commits, so it correctly sees ALREADY_ABSENT and never re-attempts the
    delete."""
    store, transcripts, source, archive = _setup(tmp_path)
    store.write_media(_SESSION, "utterance-0001.wav", b"aaa")
    reference = store.append(_event("utterance-0001.wav"))
    transcripts.upsert_transcript(reference, "один", TranscriptSource.GENERATED)

    slow_source = _SlowDeleteSource(source, delay_seconds=0.15)
    executor = _executor(store, slow_source, transcripts, archive)

    results: list[ConsolidationExecutionResult] = []
    results_lock = threading.Lock()

    def run() -> None:
        result = executor.execute_far_consolidation(
            _SESSION, active_session_id_provider=_no_active_session
        )
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    for result in results:
        assert result.executed
        assert result.run is not None
        assert result.run.failed_count == 0

    # The real invariant: the second (lock-blocked) call's re-plan must see
    # the file as already gone and never itself call delete_media - not just
    # "no two delete_media calls overlapped", but "there was only ever one
    # delete_media call at all".
    assert slow_source.concurrent_delete_calls == 0
    assert slow_source.delete_call_count == 1

    assert sum(result.run.removed_count for result in results) == 1
    assert not (tmp_path / _SESSION / "utterance-0001.wav").exists()


def test_active_session_provider_is_evaluated_inside_the_lock_scope() -> None:
    """Codex stop-time review (2026-08-08, fourth pass): the first two
    attempts tried to prove call order (provider vs. lock) through timing -
    a "not yet called within N ms while the first call holds the lock"
    window, which can only make an ordering bug *unlikely* to observe, never
    prove it impossible. The third attempt switched to a source-text check
    (`source.index("active_session_id_provider()") >
    source.index("with self._lock_for(...)")`), which is not equivalent to
    "lexically inside the block" either: moving the call to a statement
    *after* the `with` block - still textually later in the source, no
    longer holding the lock at all - would satisfy that same substring-order
    check while breaking the actual guarantee.

    The real property is lexical nesting, and Python's own parser is the only
    thing that can decide that correctly (indentation heuristics can be
    fooled by comments or multi-line expressions; substring position ignores
    block structure entirely). This test parses the method with `ast`, finds
    the `with self._lock_for(...)` statement, and walks only the AST nodes
    reachable from *inside its body* to build the set of calls genuinely
    nested there. It then asserts every call to `active_session_id_provider`
    anywhere in the function is a member of that set - so a call moved after
    the block (same bug the substring check missed) shows up as a call
    outside the with-body's node set and fails the assertion, deterministically,
    every time the test runs, not with some probability.

    `test_concurrent_execute_calls_for_the_same_session_do_not_race` proves,
    at runtime, that the lock genuinely serializes same-session calls.
    Combined with the structural fact proved here - that the provider read is
    lexically inside that same serialized scope - the two together prove
    what no timing window could: a queued call's active-session check always
    reflects state after the previous call's full critical section.
    """
    source = textwrap.dedent(
        inspect.getsource(ConsolidationExecutor.execute_far_consolidation)
    )
    function_def = ast.parse(source).body[0]
    assert isinstance(function_def, ast.FunctionDef)

    with_statements = [
        node for node in ast.walk(function_def) if isinstance(node, ast.With)
    ]
    assert len(with_statements) == 1, "expected exactly one `with` block"
    with_statement = with_statements[0]

    # Every AST node genuinely reachable from inside the with-block's body -
    # not "textually after the `with` line", actual lexical descendants.
    inside_with_block = {
        id(node) for statement in with_statement.body for node in ast.walk(statement)
    }

    def is_provider_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "active_session_id_provider"
        )

    provider_calls = [node for node in ast.walk(function_def) if is_provider_call(node)]
    assert provider_calls, "active_session_id_provider() is never called"
    calls_outside_the_lock = [
        call for call in provider_calls if id(call) not in inside_with_block
    ]
    assert not calls_outside_the_lock, (
        "active_session_id_provider() must be called only lexically inside "
        "the `with self._lock_for(...)` block - a call anywhere outside it "
        "(even later in the function) races the lock's own wait exactly "
        "like a call before it"
    )
