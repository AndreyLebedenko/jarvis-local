# Feature request: Journal search by session title

Status: Backlog.
Origin: owner request, 2026-10-24, while closing story v2.1.0 task 10f (session rename).
Not part of story v2.1.0.

## Summary

The Journal search matches event text only. Since a session can now carry a user title
(`session.json`, task 10f), the owner wants a search that also matches the session title,
the user title and the automatic one.

## Current state (commit 60ace0c plus the 10f working tree)

- Search results show the session's current title, but a title is never matched; this was
  already true for the automatic titles. `PROJECT.md` states it in the session metadata
  paragraph.
- The search projections do not read or copy `session.json`.

## Open questions for the design

- Match user title only, or the automatic title too (automatic titles are localized and
  carry a date stamp for proxy sessions).
- How a title hit is shown in results (a session-level hit without an event snippet).
- Whether the projection stores titles or the result list is filtered after the lookup;
  a rename must not force a rebuild of a whole projection.
- Interaction with the rule that the title is never read into model context or any proxy
  request.

## Acceptance criteria

- [ ] A query matching a user title returns that session; clearing the title removes the
      hit.
- [ ] A rename is reflected in search without a projection rebuild or restart.
- [ ] Event-text search behavior is unchanged.
- [ ] `python -m pytest`, `ruff check` and `ruff format --check` are green.
