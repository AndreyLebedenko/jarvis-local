# Story v1.5.0: Dialog journal

**Status:** Completed.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.5.0 (displaces file attachments, moved to v1.6.0: a
persistent journal creates a reason to keep using Jarvis and is
infrastructure that later serves attachments, search, and session
continuation; attachments only improve input paths that already have
workarounds)

## User-facing goal

Every conversation with Jarvis is recorded to disk and survives restarts.
The user can browse past dialogs, search Jarvis's text answers, and filter
by date. Voice turns are preserved as audio, messenger-style; Jarvis's
answers are readable text.

## Background facts this story builds on

- Jarvis has no STT. Voice goes to the model as audio via the `/api/chat`
  `images` field; `ConversationHistory` records a placeholder for voice
  turns and real text only for clipboard turns.
- Conversation history is text-only and in-memory; it dies with the
  process (v1.0 human decision, see `PROJECT.md`).
- Every turn already carries a timestamp (time-context work).

## Layered design (decided in planning, 2026-07-16)

The journal is an append-only event log; everything else is a derived,
rebuildable layer on top:

1. **v1.5.0 (this story): persistence + browsing + search.**
   - JSONL event log per session: turn source, timestamp, text. Binary
     media (voice audio, screenshots) stored as files next to the log and
     referenced by path; never embedded in JSONL.
   - Raw events are stored; filtering happens at display time.
   - Each event reserves a `transcript` field: optional, derived, empty in
     v1.5.0. Later STT must not require a format change.
   - Journal viewer: browse sessions, see the dialog as a feed. Voice
     turns render as an audio tile (playable), assistant answers as text.
     Audio playback ships in v1.5.0 - it is also a debugging tool (hear
     exactly what the model received).
   - The feed is live: the current session appears and grows in real
     time, reusing the console's existing real-time event mechanism (the
     same channel that feeds System Events). This is a v1.5.0
     requirement, not polish - it is what makes v1.5.1 text input cheap
     and what makes the journal useful for debugging live turns.
   - Search over Jarvis's text answers and by date, backed by a SQLite
     FTS5 index derived from the JSONL log (stdlib sqlite3, zero new
     dependencies, rebuildable from the log at any time).
   - Known accepted limitation: FTS5 has no Russian stemming; search
     matches exact/prefix word forms. Morphology or semantic search is a
     later layer.
2. **v1.5.1 or later (separate stories, out of scope here):**
   - Text input from the Journal view: a typed message becomes a new turn
     source on the existing shared `_start_turn()` path (clipboard turns
     already send real text through it, so the backend path exists; this
     is UI work plus a new source tag). v1.5.0 must not preclude it: the
     event format treats source as an open set, and the feed layout
     reserves a bottom input dock (empty in v1.5.0) so adding the field
     does not re-layout scrolling/bottom-anchoring.
   - STT as lazy enrichment: user-triggered transcription via right-click
     on the audio tile (explicit human requirement, 2026-07-16). Local
     whisper or similar; fills the reserved `transcript` field.
   - Session continuation: load the tail of a past session (transcripts
     required) into context within an explicit budget; time gaps between
     sessions presented explicitly via the existing time-context
     mechanism.
   - Summary-plus-tail compression for long sessions; semantic search
     over transcripts, potentially reusing the local Qdrant MCP provider.

## UI/UX (decided in planning, 2026-07-16)

Current UI state: `docs/screenshots/en` and `docs/screenshots/ru` (Status
Console and Touchstrip). The console is a single-screen dashboard; the
journal introduces its first second view.

- The journal is a view inside the existing Status Console shell, not a
  separate app and not a new UI framework (same vanilla HTML/CSS/JS, same
  dark palette, same system font stack, no CDN/fonts).
- Navigation: a `Console | Journal` segmented control in the header, same
  visual language as the existing Open/Hidden and thinking-level
  controls. The header (LOCAL badge, Open/Hidden) is shared across views.
  The Journal view replaces the central column; the System Events panel
  is hidden while the journal is shown.
- Journal view layout: session list on the left (date, start time,
  duration, first meaningful utterance as title); selected session as a
  feed on the right. Messenger pattern: user turns right, Jarvis left.
  Voice turn renders as a playable audio tile with duration; clipboard
  turn as text with a source mark; screenshots as previews. The audio
  tile must be built so a v1.5.1+ right-click context menu (transcribe)
  attaches without re-layout.
- The feed is live for the current session: new turns append in real
  time (bottom-anchored scrolling). A bottom input dock is reserved in
  the layout, empty in v1.5.0; the v1.5.1 text-input field slots into it
  without re-layout.
- Search field plus date-range filter above the feed; results render as a
  filtered feed with match highlighting and a jump-to-session-context
  action.
- Hidden mode: while Hidden is active the entire Journal view shows a
  generic placeholder (same approach as the vision chip detail) - the
  journal is the most sensitive surface in the console (full dialog
  history and screenshots).
- Touchstrip is untouched in v1.5.0.
- After implementation, en/ru screenshots of the Journal view are added
  to `docs/screenshots/` via the same human-run pass as the existing
  ones.
- Implementation-level open point (for a task card, not blocking the
  story): how the WebView plays journal audio files from disk (file://
  access vs serving through the console's local server).

## Boundaries

- No STT in v1.5.0. Audio is the source of truth and is stored as-is;
  transcription is a derived layer added later. A journal that stored only
  transcripts and dropped audio would make recognition errors permanent
  corruption - do not do that.
- No session continuation in v1.5.0: the journal never feeds the model's
  context in this story.
- No graph storage. Dialog is a linear timestamped feed; graph structures
  are not justified for this story and are not the planned answer for
  continuation either.
- Runtime locality is untouched: journal writes to local disk only; the
  two-tier contract (v1.4.0 revision) is neither used nor relaxed.
- The in-memory `ConversationHistory` contract (text-only history sent to
  the model) does not change; the journal is a parallel record, not a
  replacement for the model-facing history.
- No input in v1.5.0: the Journal view is read-only (plus audio
  playback). The reserved input dock stays empty; text input is v1.5.1.
- Do not silently pull v1.5.1+ items (STT, text input, continuation,
  semantic search) into v1.5.0 task cards.

## Acceptance criteria draft

- [x] Every turn (voice, clipboard, and any other source) appends events
      to a per-session JSONL log; the log survives process restarts.
- [x] Voice audio is persisted as files referenced from the log; no
      binary payloads inside JSONL.
- [x] Event format includes source, timestamp, text, media references,
      and a reserved optional `transcript` field.
- [x] Journal viewer lists sessions and renders a session as a feed:
      audio tile for voice turns, text for assistant answers.
- [x] Voice audio tiles are playable in v1.5.0 (human-run check).
- [x] The current session renders live: a new turn appears in the open
      Journal view without reload, via the console's existing real-time
      channel.
- [x] Search over assistant answer text works, with date filtering; the
      index is derived and can be rebuilt from the JSONL logs.
- [x] The Journal view lives inside the Status Console shell, switched
      via a `Console | Journal` control; no new UI framework or external
      assets.
- [x] While Hidden is active, the Journal view shows a generic
      placeholder and exposes no dialog content.
- [x] Pure automated tests cover event serialization, log append/replay,
      index build, and search queries. Viewer and audio playback are
      human-run checks per the Testing protocol.

## Release verification

Task cards 01-07 and 08 are completed and moved to `tasks/done/`. The English
and Russian Journal screenshots are `docs/screenshots/{en,ru}/chat-log.jpg`;
the search flow and Journal playback were human-verified on 2026-07-17.
Automated verification on 2026-07-18 passed with `962 passed, 1 skipped`, plus
Ruff format and lint checks. The unresolved microphone shutdown race and the
open retention policy are documented in `tasks/bug_reports/`.

## Task card sequence

Ordered; each card is deliberately small and self-contained (explicit
file pointers, narrow boundary) so a modest executor can complete it
without whole-project context. 03 may run in parallel with 02; 07 needs
05 but not 06.

1. `tasks/task-journal-01-event-schema-and-store.md` - event schema +
   JSONL store (pure logic).
2. `tasks/task-journal-02-recorder-wiring.md` - record live turns +
   audio files, off the critical path.
3. `tasks/task-journal-03-search-index.md` - derived SQLite FTS5 index +
   query API (pure logic).
4. `tasks/task-journal-04-transport-api.md` - journal endpoints + live
   `journal_event` push + Hidden enforcement on the transport.
5. `tasks/task-journal-05-journal-view-static.md` - Journal view UI,
   read-only, reserved input dock, Hidden placeholder.
6. `tasks/task-journal-06-live-feed-and-playback.md` - live append +
   audio playback; carries the main human-run end-to-end handoff.
7. `tasks/task-journal-07-search-ui.md` - search field + date filter +
   jump to context.
8. `tasks/done/task-journal-08-docs-and-release.md` - PROJECT.md, en/ru
   screenshots, retention note, release wrap-up.

## Stop conditions

- Stop if journal writes measurably add latency to the turn path; logging
  must stay off the critical path.
- Stop if storing raw audio raises retention/privacy trade-offs that need
  a human decision (e.g. disk growth policy, Hidden-mode interaction with
  the journal).
- Stop if the viewer requires a UI framework decision beyond what the
  Status Console already established.
