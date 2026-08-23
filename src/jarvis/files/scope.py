"""Builds a SessionFileScope from trusted journal fork provenance.

This is the journal-coupled half of session files: it reads raw journal
records to follow `metadata.continued_from` from the current session up its
ancestor chain, producing the ordered, read-only inherited scope the pure
SessionFileRepository then serves. It is rebuilt on each file-tool call, so a
deleted ancestor simply stops appearing - there is no cached scope to
invalidate. The model never supplies a session id; every id here comes from
trusted provenance the recorder wrote.
"""

from __future__ import annotations

from jarvis.files.session_files import SessionFileScope
from jarvis.journal.events import JournalEventRecord
from jarvis.journal.store import JournalStore

# A generous ceiling on how deep the continued_from chain is followed. Cycles
# are already stopped by the seen-set; this only bounds a pathologically long
# but acyclic hand-edited chain so resolution stays O(depth).
_MAX_INHERITED_DEPTH = 64


def resolve_session_file_scope(
    store: JournalStore,
    current_session_id: str | None,
    *,
    max_depth: int = _MAX_INHERITED_DEPTH,
) -> SessionFileScope:
    """Return the live file scope for ``current_session_id``.

    The current session anchors the scope: if it is absent or not
    journal-visible (no valid events - disabled journal, unstarted, deleted, or
    wholly corrupt), the result has no write session and no read scope, so every
    file tool reports no-active-session. Otherwise reads span the current
    session first, then each reachable ``continued_from`` ancestor in order.
    """
    if current_session_id is None:
        return SessionFileScope(write_session_id=None, read_session_ids=())
    current_records = store.read_session(current_session_id).records
    if not current_records:
        return SessionFileScope(write_session_id=None, read_session_ids=())

    read_ids = [current_session_id]
    seen = {current_session_id}
    ancestor = _continued_from(current_records)
    depth = 0
    while ancestor is not None and depth < max_depth:
        if ancestor in seen:
            break
        ancestor_records = store.read_session(ancestor).records
        if not ancestor_records:
            break
        read_ids.append(ancestor)
        seen.add(ancestor)
        ancestor = _continued_from(ancestor_records)
        depth += 1

    return SessionFileScope(
        write_session_id=current_session_id,
        read_session_ids=tuple(read_ids),
    )


def _continued_from(records: list[JournalEventRecord]) -> str | None:
    for record in records:
        value = record.event.metadata.get("continued_from")
        if isinstance(value, str) and value:
            return value
    return None
