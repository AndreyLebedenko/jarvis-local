# Story v1.3.0: Control Center

**Status:** Backlog, blocked by v1.2.x prerequisites.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.3.0

## User-facing goal

Deliver the full Control Center experience on top of engine capabilities that
already exist: verification contract, shutdown/control plane, configuration
layering, TTS engine choices, and unified hotkeys.

## Boundaries

- This is a UI/product release over existing capabilities.
- Do not introduce a new major engine architecture inside v1.3.0.
- If a new architectural prerequisite appears, move it back into a v1.2.x
  preparation release.
- Data locality remains independent from system visibility mode.
- Open/Hidden does not imply cloud/offline status.
- Hidden does not mute ordinary voice turns unless a later explicit product
  decision changes that behavior.

## Prerequisites

- [ ] v1.2.2 verification contract is complete.
- [ ] v1.2.3 hygiene and known debts are complete.
- [ ] v1.2.4 shutdown and configuration layer are complete.
- [ ] v1.2.5 TTS measurements and engine boundary are complete.
- [ ] v1.2.6 HotkeyProvider migration is complete.

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

1. Control Center information architecture.
   - Map engine capabilities that actually exist after v1.2.x.
   - Decide which controls belong on desktop vs touchstrip.

2. Configuration iteration 2.
   - Add only settings backed by real config and engine contracts.
   - Preserve restart-to-apply where live reconfiguration is not supported.

3. Data-source and data-presence axes.
   - Use authoritative state only.
   - Avoid conflating privacy visibility with data locality.

4. Consolidated visual/manual QA.
   - Desktop.
   - Touchstrip.
   - Open/Hidden.
   - Locality.

## Stop Conditions

- Stop if a requested UI control has no real engine capability behind it.
- Stop if Control Center needs live reconfiguration not delivered by v1.2.x.
- Stop if data locality, data presence, and visibility mode semantics conflict.
- Stop if visual QA reveals overlapping text or unreadable touchstrip states.
