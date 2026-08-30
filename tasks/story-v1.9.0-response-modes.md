# Story v1.9.0: Response modes (Text-Only / TTS-Only / Text+TTS)

**Status:** Proposed. No task cards opened yet.
**Created:** 2026-08-26.
**Roadmap:** `tasks/roadmap-v1.9-v2.0.md`.
**Version note:** `v1.9.0` is now the accepted slot for response modes in the
v1.9 -> v2.0 roadmap.

## Origin

Observation (owner): a reply full of bullets, tables, and inline links is
hard to *listen* to. Some content, though, cannot be spoken cleanly and
must not be dropped when it is critical (a table, a code block, a long URL,
an exact derivation). Discussion settled on three switchable response modes
rather than a single "voice-friendly" rewrite, and on the model *knowing
which output contract it is currently producing* instead of post-hoc
guessing.

## User-facing goal

The user can switch Jarvis between three response modes; the active mode
persists in config and is changed by voice, a hotkey, and the UI config
page. Default is today's behavior (Text-Only), so nothing changes until the
user opts in.

- **Mode 1 - Text-Only (default, current behavior).** Single pass, current
  text-oriented output contract. Streaming and sentence-buffered TTS behave
  exactly as today.
- **Mode 2 - TTS-Only.** Single pass, but the model produces a
  *self-contained voice contract*: prose, no bullets/tables/inline URLs,
  numbers and units spoken where it helps, long enumerations as connected
  speech. Nothing is shown that the spoken form would reference, so the
  spoken form references nothing external. For requests whose content has no
  "cannot-be-spoken" remainder; the user chooses this mode knowing that
  trade.
- **Mode 3 - Text+TTS.** Two passes. The first pass produces the canonical
  rich text (streamed to the screen as today). The second pass, **with
  reasoning off**, takes that *exact shown text* as input and produces a
  spoken derivative that *may* reference the visible content ("as in the
  table above"), because that content genuinely exists on screen and the
  user can open the window to see it. The screen streams immediately; only
  audio waits for the first pass to complete. This is intentionally higher-
  latency than a single-pass voice answer: the user gets a visible answer
  object first, then Jarvis speaks a guided rendering of that object.

## Design decisions (proposed here, confirmed by card approval)

- **Two distinct output contracts, not one.** Mode 2's voice contract must
  be self-contained (nothing shown -> nothing to reference). Mode 3's
  spoken-derivative contract is the opposite: it is allowed to reference the
  visible text. These are separate system directives; do not collapse them
  into a single "voice" prompt.
- **Mode 3's second pass consumes the exact shown text, not a re-read of the
  request.** This keeps references valid by construction and bounds drift:
  the second pass restates form, it does not re-derive content. Reasoning is
  off on the second pass - it is a pure form transformation.
- **Mode 3 suppresses the first-pass streaming TTS.** The existing
  sentence-buffered TTS path speaks the first pass today. In mode 3 that
  channel must be muted: the screen still streams, but only the second pass
  is spoken. This is a fork in the existing pipeline behavior, designed in,
  not bolted on afterward.
- **The mode is a three-state persistent runtime setting.** Closest existing
  precedent is `thinking_toggle` / `thinking_mode.py`: a persistent runtime
  state, toggled by a hotkey, consumed by future turns. Response mode
  follows the same shape, but three-valued and also settable from the UI
  config page and by voice.
- **One hotkey cycles the three states** (1 -> 2 -> 3 -> 1). Confirmed
  acceptable by owner; no separate per-mode bindings.
- **UI control is a drop-down, not a button group** (owner, 2026-08-29). The
  reasoning-level toggle is a `role="radiogroup"` of four buttons; the
  response-mode selector deliberately does *not* copy that. It is a `<select>`
  like the existing config selects (model / microphone / UI language), for
  three reasons: three named modes with trade-offs read better as labeled
  options than as terse buttons, the config page already speaks `<select>`
  for persisted single-choice settings, and a dropdown keeps the config panel
  compact. Detailed in task 2.
- **Response mode is persisted in config; reasoning level is not.** The
  closest precedent (`ReasoningLevelState`) resets to `off` at every launch -
  it has no config seed and the UI does not write it back. Response mode is
  different by owner intent: the chosen mode must survive a restart. So this
  story adds what the reasoning precedent lacks - a config field read at
  startup to seed the runtime state (task 1) and a UI write-back to
  `config.ui.toml` (task 2). The runtime-state shape still mirrors
  `ReasoningLevelState`; only the persistence is new.
- **Voice toggle needs intent recognition** and is therefore its own slice.
  Jarvis must reliably tell "switch to voice mode" (a command) from request
  content. The hotkey + UI give a working switch earlier; the voice path
  follows. Approach sketched by owner as a "UX-Aware-Prompt" plus matching
  result handlers - to be pinned down in that task card.
- **Default is Mode 1.** Nothing in the current pipeline changes until the
  user switches.
- **Canonical text and spoken derivative have separate roles (mode 3).** The
  rich first-pass text is the *authoritative* content of the turn: it alone
  goes to history and the retrieval/memory corpus, exactly as today. The
  spoken derivative is a *rendering attached to the same turn*, not a second
  assistant turn:
  - It is persisted **additively inside that turn's record**, so the
    append-only journal invariant holds (we enrich the turn, we do not add an
    event or a phantom duplicate turn).
  - It is **never fed to the retrieval/memory corpus.** It is a lossy
    restatement of the canon; indexing it duplicates the same meaning and
    risks search/memory drift, and its references ("as in the table above")
    are meaningless outside their own turn, so it is not a valid standalone
    retrieval unit by construction.
  - In the UI it appears as a **collapsed block under the reply** ("spoken
    aloud >"), always present, expandable on click.
- **Mode 3 is a text canvas plus spoken commentary, not just duplicate
  output.** The first pass creates the canonical text canvas - the block of
  content the user and future retrieval can rely on. The second pass is a
  voice log/commentary over that canvas: it may compress, prioritize, and
  verbally navigate the visible blocks, and may therefore be what the human
  remembers hearing. That does not make it an independent memory source. If
  the two layers diverge, the canvas is authoritative and the derivative is a
  rendering problem. Future search work may add a locator-only index for
  heard phrases, but it must return the owning assistant event and hydrate the
  canonical canvas, not feed the derivative into retrieval as standalone
  knowledge.
- **Mode 3 is a deliberate quality-for-latency trade.** It is a key feature,
  not an optimization path: Jarvis spends a second local backend pass so the
  user gets both a rich inspectable answer and a spoken guide to it. Users who
  need the lowest latency should choose Mode 1 or Mode 2; users who want the
  richer canvas+voice experience opt into the extra delay knowingly.
- **Replay (a Play button on the derivative) is out of scope here.** Replay
  is a separate, more primitive capability shipping first in
  `story-v1.8.2-replay-tts.md` (re-synthesis of persisted spoken text on
  demand). This story only guarantees the derivative *text* is persisted;
  once mode 3 lands, that story's Play control simply retargets from the
  canonical turn text to the derivative as the better replay source. No
  dependency inversion: modes ship without replay, replay sits on top.

## Boundaries

In scope:

- A three-valued response-mode setting persisted in config, read by the turn
  pipeline.
- The two output contracts (mode 2 self-contained voice; mode 3 spoken
  derivative referencing shown text) as system directives selected by mode.
- Mode 3's second backend pass (reasoning off) over the exact first-pass
  text, and suppression of first-pass streaming TTS in mode 3.
- A single cycling hotkey and a UI config-page control, both writing the
  same config field.
- Voice-triggered mode switching with request-vs-command intent
  disambiguation.

Out of scope:

- Per-request one-off overrides ("just this once, speak it"). The mode is a
  persisted state, not a per-turn flag, unless a later story revisits it.
- Replaying / re-listening to the spoken output (the Play button and its
  re-synthesis mechanism) - that is `story-v1.8.2-replay-tts.md`. This story
  only persists the derivative text; it adds no playback control of its own.
- Any change to the thinking-mode toggle, mic-sleep/privacy toggle, or
  interrupt hotkey contracts.
- Multi-voice / prosody / emotion work - unrelated.
- Choosing a new letter that collides with existing `ctrl+alt+<letter>`
  bindings; the card picks a free one or stops (see stop conditions).

## Scope (ordered task cards, to be opened one at a time)

1. **Output contracts + config field.** The three-valued response-mode enum
   (proposed `text` / `voice` / `text_voice`), its config default (`text`),
   validation, and the two output-contract system directives for modes 2 and
   3. The turn pipeline reads the field and selects the contract. No hotkey,
   no UI, no second pass yet - this slice just makes the mode selectable in
   config and honored on the first pass (modes 1 and 2 fully working;
   mode 3 falls back to mode-2-like or mode-1 behavior until task 3).
2. **Hotkey + UI toggle.** The single cycling hotkey (1->2->3->1) following
   the `thinking_toggle` precedent, and the UI config-page control - a
   `<select>` drop-down, not a button group (owner decision above). Both write
   the same persisted field; the running pipeline picks up the change for
   future turns.
3. **Mode 3 second pass + streaming-TTS suppression.** The second backend
   pass (reasoning off) over the exact shown text, the spoken-derivative
   contract, and muting the first-pass sentence-buffered TTS in mode 3.
   Screen streams first pass; audio speaks second pass only. Also persists
   the derivative additively in the turn record and renders it as the
   collapsed "spoken aloud >" block, keeping it out of the retrieval/memory
   corpus. (The Play control on that block belongs to
   `story-v1.8.2-replay-tts.md`, which retargets to this derivative once it
   exists.)
3b. **Status-tab live toggle; Settings drop-down becomes restart-to-apply.**
   Inserted 2026-08-30 after playtesting tasks 2-3: the Settings drop-down
   was found to be both misleading (it alone applies live with no restart,
   unlike every other field in that panel) and hard to discover (every other
   session-scoped toggle lives on the Status tab). Splits the single
   live+persisted field task 2 shipped into a live Status-tab button group
   (hotkey + buttons, session-only, mirrors the reasoning-level toggle) and a
   genuinely restart-to-apply Settings drop-down (the persisted default for
   the next launch, folded into the ordinary `UiConfigSelection` batch form).
   No new persisted field, no change to task 4's voice path. See
   `tasks/task-v1.9.0-3b-status-panel-response-mode-toggle.md`.
4. **Voice toggle with intent recognition.** The "UX-Aware-Prompt" and its
   result handlers that let a spoken "switch to <mode>" change the mode
   without being mistaken for request content. Reuses tasks 1-2's config
   field, and after 3b, drives the same live path task 3b's buttons/hotkey
   use - not the persisted default.
5. **Docs + release verification.** `config.example.toml` entry with a clear
   explanation of the three modes and their trade-offs, PROJECT.md update if
   an architectural decision is recorded, user docs, and the human-run
   verification handoff (hotkey, voice, and mode-3 audio timing are
   hardware/manual checks).

## Acceptance criteria

- [ ] Default behavior is unchanged: with no config change, Jarvis is in
      Text-Only and the current streaming/sentence-buffered TTS path behaves
      exactly as before this story.
- [ ] Mode 2 produces a self-contained spoken-friendly answer in one pass;
      no bullets/tables/inline URLs in the spoken output, and it references
      nothing that is not present to the listener.
- [ ] Mode 3 streams canonical rich text to the screen immediately, then
      speaks a derivative generated with reasoning off from the exact shown
      text; the first-pass streaming TTS is silent in this mode; spoken
      references ("as in the table above") correspond to actually visible
      content.
- [ ] The mode-3 spoken derivative is persisted additively inside its turn's
      record and shown as a collapsed block under the reply; the append-only
      journal invariant holds; the derivative does NOT appear in the
      retrieval/memory corpus (the canonical text alone does).
- [ ] The single hotkey cycles 1->2->3->1; the UI config page shows and sets
      the same state; both persist to the same config field and take effect
      for subsequent turns.
- [ ] A spoken mode-switch command changes the mode and is reliably
      distinguished from request content.
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green
      for all non-hardware logic; hotkey, voice, and mode-3 audio-timing
      checks are prepared human-run handoffs with exact commands.

## Stop conditions

- Stop if mode 3's second pass cannot cleanly take the first pass's *final*
  text as input within the current turn/backend structure (e.g. the pipeline
  has no point where the complete first-pass text is available before TTS
  begins) - that is a pipeline-shape problem, not a prompt detail.
- Stop if suppressing the first-pass streaming TTS in mode 3 cannot be a
  localized branch and would require reworking the sentence-buffering
  contract shared with modes 1 and 2.
- Stop if no free `ctrl+alt+<letter>` binding is available without
  reassigning an existing hotkey - reassignment is a user-facing breaking
  change needing its own decision.
- Stop if voice intent recognition cannot separate command from content at
  acceptable reliability without a larger addressing/wake-word mechanism -
  that would be a separate story, and the hotkey+UI switch already ships the
  feature without it.
