# Task v2.1.0-10b: Proxy session UX (marker and new sessions)

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 10b. Follows
`tasks/done/task-v2.1.0-10-journal-surfaces.md` and the owner's remarks after the first live
run of 2026-10-23 (`tasks/backlog/personal-proxy-ux-followups.md`, items 1 and 2). Renaming a
session is task 10c, not this card.

## Summary

Two changes in the Journal surface for the personal proxy. (1) Proxy sessions and proxy
messages are marked so they are seen at a glance. (2) The "New context" control works in
the proxy mode and starts a new proxy session, so requests are no longer all kept in one
session.

## Boundary

UI (list, feed, strings, CSS, JS), the run-mode verdict for the new-context action, and the
small recorder/app path that starts a proxy session. No change to the service pipeline, the
stages, provenance or what is written per request (task 10). No rename (10c). No change of
the normal-mode "New context" behavior. No live call by the agent.

## Owner decisions (2026-10-23)

1. Marker: **an icon plus an amber accent**. A clearly visible icon (a shield or an
   arrow-out; the developer proposes one that reads at small size in both themes) in the
   session row and in the header of each proxy message (request, sent, answer, notice), plus a
   thin amber border or accent line. The two signals are independent, so the marker also
   works without color. Amber keeps its meaning "data goes out" (`PROJECT.md`: amber is
   reserved for warning/cloud).
2. New session: the existing **"New context" button starts a new proxy session in the proxy
   mode**, created lazily (the session appears in the list with the first request, no empty
   sessions). While a request is in flight or a confirmation question is pending the button
   is refused with a short visible reason, so a send is never cut off.

## Design

**Marker.** `title_kind = "proxy_session"` already reaches the client. Add the class and the
icon in `_journalSessionElement`, the same class and icon in the message header for the
sources `proxy_heard`, `proxy_sent`, `proxy_answer`, `proxy_notice`, amber tokens from the
existing palette (`--amber`, `--amber-dim`, `--amber-tint`). The selected row keeps its
selection marker (brightness or fill, not a color swap). The icon needs an accessible name
and a title in en and ru. Check contrast in the dark and the light theme.

**New session.** Today `JOURNAL_NEW_CONTEXT` is refused in `PERSONAL_PROXY`
(`core/run_mode.py`) and `JournalRecorder._session_id` is one per run. Allow the action in
this mode and route it to a recorder call that drops the current session id so the next
request creates a new one (`start_blank_session` exists; the developer decides lazy versus
eager reuse, with the lazy behavior as the requirement). It must not touch the main model's
context and must not run any assistant-mode "new context" side effect. The writer
(`ProxyJournalWriter`) must start a fresh answer buffer and never write a pending answer into
the new session: a pending answer is flushed (incomplete) into the old session first, or the
action is refused while one is pending (the refusal rule above covers it). The verdict table
test must still be exhaustive.

**Dock.** After the action the dock is inactive until the new session exists, with the same
dry-run-aware note as today.

## Required behavior

1. Everything in Design, test first.
2. Tests: the class and icon on a proxy session row and on each proxy message kind and
   not on other kinds; selected state; both themes' tokens exist; strings en/ru; the verdict
   for the action in the proxy mode (allowed) and its refusal while a request is in flight or
   a question is pending; a second request after the action lands in a new session; nothing
   from the old pending answer lands in the new session; normal-mode behavior unchanged; the
   9a/9b/10 invariants still hold (full suite).
3. A short human handoff only for what needs the real window: the look of the marker in both
   themes, the button while idle, during a request, during a question
   (`manual/personal-proxy-session-ux-handoff.md`, self-sufficient, passing
   `tools/check_handoff_self_sufficiency.py`).

## Acceptance criteria

- [x] Proxy sessions and proxy messages are visibly marked with an icon and an amber
      accent; other session kinds are unchanged.
- [x] "New context" in the proxy mode starts a new proxy session lazily; it is refused with
      a visible reason while a request or a question is in progress.
- [x] Nothing from one session's request or answer is written into another.
- [x] No assistant-mode side effect is triggered by the action in the proxy mode.
- [x] `python -m pytest`, `ruff check` and `ruff format --check` are green.


## Outcome (2026-10-23)

Accepted by the owner after a live run (the marker, the buttons, a new session after
"New context"). Developer subagent; one independent review round. It found one real race
and these defects, all fixed test first: `idle` became true before the INTERRUPTED notice
was posted, so "New context" could end the session and the notice then opened a stray second
session (reproduced with the real service and writer; `idle` now stays false until the
request and its notices are fully finished, a small change in `proxy_service.py`); the
check-then-act between the idle check and `end_session()` (a re-check after the flush);
`end_session` kept the media counter (untested); texts that were false for the proxy (the
"leave the current one?" confirm, a "request in progress" reason when the proxy was not
running, "the next request starts a new session" while the typing box is disabled);
handoff text out of step with the code. Suite: 5617 passed, 1 skipped; ruff clean.

Built: `JOURNAL_NEW_CONTEXT` is allowed in `PERSONAL_PROXY` and routed to
`PersonalProxyRuntime.start_new_session()` (BUSY while a request is in flight, a question is
pending, the queue is not empty or the proxy is not running), which flushes a held answer
as incomplete into the old session, drops the held request source and calls
`JournalRecorder.end_session()`; the next request creates the new session lazily. The
Orchestrator and the main model's context are never touched. The marker is the `proxy_out`
icon (an arrow leaving a box) in the session row and in each proxy message header plus a
3 px amber left edge. In the proxy mode the confirm dialog is skipped and an accepted action
clears the proxy chat panel's blocks (owner decisions, 2026-10-23).

Deviations, accepted: the Status Console has one dark palette (no light theme), so the
contrast of the amber tokens is tested against the dark panel colors; after the action the
list auto-selects the previous session (existing behavior), the dock stays inactive until the
new session exists; a proxy that is not up reports BUSY with its own text.

Follow-ups (owner, 2026-10-23): move the request input from the Status panel to the Journal
dock; show less in the "sent" block (see `tasks/backlog/personal-proxy-ux-followups.md`).
