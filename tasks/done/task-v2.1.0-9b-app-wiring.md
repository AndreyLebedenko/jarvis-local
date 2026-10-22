# Task v2.1.0-9b: Application wiring of the personal proxy

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 9b (the second half of task 9, split by
the owner on 2026-10-22). Builds on `tasks/done/task-v2.1.0-9a-proxy-service.md` (the
service, its ports and its "Notes for later tasks") and on tasks 1-8. Diagram:
`docs/architecture/personal-proxy-sequence.puml`.

## Summary

`--personal-proxy` currently changes nothing at runtime. After this task it starts a real
mode: `RunMode.PERSONAL_PROXY`, in which every utterance and every dock text message is a
request to `PersonalProxyService`, the main model and its tools are not used, and the
service's blocks are shown in the chat and its answers are spoken. The service itself
(9a) is not changed except where a gap shows up (reported, not silently patched).

## Boundary

In scope: `app.py` start/stop wiring, `core/run_mode.py` (mode, verdict tables), the
subscriptions, the dock text routing, hotkeys in this mode, the real adapters, the
transient `proxy_block` state key in the transport with its JS and UI strings, the second
`httpx` client, stage warm-up, startup validation and its failure surface, tests, and a
self-sufficient human-run handoff.

Out of scope: persistence of the blocks, the Journal and provenance surfaces (task 10),
the refactoring sweep (task 11), documentation of the whole feature (task 12), any change
to the stages' behavior, any live call by the agent (the handoff is run by the owner).

## Owner decisions (2026-10-22)

1. Controls that do not belong to the proxy (thinking, reasoning level, response mode, MCP,
   solo session, tool toggles, context reset, journal new context and fork, transcript,
   annotation and consolidation generation, replay) are **refused with a short visible
   message** in this mode. They never reach the main model. Kept working: dock text (it is
   rerouted into the proxy) and the TTS on/off switch.
2. The debug utterance recorder is **off** in this mode, so no utterance is written to disk
   outside the proxy path.
3. A failed startup validation **keeps the window open with the reason** and does not
   start the proxy (as the MCP mode does); nothing leaves the machine.

## Design

**Mode and verdicts.** Add `RunMode.PERSONAL_PROXY`; the verdict maps in `core/run_mode.py`
stay exhaustive (a test fails when a `ControlAction` has no verdict in the new mode).
Reuse the existing refusal path and message mechanism of the MCP mode. A UI badge names the
mode.

**Subscriptions.** In this mode the only consumer of utterances is the proxy handler
(a thin function that wraps the clip as WAV 16 kHz mono PCM_16 and calls
`ProxyInbox.submit`); the `Orchestrator` turn path and the debug recorder are not
subscribed. Dock text (`journal_text_submitter`) is routed to the same inbox as typed text.
Submission only enqueues; it never waits on the work.

**Hotkeys.** Bound: `interrupt` (calls the service `interrupt()` on the app loop, marshalled
with `run_coroutine_threadsafe`), shutdown, microphone sleep (with the capture
bookkeeping it needs). Inert or refused: capture, clipboard, thinking, response mode.

**Real adapters** (each a small class over the existing component, tested with fakes):
microphone gate over `auto_pause_for_speech` / `auto_resume_after_speech` with the
resume cooldown; speaker over `ReplayPlayer` that waits while it is BUSY and parses
each call on its own (9a port contract: speech control tags may recombine across calls);
the chat sink that posts each block as a transient `proxy_block` state key (transport `_set`,
`app.js` `_applyStateDelta`, strings in both languages, and the Hidden guard so a hidden
window does not show personal text); the locality reporter; the `language()` provider; the
stage callables bound with settings and backends (`PipelineStages`).

**Second httpx client** for the local check and restoration backends (`OllamaCheckBackend`
needs its own client), read timeout at least 120 s, closed at shutdown.

**Warm-up.** Instead of the main model's warm-up (`app.py` near the `warm_up(app.backend...)`
call) the stage warm-up runs: Whisper load, the check model at the 8192 variant, and the
service `warm_up()` before the first request, so the first restoration does not hit the
cold-load limit.

**Startup validation.** Whisper dependencies and weights, the topics file (`TopicsFileError`),
the API key environment variable, the endpoint rule (https or loopback http), Ollama and
the check model. Any failure keeps the window open with a content-free reason; the
proxy does not start; exit code 5 is not relied on (invisible from the launcher).

**Ordering.** Start: validation, adapters, warm-up, service `start()`, subscriptions.
Stop: unsubscribe, service `interrupt()` and `close()` (it resumes the microphone and
stops the speaker), close the second client, then the usual shutdown.

**Privacy.** No transcript, payload, mapping or answer text in logs, exceptions or `repr`
anywhere in the new code; the `proxy_block` state is transient and never written to disk.

## Required behavior

1. Everything in Design, test first.
2. Tests mirror `tests/test_main_mcp_mode.py`: the mode starts only with the flag; each
   `ControlAction` has a verdict in the new mode (coverage test); refused controls show the
   message and call nothing; utterances and dock text reach the inbox; the debug recorder is
   not subscribed; hotkey verdicts; startup failures keep the window open and start nothing;
   shutdown order and idempotence; the adapters with fakes (gate pause/resume balance,
   speaker BUSY wait, sink payload and hidden guard, client close).
3. A self-sufficient handoff for the owner (CLAUDE.md Testing protocol 4): the exact
   commands, config keys with source references, the state-independent way to reach each
   step: a voice request without a doubt, one with a doubt (yes, no, silence), typed text,
   dry run, the interrupt hotkey, a refused control, a startup failure, and the
   tray-launcher visibility of the failure.

## Acceptance criteria

- [x] With `--personal-proxy` a spoken or typed message runs the whole pipeline and the
      answer is shown and spoken; without the flag nothing changes.
- [x] Non-proxy controls are refused with a visible message and never reach the main model;
      a coverage test fails on a new `ControlAction` without a verdict.
- [x] The debug recorder and the `Orchestrator` turn path are not subscribed in this mode.
- [x] Startup validation failures keep the window open with the reason and start nothing.
- [x] Stage warm-up replaces the main model's; the second client is closed at shutdown.
- [x] `interrupt` during a question means "no"; during a request it stops it; the microphone
      is resumed on every path.
- [x] No personal text in logs; `proxy_block` is transient only.
- [x] The human handoff is prepared and passes `tools/check_handoff_self_sufficiency.py`.
- [x] `python -m pytest`, `ruff check` and `ruff format --check` are green.


## Outcome (2026-10-22)

Accepted by the owner on tests and review; the live run of
`manual/personal-proxy-wiring-handoff.md` (microphone, speakers, Ollama, a real window) was
not done at acceptance and stays with the owner. Developer subagent; one independent
review round. It found one leak and these defects, all fixed test first: `--debug` with
`--personal-proxy` wrote the transcript, topics, mapping and answer to the debug
transcript through the shared exchange recorder (now refused in `parse_args` and in
`run()`); the Journal dock could not send in this mode (it stays inactive with a note that
points to the proxy panel; attachments return a 409 with a reason); assembly wiring was not
pinned (five mutations survived, now killed); the UI claimed a healthy main model (false
warm-up event, Backend chip, top-bar model, "listening" cue on a failed start, "queue full"
for a proxy that never started); `StageDependencies.topics_text` in `repr`; unguarded proxy
stop in the shutdown path; `trust_env` on the local client; speech control tags in the
confirmation question; handoff steps that were state-dependent or unreachable. Suite: 5465
passed, 1 skipped; ruff clean.

Owner decisions after review (2026-10-22): a launcher entry for the personal proxy mode is
a separate task (`tasks/backlog/personal-proxy-launcher-mode.md`); orb progress states
("thinking", "speaking") are postponed (same file). A window that becomes Hidden cancels a
pending confirmation (added by the lead, accepted): the user cannot see the question, so a
voice "yes" must not confirm an invisible send.

Deviations from the card, accepted: no WAV re-wrapping step (`UtteranceChunk.wav_bytes` is
already 16 kHz mono PCM_16); no separate locality-reporter class (the transport's
`set_data_locality` is passed); Whisper is loaded during the startup checks instead of a
separate warm-up step; a proxy panel with its own input box in the Status view; the top bar
shows `[personal_proxy].model` (the external model); `CONSOLIDATION_EXECUTE` is refused as
the owner listed it (it is a deterministic archive overlay and reaches no model).

Limits:
- The tray launcher cannot start this mode; an exit-code-5 failure before the window is
  visible only in a terminal.
- Blocks sent while the window is Hidden are dropped, not replayed on Open.
- The orb does not show thinking or speaking during a request.
- The `dry_run` comment in `config.example.toml` says "journaled", which is true only after
  task 10.
- Documentation of the whole feature is task 12; the handoff says so.

Notes for later tasks:
- Task 10: persist the blocks (they are transient `proxy_block` deltas now); the Journal dock
  is inactive in this mode because no journal session exists.
