# Task v1.8.1-2: Session file scope inheritance

**Status:** Not started.
**Story:** `tasks/story-v1.8.1-session-file-operations.md`
**Depends on:** task-v1.8.1-1.

## Summary

Extend session-file scope from one current session to an ordered live read
scope: current session first, then read-only `continued_from` ancestors. Writes
remain current-session only.

## Context you need

- `tasks/story-v1.8.1-session-file-operations.md`: decisions 5 and 6, and the
  task-1b acceptance bullets.
- `src/jarvis/journal/recorder.py`: fork provenance event written by
  `start_fork_session()`.
- `src/jarvis/ui/transport.py`: the journal continue/fork path and
  `metadata.continued_from` shape currently emitted from UI flows.
- `src/jarvis/journal/store.py`: `read_session()`, missing/deleted session
  behavior, and traversal-safe session directory resolution.
- Task v1.5.3 fork cards and `PROJECT.md`: established fork/continue
  provenance contract.

## Boundary

- Scope construction and repository multi-scope lookup only. No builtin tool
  schemas or UI upload behavior.
- Inherited scopes are live pointers, not snapshots. Do not copy ancestor
  files into the child session.
- Do not add a model-supplied `session_id` argument or an ambiguity-resolution
  argument.

## Requirements

- Represent `SessionFileScope` with `write_session_id` and ordered
  `read_session_ids`.
- Resolve reads/list/stat/view by read-scope order: current session shadows
  nearest ancestor, then older ancestors.
- Keep write operations restricted to `write_session_id`; inherited sessions
  are read-only even when their files are visible.
- Build inherited scope by reading trusted journal provenance, following
  `metadata.continued_from` recursively from the current session.
- Rebuild scope on each file-tool call so deleted ancestors disappear without
  restart.
- Skip missing/deleted/corrupt ancestors and terminate on fixed depth and
  seen-set limits.
- Preserve the no-active-session invariant: absent current session, disabled
  journal, or not-yet-journal-visible current session returns typed
  `no_active_session`.
- Make manual duplicate storage names across scopes visible in `list` by
  reporting origin `session_id` and `scope`; deterministic lookup order is the
  only resolution policy.

## Acceptance criteria

- [ ] Tests cover current-session lookup before ancestor lookup for read,
      view, stat, and list.
- [ ] Tests cover inherited file reads while writes still target only the
      current session.
- [ ] Tests cover a manually duplicated storage name: read/stat choose current
      before ancestor, and list exposes both origins with scope metadata.
- [ ] Tests cover recursive `continued_from` ancestry, missing ancestors,
      deleted ancestors, corrupt provenance, cycles, and depth limit.
- [ ] Tests prove scope is rebuilt live: deleting an ancestor removes it from a
      later list/read without process restart.
- [ ] Tests cover no active and not-yet-journal-visible current sessions
      returning typed `no_active_session` without creating loose directories.

## Stop conditions

- Stop if fork provenance is not reconstructible from raw journal records with
  a deterministic rule.
- Stop if the live-scope resolver needs to cache state whose invalidation would
  become a lifecycle system of its own.
- Stop if scope inheritance would expose arbitrary model-controlled session
  ids.

## Verification

- Focused repository/scope tests.
- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
