# Task v2.1.0-10: Journal, provenance and Status Console surfaces

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 10, the "Journal shape" decision and
revision 3. Builds on `tasks/done/task-v2.1.0-9a-proxy-service.md` and
`tasks/done/task-v2.1.0-9b-app-wiring.md` (their "Notes for later tasks": persist the
blocks; the Journal dock is inactive because no session exists).

## Summary

Make the proxy exchange durable and safe to keep. A request that was heard and sent is
written to the Journal as a user-side record (the heard text whole, own source) and an
answer record (the restored text, a proxy provenance kind). Both are excluded from automatic
retrieval and from fork seeds, and are labeled in `search_history` and the Journal UI. The
Status Console gets a dry-run indicator and the last block reason. A test proves that logs
never contain the heard text.

## Boundary

No new Journal features: reuse `JournalRecorder`, the events, the store, the corpus and the
provenance machinery; add only the minimum (a source, a provenance kind, labels, a
recorder method). No change to stage behavior, the service pipeline or the gate. The service
stays journal-free; persistence is a separate writer behind the existing `ProxyChatSink`
port (a tee). No retention feature, no replay of blocks dropped while Hidden.

## Owner decisions (2026-10-22)

1. Provenance: **a separate kind and source** for proxy answers (not `mcp_canvas`), with the
   same exclusions as external content: never selected by automatic retrieval, never in a
   fork seed, visible in `search_history` and the Journal UI with a label. A proxy answer is
   never confused with an MCP canvas or its caller name.
2. Dry run: **nothing is written** to the Journal (the block holds the mapping, which is
   never stored). The `config.example.toml` comment that says dry-run output is
   "journaled" is corrected.
3. Answer: **one event per answer**, the restored text exactly as shown and spoken; the raw
   external answer with placeholders is not stored. An interrupted or failed answer is
   written with what was shown and an "incomplete" marker.
4. Session: **one Journal session per run**, created at the first request. Content-free
   notices are written too (topics refusal reason class, gate block category and position,
   not sent after decline or timeout, no speech, incomplete answer); the Status Console's
   last block reason reads from the same classification.

Decided by the lead as defaults (flag at review if wrong): the heard-text user record has its
own source and kind (it must not be eligible for main-assistant retrieval or fork seeding);
typed text is stored as typed, a spoken request keeps its raw voice and `raw_transcript` as
the story's "Journal shape" says; the mapping is never written; the sanitized request is
written (it is what went out); a Journal write failure never changes whether or what is
sent (the request continues, a content-free warning is logged without text); the Journal
dock becomes usable once the session exists, and its note is replaced.

## Design

**Writer.** `ProxyJournalWriter` (new module in `src/jarvis/personal_proxy/` or the journal
package, whichever matches the existing layout) implements `ProxyChatSink`, forwards every
block to the real sink first, then persists the ones in the table below. It uses the app's
`JournalRecorder` through a small method (for example `record_proxy_exchange_part`) so the
recorder stays the only writer. It never raises into the service; exceptions are caught and
logged by type only.

| Block | Written as |
|---|---|
| `HeardBlock` | user record, own source, text = heard text whole, metadata: doubts class, decision |
| spoken request audio | the existing raw-voice media path (as `record_voice_user` does), same event |
| `SentBlock` | system/assistant-side record, the sanitized request (messages), own source |
| answer sentences | buffered; one answer event at the end (or on failure/interrupt) |
| `NoticeBlock` | content-free system record: kind and enum/int details only |
| `DryRunBlock` | not written |

**Provenance and exclusions.** A new `ProvenanceSourceKind` for the proxy answer and one for
the proxy user-side records (names decided by the developer, consistent with the existing
ones), with eligibility {MODEL_SEARCH, JOURNAL_UI} only (never `AUTO_RETRIEVAL`), mapped in
`provenance_descriptor_from_corpus_event`. Add the sources to `_EXCLUDED_SOURCES` in
`fork.py`. Tests follow `tests/test_automatic_retrieval.py` (ineligible candidates are
dropped before the limit and do not use a slot; the query requires `AUTO_RETRIEVAL`) and
`tests/test_journal_fork.py`.

**Labels.** `search_history` serializes the new kinds; its model-facing note names them;
the Journal UI search labels and source strings (en/ru) exist; the session title shows a
proxy session. `_ExternalSessionProbe` must not misread a proxy session (user and answer
events mix).

**Status Console.** New state keys (in the snapshot and as deltas, like `data_locality`):
a dry-run indicator (from `settings.personal_proxy.dry_run`) and the last block reason
(content-free class and position, cleared by the next successful request). Strings en/ru.
The Journal dock works once the session exists; `journal_input_proxy_note` is replaced or
removed accordingly, and the dock still routes to the proxy (not to the main model).

**Privacy.** The Journal holds the heard text whole (story revision 3); nothing derived from
it reaches logs, exceptions or `repr`. A `caplog` test at DEBUG runs a full service pass with
a distinctive heard text, a mapping value and an answer, with the Journal writer in the
chain and with a failing recorder, and asserts none of them appears in the log text. The
logs hold only what goes out, with placeholders (the sent payload is already
placeholder-only).

## Required behavior

1. Everything in Design, test first.
2. Invariants, each tested: (a) after a full request the Journal holds the heard record, the
   sent record and one answer record, with the right sources and provenance; (b) none of them
   is selected by `select_automatic_retrieval_passages`; (c) none is in a fork seed and the
   drop is counted; (d) `search_history` returns the answer with its label; (e) dry run
   writes nothing; (f) the mapping and the raw (placeholder) external answer are never
   written; (g) a failing recorder does not change what is sent or shown; (h) logs never
   contain the heard text, the mapping values or the answer; (i) blocks are forwarded to the
   chat sink even when persistence fails.
3. The recorder, search, fork and corpus tests keep passing; corpus schema version is bumped
   only if the existing rule requires it.
4. A human-run handoff only if something needs the real UI: the Journal view showing the
   proxy session, labels, the dock, the Status Console indicators (self-sufficient, per
   CLAUDE.md Testing protocol 4).

## Acceptance criteria

- [x] A heard-and-sent request produces the heard, sent and answer records in one per-run
      session with the proxy provenance.
- [x] Proxy records are excluded from automatic retrieval and fork seeds, and labeled in
      `search_history` and the Journal UI.
- [x] Dry run writes nothing; the mapping is never stored.
- [x] A persistence failure never alters the request; logs never contain the heard text.
- [x] The Status Console shows the dry-run indicator and the last block reason without
      values.
- [x] The Journal dock works in the proxy mode and still routes to the proxy.
- [x] `python -m pytest`, `ruff check` and `ruff format --check` are green.


## Outcome (2026-10-23)

Accepted by the owner after a live happy-path run (a spoken request through the cloud model
via the local Ollama endpoint, the Journal session, the heard and sent records shown, the
dock). Developer subagent; one independent review round, which found no leak and no path
for a proxy record into automatic retrieval, a fork seed or an unlabeled `search_history`
hit; its findings were fixed test first: stale `PROJECT.md` text, `proxy_sent` and
`proxy_notice` mapped to `RAW_EVENT` (now explicit kinds, a new `PROXY_NOTICE`), enum details
shown as English slugs in the Russian "Last stop" line, an unsafe `uiString` on unknown
stored kinds, a misleading dock note in dry run, four surviving mutants, the pending-answer
flush when `service.close()` raises, identical placeholder session titles. After the live
run one layout bug was fixed (the dock grid kept three columns while the attach button was
hidden). Suite: 5559 passed, 1 skipped; ruff clean.

Built: sources `proxy_heard`, `proxy_sent`, `proxy_answer`, `proxy_notice`
(`journal/proxy_exchange.py`); provenance kinds `PROXY_REQUEST`, `PROXY_ANSWER`,
`PROXY_NOTICE`, none eligible for `AUTO_RETRIEVAL`, all four sources in the fork exclusions;
`ProxyJournalWriter` (a tee over `ProxyChatSink`, real sink first, never raises into the
service, one answer event, incomplete marker on interrupt, failure, close or the next
request); `notice_class` (content-free), `status_sink` and the `proxy_status` state key
(dry-run indicator, last block reason); Journal UI labels, localized details and the session
title "Personal proxy session YYYY-MM-DD HH:MM"; the dock works once a session exists; the
`dry_run` comment in `config.example.toml` corrected.

Change in the service (two persistence-only blocks, skipped by `TransportChatSink`): the raw
voice and the raw transcript never reached the sink, and nothing marked the end of an answer.
`RequestSourceBlock` is posted before the question and not in a dry run;
`AnswerCompleteBlock` only after a successful answer. Any new sink must skip them.

Decisions beyond the card, accepted: a refusal is stored as its kind only (the reason is
model text derived from the request); doubts are stored as their class only; the heard text
is kept whole, also for a declined or timed-out request; a Hidden window still writes to the
Journal; a dry run writes nothing, so with the default `dry_run = true` the Journal stays
empty and the dock stays inactive.

Limits and observations:
- Journal writing depends on the previous sink not raising.
- A speech failure in the middle of an answer lands before the answer event (order of
  writing, not of showing).
- Live run: a spoken harmless request ("tell briefly what a relay is") was refused once
  with `bad_placeholder` by the strict sanitize parser (a false refusal, fail-closed). Not
  investigated; watch for repeats.
- Only the happy path was checked live; the rest of the handoff
  (`manual/personal-proxy-journal-handoff.md`) is not run.

Follow-ups from the owner (2026-10-23), see `tasks/backlog/personal-proxy-ux-followups.md`:
a clearly visible marker for proxy sessions in the Journal, new sessions in the proxy mode,
renaming a session.
