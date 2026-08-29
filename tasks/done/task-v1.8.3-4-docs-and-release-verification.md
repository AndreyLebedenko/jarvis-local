# Task v1.8.3-4: Docs + release verification

**Status:** Completed. Docs updated (PROJECT.md v1.8.3 section finalized incl.
the completion-fix; v1.8.2 "no queue" and deferred-pause pointers; README.md +
README.ru.md replay section). `config.example.toml` needs no entries -
play-from-here and Pause/Resume are Journal UI controls, not config settings
or hotkeys. Consolidated hardware verification list below; tasks 1-3 were each
hardware-verified as they landed. `python -m pytest`, `ruff check`, `ruff
format --check` green. Merged to `main`.
**Story:** `tasks/story-v1.8.3-sequential-journal-playback.md`
**Depends on:** task-v1.8.3-1, -2, -3 (all implementation slices complete).

## Summary

Document the v1.8.3 architecture and prepare the release verification handoff.
Record the pausable playback primitive, the sequence engine, the two playback
mechanisms (assistant TTS vs voice-user direct wav), and the scoped revision
of v1.8.2's "no queue" rule. Update user-facing docs for the new controls
(play-from-here, Pause/Resume) and assemble the human-run verification list.

## Context you need

- PROJECT.md "Architecture v1.8.2 (reply replay)": its deferred pause/resume
  note (now delivered) and its "no queue" paragraph (now scoped to concurrent
  replay). Add an "Architecture v1.8.3 (sequential journal playback)" section
  rather than rewriting v1.8.2 history; cross-reference.
- `tasks/story-v1.8.3-sequential-journal-playback.md`: the locked decisions to
  mirror into PROJECT.md.
- `config.example.toml` and any user-facing docs that list replay/journal
  controls or hotkeys, if the new controls need entries.
- The verification-contract section of PROJECT.md for the CI/hardware split.

## Boundary

- Docs, config example, and verification handoff only. No behavior change.
- Do not re-open design decisions; record what tasks 1-3 shipped.

## Requirements

- PROJECT.md: new "Architecture v1.8.3" section covering the pausable
  callback-`OutputStream` primitive + position marker; the sequence engine
  (journal-order walk, skip typed-user/system, one channel, one held request);
  assistant-TTS vs voice-user-wav mechanisms; live-turn-cancels-sequence and
  busy-reject still holding; and the explicit scoping of v1.8.2's "no queue"
  to concurrent replay. Mark any settled facts appropriately.
- Update the v1.8.2 "no queue" paragraph in place with a one-line pointer to
  the v1.8.3 scoping (so the old text is not read as still absolute).
- `config.example.toml` / user docs: entries for play-from-here and
  Pause/Resume controls and any route/keybinding notes, matching what tasks
  1-2 implemented.
- Assemble the consolidated human-run verification list from tasks 1-3's
  handoffs with exact commands (pause/resume timing, sequence ordering,
  wav-vs-TTS mix, skip-typed, live-turn-cancel).

## Acceptance criteria

- [ ] PROJECT.md documents the v1.8.3 architecture and the scoped v1.8.2
      "no queue" revision; no contradiction remains between the two sections.
- [ ] `config.example.toml` / user docs describe the new controls accurately.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` are green.
- [ ] The human-run verification handoff is written with exact commands and
      covers every hardware/manual check from tasks 1-3.

## Verification handoff (human-run, hardware)

All checks use the status-console Journal. Start the app, open the Journal tab,
and pick a session with a mix of voice questions, typed requests, and replies:

```
python -m jarvis --status-console
```

Consolidated from tasks 1-3:

1. Single-reply Play/Stop (task 1). Press Play on the last reply in the log
   (nothing after it). It plays only that reply and the button returns to Play
   at the end. Press Play again, then Stop mid-playback: speech stops at once.
2. Pause/Resume (task 1). Press Play on a long reply, then Pause mid-sentence:
   audio suspends. Press Resume: it continues from the same point, not the
   start. Confirm Pause/Resume never restarts the clip.
3. Sequence order + play-from-here (task 2). Press Play on a reply in the
   middle of the log. It plays that reply and every later reply in order, back
   to back, to the end (or until Stop).
4. Now-playing highlight (task 2). During a sequence, confirm the Stop/Pause
   highlight moves onto whichever turn is playing now and clears at the end.
5. Pause during a sequence (task 2). Pause mid-sequence: it holds the current
   turn without skipping ahead. Resume continues; Stop ends the whole sequence.
6. Live turn cancels the sequence (task 2). Start a sequence, then speak a new
   request (or press the interrupt hotkey). The sequence stops, the highlight
   clears, and it does not resume afterward.
7. Busy reject (task 2). While a sequence plays, press Play on another turn:
   it is rejected with the error cue and a message, not queued.
8. Voice wav vs TTS mix + skip-typed (task 3). Start a sequence from the top
   of a mixed session: voice questions play your own recording, replies play
   TTS, in journal order; a typed request in the middle is skipped without a
   gap artifact.
9. Start on a voice turn (task 3, regression). Press Play directly on a voice
   question. It plays your recording AND continues to the following reply and
   the rest of the sequence - it must not stop after the voice turn.
