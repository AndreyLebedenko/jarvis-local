# Story v1.3.0: Control Center

**Status:** Backlog, deferred. Task cards removed pending future replanning.
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

## Acceptance Criteria

- [ ] Control Center uses the existing Status Console design system.
- [ ] Configuration iteration 2 exposes supported TTS engine, language, voice,
      and likely VAD settings where real engine/config contracts exist.
- [ ] Data-source and data-presence axes are implemented only where supported
      by authoritative runtime state.
- [ ] Touchstrip remains a glance/control surface, not a miniature dashboard.
- [ ] Desktop console remains suitable for denser control and event review.
- [ ] UI does not show fake success for engine capabilities that do not exist.
- [ ] Manual visual QA covers desktop and touchstrip surfaces.

## Task Card Sequence

No active task-card sequence. The previous decomposition was removed when
the story was deferred because it encoded unresolved product and architecture
decisions. Create a new sequence only after the story is reconsidered and its
boundaries are made implementable.

## Stop Conditions

- Stop if a requested UI control has no real engine capability behind it.
- Stop if Control Center needs live reconfiguration not delivered by v1.2.x.
- Stop if data locality, data presence, and visibility mode semantics conflict.
- Stop if visual QA reveals overlapping text or unreadable touchstrip states.
