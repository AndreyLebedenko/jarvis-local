# Backlog: Region-select overlay threading

**Status:** Backlog.
**Source:** `tasks/bug_reports/capture-region-select-tkinter-thread-safety.md`

## Summary

Replace or rework the screenshot region-select overlay so it no longer depends
on constructing and running a Tkinter UI from a global-hotkey callback thread.

## Context

`capture.py` currently calls `select_region_interactively()` from the screenshot
region hotkey callback. With the current `keyboard` package, that callback runs
on the package's own listener thread. The overlay creates a fresh `tk.Tk()` and
runs `mainloop()` there, which is a plausible cause of the observed
out-of-order mouse event crash recorded in the bug report.

The defensive guard currently prevents the observed `KeyError`, but it does
not turn this into a sound UI architecture. The risk is localized to the
region-select workflow; it is not the main voice pipeline's highest-priority
stability issue.

## Current Boundary

- Do not fold this into the HotkeyProvider migration unless the migration
  directly changes region-select threading.
- Do not replace the overlay blindly without human-run visual verification.
- Keep full-screen screenshot capture out of scope unless the same change
  naturally covers it.

## Possible Approaches

- Route the region-select interaction through a single persistent UI thread.
- Replace the Tkinter overlay with a pywebview/status-console based selector.
- Replace the ad hoc overlay with a Windows-native region selector.

## Acceptance Criteria

- [ ] Region selection no longer creates a Tkinter root from an arbitrary
      hotkey callback thread.
- [ ] Escape cancel still works.
- [ ] Zero-size selections are ignored.
- [ ] Selected coordinates are correct on the human's display setup.
- [ ] Human handoff verifies repeated region selection without callback errors.

## Stop Conditions

- Stop if the implementation depends on untested display, DPI, or multi-monitor
  behavior that cannot be verified by the agent.
- Stop if replacing the overlay requires a broader screenshot/capture redesign.
- Stop if the HotkeyProvider migration changes the callback/threading model in
  a way that invalidates this task's assumptions.
