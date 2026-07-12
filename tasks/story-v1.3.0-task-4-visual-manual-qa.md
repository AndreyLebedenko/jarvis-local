# Task: Consolidated visual and manual QA

**Story:** `tasks/story-v1.3.0-control-center.md`
**Status:** Planned. Blocked by tasks 2 and 3.
**Release:** v1.3.0

## Summary

Prepare the consolidated human-run QA pass for the evolved Control Center.
The agent prepares scripts, checklists, and exact commands; the human runs
everything needing real windows, hardware, or visual judgment.

## Current Boundary

- Surfaces: desktop console as WebView2 window and as a Chrome client on
  the same loopback URL (both must behave identically), and the
  touchstrip.
- Checklist covers:
  - Open/Hidden on both surfaces;
  - modules panel across real health transitions (for example TTS route
    load failure, backend warm-up, mic sleep toggle) - driven through
    real actions where possible, through the dev QA harness where a state
    is hard to trigger on demand;
  - configuration iteration 2 flows end-to-end including restart-to-apply
    and invalid-value rejection;
  - data-source and timestamp-first last-request displays, including their
    independence from visibility mode; verify voice duration, clipboard,
    voice-plus-screenshot, and that rejected/busy input creates no entry;
  - both UI languages (en/ru) for the new sections;
  - layout geometry: no overlapping text or cramped columns on either
    surface (the v1.2.10 QA precedent - measure, do not eyeball).
- Extend the existing demo/QA harness for new states; harness stays
  dev-only and out of the production surface.
- Findings not fixed in v1.3.0 are written up per the bug-report
  protocol.
- Update README/README.ru where the Control Center changes user-visible
  behavior.

## Acceptance Criteria

- [ ] Checklist covers all combinations above with exact human-run
      commands.
- [ ] Automated tests cover harness wiring and the layout checks that can
      run headless.
- [ ] `python -m pytest` passes.
- [ ] Human has run the checklist; results and bug reports recorded.
- [ ] Story acceptance criteria checked off against the QA results.

## Stop Conditions

- Stop if QA reveals overlapping text or unreadable touchstrip states
  (story stop condition).
- Stop if WebView2 and Chrome render or behave differently in a way that
  requires surface-specific code.
