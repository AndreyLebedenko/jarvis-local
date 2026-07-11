# Story v1.3.0: Control Center

**Status:** Backlog, blocked only by v1.2.10 UI transport.
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

## Prerequisites

- [x] v1.2.2 verification contract is complete.
- [x] v1.2.3 hygiene and known debts are complete.
- [x] v1.2.4 shutdown and configuration layer are complete.
- [x] v1.2.5 TTS measurements and engine boundary are complete.
- [x] v1.2.6 HotkeyProvider migration is complete.
- [ ] v1.2.10 UI transport (`tasks/story-v1.2.10-ui-transport.md`) is
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

1. Control Center information architecture
   (`story-v1.3.0-task-1-control-center-ia.md`).
   - Map engine capabilities that actually exist after v1.2.x.
   - Decide which controls belong on desktop vs touchstrip.
   - Modules panel is data-driven: the UI renders whatever module list
     arrives in the state snapshot, with no hardcoded module set in markup.
   - Host telemetry (CPU/GPU/RAM), if included, is collected engine-side
     and published as bus events delivered over the state channel - never
     measured by the UI client itself.
   - Data-locality presentation must not assume a binary local/cloud set;
     the contract and badge stay extensible even though v1.3.0 only ever
     shows the existing local value.

2. Configuration iteration 2
   (`story-v1.3.0-task-2-configuration-iteration-2.md`).
   - Add only settings backed by real config and engine contracts.
   - Preserve restart-to-apply where live reconfiguration is not supported.

3. Data-source and data-presence axes
   (`story-v1.3.0-task-3-data-axes.md`).
   - Use authoritative state only.
   - Avoid conflating privacy visibility with data locality.

4. Consolidated visual/manual QA
   (`story-v1.3.0-task-4-visual-manual-qa.md`).
   - Desktop.
   - Touchstrip.
   - Open/Hidden.
   - Locality.

## Stop Conditions

- Stop if a requested UI control has no real engine capability behind it.
- Stop if Control Center needs live reconfiguration not delivered by v1.2.x.
- Stop if data locality, data presence, and visibility mode semantics conflict.
- Stop if visual QA reveals overlapping text or unreadable touchstrip states.
