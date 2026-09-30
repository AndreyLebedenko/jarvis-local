# Task v2.0-1: Single-instance guard

**Status:** Not started.
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Depends on:** nothing. First card of the story.
**Executor:** the story's executor profile. This card adds one small
process-level guard. It touches no dialog, journal, or UI code. If you find
yourself adding inter-process messaging, a "focus the running window" feature,
or a lock file, you have left this card - stop.

## Summary

Refuse a second Jarvis start while one is running, in every start mode
(headless, `--status-console`, and later `--mcp-mode`). The guard is a Windows
named mutex taken in `main()` before settings, logging, models, or windows are
touched.

## Why this exists

Owner constraint (story, settled constraint 1): normal mode and `--mcp-mode`
never run concurrently, "neither now nor in the future", and a second start is
refused, not merely discouraged. Today nothing prevents two instances: both
would open the microphone, load TTS, fight over global hotkeys, and append to
the same journal. v2.0 makes the risk concrete, because `--mcp-mode` is
exactly the kind of start a user runs beside an already-open Jarvis.

A named mutex is chosen over a lock file because the OS releases it when the
process dies. A crashed Jarvis therefore never leaves a stale lock the user
must find and delete.

## Required reading before implementing

- `src/jarvis/app.py`: `main()`, `parse_args()`, `run()`,
  `run_with_status_console()`.
- `src/jarvis/__main__.py` and `Jarvis.cmd` (the user's normal launcher runs
  `python -m jarvis --status-console %*` in a console window that closes on
  exit).
- `tests/test_package_entrypoint.py` for how the entry point is tested today.

## What to build

1. **`src/jarvis/core/single_instance.py`.** A small module that owns the
   guard:
   - a mutex name constant in the `Local\` namespace (per Windows logon
     session), for example `Local\Jarvis.SingleInstance`. It is global per
     user, not per workspace or project directory: the owner rejected
     workspaces as a way around the single-instance rule;
   - an acquire function returning a handle object (or a typed "already
     running" result). The real implementation calls `CreateMutexW` through
     `ctypes` and checks `GetLastError() == ERROR_ALREADY_EXISTS`;
   - the Win32 calls live behind an injectable acquirer so the decision logic
     is tested without a real mutex;
   - the handle is held for the whole process lifetime and closed on normal
     exit. Do not release it before shutdown finishes.
2. **Wire it first in `main()`.** Take the guard after `parse_args()` (so
   `--help` and argument errors still work while another instance runs) and
   before `run()` / `run_with_status_console()`. `run()` itself stays
   guard-free: tests and `manual/` scripts call it or `build_app()` directly
   and must not be blocked by a running Jarvis.
3. **Refusal is visible.** On refusal, write one English line to stderr and
   exit with a non-zero exit code of its own (named constant). With
   `--status-console`, also show a native message box (`MessageBoxW` through
   `ctypes`, no new dependency), because the `Jarvis.cmd` console window
   closes on exit and the user would otherwise see only a flash. The message
   says that Jarvis is already running and that only one instance may run at
   a time, in both modes.

## Explicitly out of scope

- Activating, focusing, or messaging the running instance.
- Any per-workspace or per-directory mutex naming.
- Non-Windows support (the project targets Windows 11 only).
- Changing `run()`, `build_app()`, or any test helper to take the guard.

## Tests

New `tests/test_single_instance.py` plus the entry-point tests:

- Acquire with a fake acquirer reporting "free" returns a held handle.
- Acquire with a fake acquirer reporting "already exists" returns the refused
  result and does not keep the handle.
- `main()` with a refusing guard exits with the named exit code and never
  calls `run()` / `run_with_status_console()` (both patched).
- `main()` with `--status-console` and a refusing guard calls the message-box
  seam; without `--status-console` it does not.
- `main(["--help"])` behaves as before with a refusing guard (argparse wins).

The real two-process refusal is hardware-free, but it is a whole-process
check. It goes into the task-8 human handoff, not the automated suite. Do not
spawn a second Python process from pytest.

## Acceptance criteria

- [ ] A second `python -m jarvis` start, with or without `--status-console`,
      is refused while one is running, with a visible message and a named
      non-zero exit code.
- [ ] The guard is released by process exit, including a crash (a named
      mutex, not a file).
- [ ] `run()` and `build_app()` stay guard-free; the existing suite needs no
      change to keep passing.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` green.

## Stop conditions

- Stop if `CreateMutexW` through `ctypes` cannot be made reliable in the
  project's Python 3.11 environment (for example a permissions error). That is
  an environment problem (section 0.9), not a reason to switch to a lock file
  silently.
