# Jarvis Vision

Jarvis is a local-first personal assistant system that connects the user's
devices, local models, tools, and home automation through one coherent
interface.

The long-term goal is not a single Windows application. The goal is a personal
system where a local model can run on one machine, work can happen from another
machine, mobile voice access can be added later, and trusted local integrations
can operate devices such as smart home equipment.

## Non-Goals

- Jarvis is not a cloud SaaS assistant.
- Jarvis is not a Windows-only GUI application.
- Jarvis is not a thin wrapper around one LLM backend.
- Jarvis is not an automation system that silently performs high-impact actions
  without explicit capability boundaries and user-visible state.

## Principles

- Local-first by default. Jarvis should not require a cloud service for its core
  runtime behavior.
- Local network is allowed as an optional deployment boundary. Multi-device
  operation may use LAN transport without changing the local-first guarantee.
- The core owns orchestration, policy, state, history, and tool routing.
- UI surfaces are thin clients. They display state and send explicit commands;
  they do not own engine behavior.
- LLM backends are replaceable compute providers, not Jarvis itself.
- Device and service integrations are capability-bounded adapters.
- State, events, and commands flow through explicit contracts rather than log
  parsing or UI-only assumptions.
- Privacy and locality are separate axes. Hidden/Open describes system
  visibility; Local/External describes where computation or data flow happens.

## Architecture Direction

Jarvis should evolve around five boundaries:

1. Core
   Orchestration, conversation state, permissions, routing, and system events.
2. Backend layer
   Local Ollama today, possibly remote-on-LAN Ollama or other compute providers
   later.
3. Surfaces
   Status Console, touchstrip, mobile app, web panel, voice-only endpoint, or
   other user-facing control surfaces.
4. Tool and device providers
   Home automation, files, browser/OS actions, calendar, notes, and other
   adapters with clear capability contracts.
5. Transport layer
   In-process first; later LAN transport such as WebSocket, HTTP, or another
   authenticated local protocol when a real remote surface needs it.

## Component Model (Jarvis 2.0 direction)

The long-term identity of Jarvis is a bus plus orchestrator. The LLM,
information sources (including PC input capture), and output devices are all
components registered with the orchestrator, not parts of a monolith.

- The event bus stays in-process on the orchestrator host. Remote components
  attach through authenticated protocol adapters that project bus traffic in
  both directions. Jarvis does not implement a distributed event bus.
- Registration is a handshake: a component declares its identity and
  capabilities before exchanging state or media. The wire protocol reserves
  this from its first version, even while the only client is local.
- Compute components live where they are implemented - typically on the
  orchestrator host (TTS synthesis, recognition via the LLM backend).
  Sensor and actuator components live on the node physically near the user
  (microphone capture, audio playback, screen capture, global hotkeys).
  Synthesis and playback are therefore separate components, as are capture
  and recognition.
- Multiple hosts may register components. The orchestrator arbitrates which
  sensor node is active at a given moment; the arbitration mechanics are a
  later decision, but the protocol leaves room for it via registration.
- Security direction for LAN operation: pairing-based trust, with
  host-issued client certificates (mTLS) as the leading option for
  component nodes; UI surfaces may use token auth instead. Not decided yet.

## Near-Term Implications

- Keep UI logic out of core modules.
- Keep backend-specific assumptions inside backend adapters.
- Stabilize state and command contracts before adding remote transport.
- Design the UI transport protocol (v1.2.x) as a multiplexed channel set
  (state, control, later audio) with no same-process or same-machine
  assumptions, while shipping it loopback-only.
- Treat the Status Console as the first management surface, not the final
  application shape.
- Do not add network dependency to core runtime just because a future transport
  may use the local network.
- Prefer honest incomplete state over fake success. If a module has no real
  health or lifecycle signal yet, record that boundary instead of inventing one.

