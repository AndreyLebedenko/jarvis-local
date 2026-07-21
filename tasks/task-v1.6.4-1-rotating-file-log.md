# Task v1.6.4-1: Rotating system log on disk

**Status:** Planned.
**Story:** `tasks/story-v1.6.4-observability-and-logging.md`
**Depends on:** nothing; first card of the story.

## Summary

Give the detailed English log a durable destination. Today
`publish_system_event()` writes `log_message` into `logging`, and
`logging` is configured by a bare `basicConfig()` with no file handler,
so the entire diagnostic stream exists only on stderr.

## Context you need

- `src/jarvis/app.py`'s `run()`: the single `logging.basicConfig()` call
  and the comment explaining why it was added (INFO-level events were
  being dropped silently). That comment stays true; this card extends
  the same reasoning from "visible in a terminal" to "recoverable after
  the fact".
- `src/jarvis/core/system_log.py`: `publish_system_event()` already
  separates `log_message` from `ui_message`. This card changes nothing
  about that function - it only gives its first output somewhere to go.
- The story's content rule: kinds, counts, durations, sizes; never
  payload content.
- `PROJECT.md`'s runtime locality contract: a local file sink opens no
  socket and is not a network capability. Confirm this explicitly in
  the card outcome so a future reader does not have to re-derive it.

## Owner decision (2026-07-21)

The log lives on the local filesystem, and the directory is a config
parameter - not a hardcoded path and not a platform-guessed location.

This makes it an engine setting, so it belongs in `config.toml` through
`Settings`, not in `config.ui.toml` (which holds UI overrides the
console writes). Follow the existing directory-setting precedent
exactly: `JournalSettings.root = "journal"` and
`MemorySettings.root = "memory"` in `src/jarvis/core/config.py` - a
plain string, relative to the same base those two resolve against, with
a working default so an untouched `config.toml` still produces a log.
Register the new section in `_SECTIONS` alongside the others.

## Boundary

- Logging configuration, its config section, and its documentation
  only. No new log call sites, no re-levelling of existing ones, no
  changes to what any component logs.
- The setting is the directory, not the file name. Rotation owns the
  file naming; letting the user name the file invites collisions with
  the rotation suffixes.
- No log shipping, no network sink, no telemetry of any kind.
- Rotation must be bounded in both size and file count; an unbounded
  log is a disk-space bug waiting for a long-running session.

## Requirements

- A new config section carries the log directory, defaulting to a
  working value, parsed and validated on the same terms as every other
  section in `src/jarvis/core/config.py`.
- A rotating file handler is installed alongside the existing stderr
  handler; stderr behavior when run from a terminal is unchanged.
- The format carries at minimum timestamp, level, logger name, and
  message - the existing `basicConfig` format is the starting point.
- Rotation parameters are explicit and justified in the card outcome,
  not inherited defaults.
- The log directory is created if missing, and a failure to open it
  degrades to stderr-only logging with a warning rather than preventing
  startup. Jarvis must not fail to start because it could not open a
  log file.
- No payload content is written by any path this card touches; where an
  existing call site already logs something payload-adjacent, report it
  rather than fixing it inline (that is a separate decision).

## Acceptance criteria

- [ ] Automated tests cover: the config section parses, defaults, and
      rejects bad input like its siblings; the handler is installed at
      the configured directory with the agreed rotation bounds; an
      unwritable log location degrades to stderr-only without raising;
      the format includes the required fields. Tests must not depend on
      a real long-running process.
- [ ] A human-run check confirms a file appears after a normal session,
      contains the detailed English lines, and is still there after the
      process exits.
- [ ] `python -m pytest` and Ruff checks are green.

## Human verification handoff

1. Start Jarvis normally (not from a terminal, so stderr is not
   attached) and let it complete at least one voice turn.
2. Shut it down through the Status Console.
3. Open the log file at the agreed location. Confirm it contains the
   startup lines, the turn's engine events, and the shutdown sequence.
4. Confirm no transcript text, clipboard text, or attachment content
   appears anywhere in the file.
5. Report the file size after a normal session so the rotation bounds
   can be sanity-checked against real usage.
