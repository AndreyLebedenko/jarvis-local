# Task v2.1.0-10c: Proxy request input in the Journal dock

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 10c (renaming a session moves to 10d).
Follows `tasks/done/task-v2.1.0-10-journal-surfaces.md` and
`tasks/done/task-v2.1.0-10b-proxy-session-ux.md`; origin: the owner's UI remarks of
2026-10-23 (`tasks/backlog/personal-proxy-ux-followups.md`, items 5 and 6).

## Summary

The request input of the personal proxy moves from the Status panel to the Journal dock, and
the "sent" block stops repeating the fixed system prompt.

## Boundary

Status Console UI (JS, HTML, CSS, strings) and the dock's enable rule. No change to the
service pipeline, the stages, what is written to the Journal, or the transport route
(`/api/journal/input` already reaches the proxy). No rename (10d).

## Owner decisions (2026-10-23)

1. The input field in the Status "Personal proxy" panel is removed. The panel stays as the
   live read-only ribbon of blocks (heard, sent, answer, notices, dry-run state).
2. The Journal dock is the only place to type a request in the proxy mode. It is active
   when the selected session is the live proxy session, **and also when there is no live
   session yet** (at start, in dry run where no session is ever created, and after
   "New context"). A typed request starts the session like a spoken one does.
3. After "New context" the feed shows an empty "new session" state instead of the previous
   session, so the dock does not look attached to an old session. Selecting an older
   session makes the dock inactive with a note.
4. The "sent" block hides the system prompt when it equals the default
   (`DEFAULT_SYSTEM_PROMPT`): it shows the cleaned user text and a short label that a
   standard system prompt was sent, expandable on click. A system prompt that differs from
   the default is shown in full. The record in the Journal is not changed.

## Design

Dock rule: the dock is enabled in the proxy mode when (selected session is the live one) or
(no live proxy session exists). "Live session" is the id the server reports as active
(`active_session_id`); "no live session" is `null` after the start, after "New context" and
in dry run. Dry run needs the dock because the answer to a typed request is the dry-run
block in the Status ribbon: after sending, the dock's status line says that the result is in
the Status view (en/ru), and the Status panel hint text changes from "Say a request, or type
one below" to speaking or the Journal dock.

"New session" empty state: when the action is accepted and no live session exists, the feed
shows the empty-state message (reuse the existing empty-feed element) and no session is
selected; the first request makes the new session appear and become selected.

"Sent" block: the client decides by comparing the system message with the default prompt text
the server provides (a field in the block payload such as `system_is_default`, computed
server-side from `DEFAULT_SYSTEM_PROMPT`, so the page keeps no copy of the prompt). The same
rule applies in the Status ribbon and in the Journal feed for `proxy_sent` records.

## Required behavior

1. Everything in Design, test first.
2. Tests: no input field in the Status panel; the dock is enabled with the live session
   selected, with none selected and no live session, in dry run, after the new-context
   action, and inactive with an older session selected (with the note); a typed request from
   the dock reaches the proxy and not the main model (existing routing tests keep passing);
   the empty state after the action; the "sent" block hides a default system prompt in both
   places and shows a different one in full; strings en/ru; the 9a, 9b, 10, 10b invariants
   (full suite).
3. A short self-sufficient handoff for what needs the real window
   (`manual/personal-proxy-input-dock-handoff.md`, passing
   `tools/check_handoff_self_sufficiency.py`).

## Acceptance criteria

- [x] The Status panel has no input; the Journal dock sends proxy requests, also in dry
      run and before the first session exists.
- [x] The dock is inactive with an older session selected, with an explanation.
- [x] After "New context" no old session is shown as current.
- [x] A default system prompt is not repeated in the "sent" block; a changed one is shown.
- [x] Nothing reaches the main model; nothing new is written to the Journal.
- [x] `python -m pytest`, `ruff check` and `ruff format --check` are green.


## Outcome (2026-10-24)

Accepted by the owner. Developer subagent; one independent review round (14 mutations of the
dock rule, the pending flag and the sent view were all killed by the tests; privacy and
isolation sound). Fixed test first: `_journalNewSessionPending` stayed set when the first
request was spoken while another view was active (the feed then showed "New session" over
a live session and hid the dock; the Node harness now drives `applyJournalEvent`,
`setActiveView` and the refresh path), and the start of the proxy mode with older sessions on
disk now shows the new-session state too, with a dock note that a typed request starts a new
session. Suite: 5666 passed, 1 skipped; ruff clean.

Built: the Status "Personal proxy" panel is a read-only ribbon (no input); the Journal dock
is the only place to type a request in the proxy mode, active when the selected session is
the live one or when no live session exists (start, dry run, after "New context"), inactive
with a note when an older session is selected while a live one exists; attachments stay
refused; after an accepted "New context" the feed shows the empty new-session state and the
first request selects the new session. The "sent" block hides a default system prompt
behind an expandable label (`system_is_default` computed server-side in `sent_view.py`, a
changed prompt is shown in full); the stored records are unchanged.

Decisions beyond the card, accepted: the dry-run "Exact payload" keeps the full system
prompt; search snippets for `proxy_sent` still carry the system line; the stored-text split
of `proxy_sent` relies on the system prompt being a constant (pinned by a test and a
one-line note); the Node behavior tests skip when Node is missing (CI does not declare it).

Process note: the developer wrote the first version of the tests together with the code;
the review mutation run and the fix round were test first.

Observation (2026-10-23, live): the local sanitize model refused a harmless request with
the reason `DATE` ("what happened with the internet on Wednesday, 21 October this year?")
although no topics file exists; an earlier harmless request failed with `bad_placeholder`.
Both are fail-closed false refusals. Follow-ups: the `/force` command (task 10d) and a
separate fix of the empty-topics prompt and the refusal check.
