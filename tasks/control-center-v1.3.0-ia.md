# Control Center v1.3.0 IA

**Status:** Accepted (2026-07-12; authored by the human, reviewed by the
agent - two implementation notes folded in below).
**Story:** `tasks/story-v1.3.0-control-center.md`
**Task:** `tasks/story-v1.3.0-task-1-control-center-ia.md`
**Source mock-up:** `.planning/UI/mock-ups/jarvis_dashboard_v3.html`

## Decision

Control Center v1.3.0 is the next version of the existing Status Console,
served by the v1.2.x local HTTP plus WebSocket transport. It is not a new
page, not a new transport, and not a new engine architecture.

The desktop surface becomes the dense control and review surface. The
touchstrip remains a glance/actions surface over the same snapshot contract.
No touchstrip settings menu, event log, memory panel, resource telemetry, or
mock-up dashboard grid is added.

## Contract Sources

Current authoritative state sources:

| UI concept | Source |
| --- | --- |
| Runtime state, label, substatus | `UiStateStore.runtime`, rendered from `RuntimeStateTracker` transitions |
| Module health | `UiStateStore.modules`, populated by `ModuleHealthTracker` via `ModuleHealthChanged` |
| Backend/model label | `UiStateStore.model.label` |
| Data locality | `UiStateStore.data_locality.locality` using `DataLocality` |
| Visibility mode | `UiStateStore.visibility.mode` using `VisibilityMode` |
| Thinking mode | `UiStateStore.thinking.is_enabled` |
| System events | `UiStateStore.system_events` and `system_event` deltas |
| UI language | `UiStateStore.ui_language.language` from `[ui].language` |
| Model and microphone selectors | `model_options`, `microphone_options`, `pending_restart` |
| Controls | protocol v1 `control/command` handlers in `UiTransportServer` |

The current contract already separates `DataLocality` from `VisibilityMode`.
This remains non-negotiable: `Hidden` never means local/cloud, and local/cloud
never changes visibility behavior.

## Small Task 3 Deltas

These are small enough for task 3 and do not require v1.2.x prep work:

| Delta | Shape | Reason |
| --- | --- | --- |
| Data-driven module rendering | Render `state.modules` plus known `MODULE_IDS` defaults, rather than fixed chip/card markup | The backend already publishes module health by `ModuleId`; the frontend needs to create rows/cards dynamically |
| Unknown module state | Treat every known `MODULE_IDS` entry absent from `state.modules` as `unavailable` with empty detail | Matches v1.2.14 "unknown before first signal" without fake success |
| Data presence summary | Add a small `data_presence` snapshot section owned by task 3 | Needed for honest microphone/screen/clipboard presence indicators |
| Data presence event inputs | Derive only from `ScreenshotCaptured`, `ClipboardSubmitted`, and `MicSleepToggled` | These events already exist and are authoritative |

Proposed `data_presence` shape for task 3:

```json
{
  "items": [
    {
      "kind": "microphone",
      "present": true,
      "detail": "awake"
    },
    {
      "kind": "screen",
      "present": true,
      "detail": "captured"
    },
    {
      "kind": "clipboard",
      "present": true,
      "detail": "submitted"
    }
  ]
}
```

Only present, observed sources should render. Absence means omission or
unknown, not "off", unless a real event says so.

Implementation notes for task 3 (from review):

- `detail` values travel as ui_text catalog keys resolved by the
  renderer in its own language - the same split as `ModuleHealthChanged`
  and `RuntimeStateChanged`. The literal strings in the JSON example
  above illustrate meaning, not wire format.
- Clipboard presence derives only from accepted submissions: a
  `ClipboardSubmitted` with `is_empty` is a rejected turn and must not
  set presence.

## Desktop Layout

Desktop Control Center keeps the current Status Console structure and evolves
it in place:

1. Top bar: brand, model/locality badge, visibility toggle.
2. Main status area: runtime orb, substatus, module health panel.
3. Control area: thinking toggle, settings, reset context, shutdown.
4. Config panel: model, microphone, TTS routes, UI language, VAD settings,
   pending restart.
5. Event panel: recent system events.
6. Reserved collapsed section: dangerous capabilities.

The dangerous capabilities slot is hidden by default and empty in v1.3.0. It
is a layout reservation only, for a later release with real action-taking
capabilities. It must not contain enabled controls, fake outbound logs, or
mock actions in v1.3.0.

## Touchstrip Layout

Touchstrip remains two pages:

| Page | Content |
| --- | --- |
| Glance | Runtime state, substatus, model plus locality line, visibility mode, key module dots |
| Actions | Thinking toggle, hold-to-reset context, hold-to-shutdown |

Do not add the desktop config panel, system event log, module cards, resource
meters, memory panel, or dangerous-capabilities slot to touchstrip.

## Mock-up Element Mapping

Classification:

- Backed now: can be shown from existing v1.2.14/v1.2.x state.
- Small delta: can be added in task 2 or task 3 without new architecture.
- Drop/disable: must not ship as active v1.3.0 UI.

| Mock-up element | Classification | Desktop placement | Touchstrip placement | State source / decision |
| --- | --- | --- | --- | --- |
| Page title `Jarvis Local - Control Center` | Backed now | Browser/window title and brand subtitle | Not shown | Static UI text; rename existing Status Console chrome |
| Dark/light theme tokens | Drop/disable | Optional future local UI preference, not v1.3.0 | Not shown | No config contract or state source |
| `data-state` visual color states | Backed now | Runtime orb/status styling | Glance orb styling | `runtime.state` |
| `data-source` local/cloud styling | Drop/disable as toggle | Badge only | Model/locality line | `data_locality.locality`; no cloud switch in v1.3.0 |
| `data-visibility` open/hidden styling | Backed now | Visibility toggle and hidden styling | Visibility text/toggle | `visibility.mode` |
| Presence strip | Backed now with wording fix | Top/sub-top visibility band or compact control | Glance visibility label only | `VisibilityMode`; must not claim muted TTS |
| Presence Open button | Backed now | Visibility toggle | Tap/toggle text | `set_visibility_mode(open)` |
| Presence Hidden button | Backed now | Visibility toggle | Tap/toggle text | `set_visibility_mode(hidden)` |
| Presence Hidden copy says TTS muted | Drop/disable | Replace copy | Not shown | Existing engine does not mute ordinary turns in Hidden |
| Source strip local banner | Backed now | Locality badge/band | Model/locality line | `DataLocality.LOCAL` |
| Source strip cloud banner | Drop/disable | No active cloud button | Not shown | No external backend selection in v1.3.0 |
| Source local button | Drop as control | Badge text only | Badge text only | Data locality is reported, not user-selected |
| Source cloud button | Drop/disable | Disabled only if needed for future affordance | Not shown | No engine capability |
| Top brand mark `J` | Backed now | Top bar | Not shown or orb only | Static UI chrome |
| Brand name `JARVIS Local` | Backed now | Top bar, renamed Control Center | Not shown | Static UI chrome plus locality badge |
| Status pill `Listening` | Backed now | Runtime status near orb/top | Glance state | `runtime.label` |
| Pulsing dot | Backed now | Runtime status visual | Glance orb visual | `runtime.state` |
| Model tag `OLLAMA ... local` | Backed now | Model chip/meta or top badge | Model/locality line | `model.label` plus `data_locality` |
| Theme toggle dark/light | Drop/disable | No v1.3.0 control | Not shown | No stored setting or contract |
| Sidebar section `Input` | Small delta | Fold into data-driven modules panel | Module dots only | Module health plus data presence |
| Sidebar Voice item | Backed now | Module card/row | Dot | `ModuleId.MICROPHONE` health |
| Sidebar Screen item | Backed now | Module card/row | Dot | `ModuleId.VISION` health |
| Sidebar section `Core` | Small delta | Module panel grouping only | Not grouped | Frontend grouping over module ids |
| Sidebar LLM item | Backed now | Backend module card/row | Model/locality line | `ModuleId.BACKEND`, `model.label` |
| Sidebar Memory item | Drop/disable | Show unavailable module only if known id remains | Dot may remain unavailable | No memory/vector-store capability |
| Sidebar Tools item | Drop/disable | Not shown | Not shown | No module id or engine capability |
| Sidebar Plugins item | Drop/disable | Not shown | Not shown | No plugin capability |
| Thinking mode switch | Backed now | Control area | Actions page | `thinking.is_enabled`, `toggle_thinking` |
| `v1.1` badge | Drop | Not shown | Not shown | Release badge is stale UI decoration |
| Sidebar section `Output` | Small delta | Module panel grouping only | Not grouped | Frontend grouping over `ModuleId.TTS` |
| Sidebar Speech/TTS item | Backed now | Module card/row | Dot | `ModuleId.TTS` health |
| Sidebar section `System` | Backed now | Control/config/log areas | Actions page for controls only | Static placement |
| Settings nav item | Backed now, expands in task 2 | Config panel | Not shown | Existing model/mic config, task 2 TTS/VAD/UI language |
| Event log nav item | Backed now | Event panel | Not shown | `system_events` |
| State selector demo buttons | Drop | Not shipped | Not shown | Demo-only state mutation, not engine state |
| Orb rings | Backed now | Main status | Glance orb | `runtime.state` styling |
| Orb core and glyph | Backed now | Main status | Glance orb | Static chrome plus runtime styling |
| Orb state text | Backed now | Main status | Glance state | `runtime.label` |
| Orb substatus text | Backed now | Main status | Glance substatus | `runtime.substatus` |
| Wave bars | Backed now as decorative runtime affordance | Optional runtime styling | Not needed | `runtime.state`; no audio level claim |
| Thinking strip process text | Drop/disable | Replace with thinking status only | Not shown | Reasoning text must never be exposed |
| CPU meter | Drop | Not shown | Not shown | CPU/GPU/RAM telemetry excluded |
| GPU meter | Drop | Not shown | Not shown | CPU/GPU/RAM telemetry excluded |
| RAM meter | Drop | Not shown | Not shown | CPU/GPU/RAM telemetry excluded |
| Network meter | Drop | Not shown | Not shown | No external backend/network telemetry |
| Modules header count `6 active` | Small delta | Module panel summary | Not shown | Compute from module health; no hardcoded count |
| Modules grid | Small delta | Replace current hardcoded chips with data-driven rows/cards | Dots only | `state.modules` plus known defaults |
| STT `Whisper` card | Drop/disable | Represent microphone health instead | Microphone dot | No STT/Whisper module exists |
| STT latency `340ms` | Drop | Not shown | Not shown | No latency state source |
| LLM `Ollama gemma4` card | Backed now | Backend module card/row | Model/locality line | `ModuleId.BACKEND`, `model.label` |
| LLM GPU percent | Drop | Not shown | Not shown | GPU telemetry excluded |
| Vision `CLIP` card | Drop/disable label | Vision module card/row | Vision dot | Use `Vision`, not CLIP; source is capture health |
| Vision waiting/capture meta | Backed now | Vision detail, hidden-safe | Dot only | `ModuleId.VISION.detail`; hidden masks detail |
| TTS `Silero (RU)` card | Backed now, expanded task 2 | TTS module card plus config panel | TTS dot | `ModuleId.TTS`; task 2 engine/model route values |
| TTS waiting/failed meta | Backed now | TTS detail | Dot only | `ModuleId.TTS.detail` |
| Card progress bars | Drop | Not shown | Not shown | No progress/load metric source |
| Memory section header | Drop | Not shown as memory panel | Not shown | Vector-store panel excluded |
| Dialog history card | Drop/disable | No active card | Not shown | No vector memory store/count source |
| Screen context card | Small delta as presence only | Data presence summary | Not shown | `ScreenshotCaptured`, no stored count/retention |
| Plugins card | Drop | Not shown | Not shown | No plugin capability |
| Memory counts and retention | Drop | Not shown | Not shown | No state source |
| Log panel title `ASYNC EVENT BUS` | Backed now with rename | Event panel | Not shown | `system_events`; title should be user-facing |
| Log rows for VAD/STT/CTX/MEM/THINK/NET/LLM/TTS/OUT | Backed only for real system events | Event panel | Not shown | Render actual `SystemEvent` only; no scripted rows |
| `THINK` log row text | Drop unless real event | Event panel only if published | Not shown | No reasoning or invented process text |
| `NET` cloud log row | Drop | Not shown | Not shown | No cloud request capability |
| `ENV` Hidden says muted/preview hidden | Backed only for preview-hidden | Event panel | Not shown | Existing event says screen preview hidden; do not mention muted TTS |
| Log footer `All data stays on device` | Backed now | Locality/help text if compact | Not shown | `DataLocality.LOCAL`; avoid cloud toggle copy |
| `setState()` demo behavior | Drop | Not shipped | Not shown | Engine owns runtime state |
| `applyLoad()` demo behavior | Drop | Not shipped | Not shown | Resource telemetry excluded |
| `setSource()` demo behavior | Drop | Not shipped | Not shown | No locality switching control |
| `setPresence()` demo behavior | Backed only as visibility command | Visibility control | Glance visibility command | Must not change TTS/mic behavior |
| `toggleThinking()` demo behavior | Backed now | Thinking control | Actions page | Existing command |
| `setTheme()` demo behavior | Drop | Not shipped | Not shown | No theme setting |

## Existing Controls To Keep

The mock-up does not show all current controls. These remain part of Control
Center because they are real engine controls:

| Control | Desktop placement | Touchstrip placement | Source |
| --- | --- | --- | --- |
| Reset context | Control area with confirmation | Hold-to-confirm action | `reset_context` command |
| Shutdown | Control area with confirmation | Hold-to-confirm action | `request_shutdown` command |
| Reset module request | Per-module affordance, visibly unsupported where engine lacks reset | Not shown | `reset_module` command publishes unsupported event |
| Model selection | Config panel | Not shown | `model_options`, `save_config_selection` |
| Microphone selection | Config panel | Not shown | `microphone_options`, `save_config_selection` |
| Pending restart banner | Config panel | Not shown | `pending_restart.pending` |

## Configuration Placement For Task 2

Desktop config panel sections:

| Section | Fields | Contract |
| --- | --- | --- |
| Backend | Model selector | Existing `[backend].model` UI writer |
| Microphone | Device selector | Existing `[microphone].device` UI writer |
| TTS routes | Engine and all parameters of its typed route per language | Existing `SileroTtsSettings` / `PiperTtsSettings` contracts |
| UI | UI language `en`/`ru` | Existing `[ui].language` |
| VAD | Threshold, max chunk, request-end pause, resume cooldown | Existing `VadSettings` |

All fields are restart-to-apply. No prompt editing belongs in v1.3.0 Control
Center.

## Data Locality Rules

Render locality as a reported state, not as a binary user switch. The UI must
support values beyond `local` and `external` without layout assumptions, even
though v1.3.0 runtime reports only local.

Allowed v1.3.0 copy:

- Local
- External backend
- Unknown external value rendered as its raw label or generic external badge

Disallowed v1.3.0 copy:

- "Ollama Cloud" as an available choice.
- Network transfer meters.
- Any claim that `Hidden` changes locality.

## Data Presence Rules

Presence is about recently observed input/context, not about where inference
runs and not about UI visibility:

| Presence kind | Event source | Render rule |
| --- | --- | --- |
| Microphone | `MicSleepToggled` | Show awake/asleep only after event or initial seeded state |
| Screen | `ScreenshotCaptured` | Show captured/present after capture; hide sensitive detail in Hidden |
| Clipboard | `ClipboardSubmitted` | Show submitted/present after event |

No counts, retention periods, vector-store claims, or persistent memory claims
are allowed in v1.3.0.

## Review Checklist

- Every mock-up element is classified above.
- All kept elements name an existing state source or a small task 2/task 3
  delta.
- CPU/GPU/RAM telemetry, memory/vector-store, cloud switching, plugin/tools,
  and invented logs are dropped or disabled.
- Desktop and touchstrip placement is fixed.
- Dangerous capabilities are reserved as hidden layout only.
- Human review is required before task 2 starts.
