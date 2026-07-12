# Story v1.3.0: Control Center

**Status:** Completed.
**Replanned:** 2026-07-11, after v1.2.10-v1.2.13 landed. Product decisions
fixed by the human: Control Center is an evolution of the existing Status
Console page (not a separate page); module health foundation moves to the
v1.2.14 prep release; CPU/GPU/RAM telemetry is dropped from this release;
the mock-up's memory/vector-store panel is dropped (no engine capability).
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.3.0

## User-facing goal

Deliver the full Control Center experience on top of engine capabilities that
already exist: verification contract, shutdown/control plane, configuration
layering, TTS engine choices, and unified hotkeys.

## Boundaries

- This is a UI/product release over existing capabilities.
- Do not introduce a new major engine architecture inside v1.3.0.
- The UI is a client of the v1.2.x UI transport (local HTTP+WS server);
  no new transport work happens inside v1.3.0. Audio channels, multi-host
  operation, LAN binding, and node authentication stay out of this release.
- If a new architectural prerequisite appears, move it back into a v1.2.x
  preparation release.
- Data locality remains independent from system visibility mode.
- Open/Hidden does not imply cloud/offline status.
- Hidden does not mute ordinary voice turns unless a later explicit product
  decision changes that behavior.
- Layout reservation only, no implementation: the Control Center layout
  reserves a place for a hidden-by-default "dangerous capabilities"
  section (enable control with auto-off timer, outbound-data log). The
  section itself ships with the first release that has a real
  action-taking capability behind it (post-v1.4.0 actions/watchdog
  story); building it earlier would violate the no-fake-success rule.

## Prerequisites

- [x] v1.2.2 verification contract is complete.
- [x] v1.2.3 hygiene and known debts are complete.
- [x] v1.2.4 shutdown and configuration layer are complete.
- [x] v1.2.5 TTS measurements and engine boundary are complete.
- [x] v1.2.6 HotkeyProvider migration is complete.
- [x] v1.2.10 UI transport (`tasks/done/story-v1.2.10-ui-transport.md`) is
      complete: local HTTP+WebSocket server bound to loopback, registration
      handshake in protocol v1, Status Console and touchstrip migrated from
      the `evaluate_js` bridge to the WS channels.
- [x] v1.2.14 UI State Foundation
      (`tasks/done/story-v1.2.14-ui-state-foundation.md`) is complete:
      RuntimeStateTracker owns state transitions, authoritative module
      health events exist for backend/TTS/vision/microphone, and the
      surface contract is capability-based.
- [x] v1.2.16 Model request composition state
      (`tasks/done/task-v1.2.16-model-request-composition.md`) is complete:
      latest accepted backend-request metadata is authoritative and available
      to the UI transport without exposing request content.

## Acceptance Criteria

- [x] Control Center uses the existing Status Console design system.
- [x] Configuration iteration 2 exposes supported TTS engine, language, voice,
      and likely VAD settings where real engine/config contracts exist.
- [x] Data-source and last-request axes are implemented only where supported
      by authoritative runtime state.
- [x] Touchstrip remains a glance/control surface, not a miniature dashboard.
- [x] Desktop console remains suitable for denser control and event review.
- [x] UI does not show fake success for engine capabilities that do not exist.
- [x] Manual visual QA covers desktop and touchstrip surfaces.

## Task Card Sequence

Replanned 2026-07-11 with the product decisions above fixed and the
architecture gaps moved to v1.2.14.

1. Control Center information architecture
   (`done/story-v1.3.0-task-1-control-center-ia.md`; deliverable:
   `control-center-v1.3.0-ia.md`).
   Map every dashboard-v3 mock-up element to real state or drop it
   visibly; decide desktop vs touchstrip placement; reserve the
   dangerous-capabilities slot.
2. Configuration iteration 2
   (`story-v1.3.0-task-2-configuration-iteration-2.md`).
   Fully typed per-language TTS engine settings, UI language, VAD settings - all backed
   by existing config contracts, restart-to-apply preserved.
3. Modules panel and data axes
   (`story-v1.3.0-task-3-modules-panel-and-data-axes.md`).
   Data-driven modules panel over v1.2.14 health events; extensible
   data-source badge; timestamp-first last-request summary from v1.2.16.
4. Consolidated visual/manual QA
   (`story-v1.3.0-task-4-visual-manual-qa.md`).
   Desktop (WebView2 and Chrome), touchstrip, Open/Hidden, config flows.

## Stop Conditions

- Stop if a requested UI control has no real engine capability behind it.
- Stop if Control Center needs live reconfiguration not delivered by v1.2.x.
- Stop if data locality, last-request, and visibility mode semantics conflict.
- Stop if visual QA reveals overlapping text or unreadable touchstrip states.
