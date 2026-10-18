# Story v2.1.0: Personal proxy (external model behind a local sensitive-data gate)

**Status:** Approved by the owner, 2026-10-18 (including `--personal-proxy`
as a launch flag). No task card is started.
**Created:** 2026-10-18
**Updated:** 2026-10-18
**Roadmap:** `tasks/roadmap-v1.9-v2.0.md`. This story reverses the item
"Rejected for v2.0" in that file (see "Reversal of a recorded rejection").
**Predecessors:** `tasks/done/story-v2.0-mcp-voice-guide.md` (done) shipped the
`VoiceGuideService` pattern (a bus-free `iter_chat()` pipeline outside the
turn lifecycle, journaled with a non-Jarvis provenance) that this story reuses.
`story-v1.9.0-response-modes.md` (done) shipped the `text_voice` response mode
that renders the result.
**Executor profile:** same as story-v2.0. Task cards name files, precedents,
and boundaries literally, prefer "mirror this existing pattern" over open-ended
design, and state up front what they must NOT touch.

## Origin

Owner planning dialog, 2026-10-18. The local model is weaker than the best
external models. The owner wants to ask an external model a question by voice
without the voice, and without the identifying details of the question, leaving
the machine. Jarvis listens to the microphone, removes sensitive content from
the request while keeping its meaning, sends the cleaned text request to an
external model over an API, receives the answer, restores the removed details
locally, and presents it in Text+Voice mode. The audio never leaves the
machine.

## Reversal of a recorded rejection

The v2.0 roadmap rejected "Jarvis calling an external LLM itself, with local
STT and a local sensitive-data gate" for four reasons and said it "may return
later". The owner brings it back now. Each reason is answered here, not
ignored:

1. **It revises the unconditional core-inference locality contract.** Answered
   by task 2: external inference becomes a second explicit, off-by-default,
   per-component capability under the existing two-tier contract
   (`PROJECT.md`, runtime locality contract). Core orchestration and the local
   Ollama backend stay unconditionally local.
2. **A bare Gemma-class transcription pass is "recorded as unreliable".**
   Substantiated by the closed bug reports
   `2026-09-01-request-shape-suppresses-audio-attention.md` and
   `2026-08-04-transcription-model-refuses-audio.md`: audio attention on
   Gemma 4 12B depends on the request shape (a system prompt, tool
   declarations, and the current-turn wording each degraded transcription of
   the same clips), very short clips are fragile, and the only best-measured
   shape is the bare request with the English verbatim instruction, which was
   still usable on only 3/5 clips for the Q8_0 variants. (An earlier draft of
   this card said the roadmap's claim could not be substantiated; that was
   wrong, the records are in the bug reports, not in `PROJECT.md`.) A combined
   transcribe-and-sanitize call needs exactly the long instruction those
   studies found risky. The owner's decision to merge transcription and
   sanitization into one Gemma pass is therefore a hypothesis against the
   prior, and task 1 is a measured spike with a frozen decision rule and a
   defined fallback (two steps: the existing bare transcription, then a
   text-only sanitize pass).
3. **It needs an API-key store.** v1 reads the key from an environment
   variable and never from `config.toml`. `tasks/backlog/secret-storage.md`
   stays a separate, unblocked backlog item.
4. **The leakage gate can reduce but never prove absence of sensitive data.**
   Accepted as the permanent honest limit. Every user-visible and documented
   statement says "reduces", never "protects" or "guarantees".

Version note: `tasks/roadmap-v1.9-v2.0.md` already has a heading "v2.1 -
Canvas-guided voice". The owner chose v2.1.0 for this story. Task 10 renumbers
that roadmap section; this card does not edit the roadmap.

## User-facing goal

- The user starts Jarvis with `--personal-proxy` (see design decisions for why
  a launch flag). Jarvis uses the microphone exactly as in normal mode.
- The user asks a question by voice. Jarvis shows and speaks the external
  model's answer in `text_voice` mode, with the details the user mentioned
  (names, numbers, places) restored in the answer.
- Nothing about the voice, and nothing sensitive that the sanitizer or the
  gate recognizes, is sent. If the gate blocks the request, the user is told
  why (the category, not the value), and nothing is sent.
- A dry-run setting runs the whole path up to and including the gate, shows
  what would have been sent, and sends nothing.
- The Status Console and Journal state plainly that the answer came from an
  external model.

## Settled constraints (owner, 2026-10-18 - do not re-litigate)

1. **Audio never leaves the machine.** Only text is sent.
2. **One Gemma pass transcribes and sanitizes**, subject to the task 1 spike
   (the owner's reasoning: the raw voice is stored locally anyway, and one
   pass is faster than two). If the spike fails its frozen rule, the story
   re-plans to two steps (existing `TranscriptionService`, then a text-only
   sanitize pass); that is a stop-and-confirm event, not an automatic switch.
3. **A deterministic gate is the last step before sending.** It is blocking.
   A block names its reason.
4. **Sensitive topics come from a plain text file**, read by the sanitizer
   pass. A micro-editor in Settings is a later story.
5. **Send by default; dry-run exists for testing.**
6. **The answer is restored through Gemma, reasoning off.** The external
   answer passes through the local model to put the original details back with
   correct grammar (Russian cases).
7. **Single request in v1.** No multi-turn dialog with the external model.
8. **Output is `text_voice`.**

## Design decisions (proposed here, confirmed by card approval)

- **Pipeline, and where it lives.** `PersonalProxyService`, outside the turn
  lifecycle, mirroring `VoiceGuideService` (`dialog/voice_guide.py`): bus-free
  `iter_chat()` for both local Gemma passes, the app's playback path for
  speech. Stages: (1) sanitize pass on the audio, (2) outbound gate, (3)
  external request, (4) restoration pass, (5) present. `Orchestrator`'s turn
  state is not used (see Stop conditions).
- **Sanitize pass output is structured**, never free text:
  `verdict` (`send` or `refuse` with a reason), `sanitized_text`,
  `mapping` (placeholder to original value), and `raw_transcript`.
  `raw_transcript` is always returned, not only in dry-run, so the failure mode
  "the model misheard" can be told from "the model heard and did not replace".
  It stays local (journal only). A parse failure or an invalid structure is a
  fail-closed refusal, never a retry loop and never a send.
- **Typed placeholders, stable in the request.** `<PERSON_1>`, `<ORG_2>`, and
  so on: the type is kept so the external model can still reason; the same
  entity gets the same placeholder within the request. A whole-request
  sensitive topic (from the topics file) is a `refuse` verdict, not a clean-up
  attempt: removing the topic would remove the meaning.
- **Gate scope is the whole outbound payload**, not only the cleaned
  utterance: system prompt, any added text, every message. All outbound
  requests are built through one function, and the gate runs on its output
  (a single chokepoint, as in story-v2.0 task 2). Checks: (a) deterministic
  patterns for emails, phone numbers, payment card numbers (Luhn), IBAN,
  long digit runs, API-key-like and password-like strings, street-address
  shapes; (b) the exact-and-stem check of every original value in `mapping`
  against the payload, which catches "declared a replacement, did not make
  it"; (c) the topics-file text must not appear in the payload. It cannot
  catch a sensitive entity that the sanitizer neither mapped nor matched by
  pattern; that limit is documented, not hidden.
- **A block reports category and position, not the value**, so logs, the
  Journal, and the Status Console never become a store of the secrets the gate
  found. The user hears and sees the category ("a phone-number pattern was
  found at the request, nothing was sent").
- **The topics file is local-only.** It may itself be sensitive. Its text
  goes into the local sanitize prompt and nowhere else; check (c) above
  enforces that.
- **Restoration pass.** Applied only to sentences of the external answer that
  contain a placeholder; other sentences go to presentation immediately, with
  no extra model call. Gemma gets the sentence and the mapping, reasoning off.
  Validation is deterministic: no placeholder text remains, and every
  restored value appears in the sentence. If validation fails, fall back to
  plain substitution of the original value (grammatically rough, content
  intact) and mark the sentence as such in metadata. A placeholder split
  across streamed chunks is handled by buffering to sentence boundaries,
  reusing the sentence buffer.
- **Nothing but the sanitized request goes out.** No screenshots or images,
  no journal or memory retrieval, no annotations, no history, no text that
  arrived through `--mcp-mode` (that text is another assistant's claim and is
  never sent onward, per `PROJECT.md`). A test enumerates the outbound builder
  inputs and fails if a new source appears.
- **External client.** A small client for an OpenAI-compatible chat endpoint
  (URL and model in a config section `[personal_proxy]`), key from an
  environment variable (name in config, never the key), a timeout, and typed
  errors. The key, the payload, and the response body are never logged
  (the existing request log, `core/model_request_log.py`, is not extended to
  this path).
- **Locality and labeling.** A turn answered externally reports
  `DataLocality.EXTERNAL` (`ui/contract.py`, already defined for this) and the
  Status Console shows it. Every other mode continues to report `LOCAL`. The
  capability is off by default and turned on only by the explicit launch flag
  plus a configured endpoint.
- **Launch flag, not a setting.** `--personal-proxy`, mirroring `--mcp-mode`:
  an explicit per-run act, no persistent state that could silently re-enable
  external egress after a restart. Switching modes needs a restart. (Confirmed
  by the owner, 2026-10-18.)
- **Journal shape.** The raw voice, `raw_transcript`, the sanitized request,
  the verdict, and the restored answer are journaled. The external answer is
  recorded with a non-Jarvis provenance that excludes it from automatic
  retrieval and labels it as an external model's answer in `search_history`,
  reusing the v2.0 `EXTERNAL_CANVAS` machinery (task 8 decides whether this is
  the same kind or a sibling kind, and records why). The `mapping` is not
  stored separately: its originals already exist in the local transcript, and a
  second copy would only widen the surface.

## Honest limits (carried into docs and UI wording)

- The sanitizer and the gate reduce the chance of leaking; they do not prove
  absence. Quasi-identifiers (a combination of harmless facts that identify
  someone) are not detectable by either.
- What the external provider does with the cleaned text (retention, training)
  is outside Jarvis's control.
- Topic-level sensitivity cannot be removed without losing meaning; for it the
  only honest outcome is `refuse`.
- Speech recognition errors on names can make a name unrecognizable as a name;
  the dry-run output exists to measure this.

## Boundaries (explicitly out of scope)

- Multi-turn dialog with the external model, history in the outbound request.
- Images, screenshots, camera, files, tools, or MCP tools in the outbound
  request.
- The Settings micro-editor for the topics file.
- The secret-storage mechanism (`tasks/backlog/secret-storage.md`).
- Fallback from a blocked request to a local answer.
- Switching modes without a restart.
- Any change to mode 1/2/3 or `--mcp-mode` behavior.
- Selecting among several external providers.

## Task-card sequence

1. **Spike: combined transcription and sanitization on Gemma.** (Size: M.)
   Human-run measurement, with a corpus the owner records (Russian utterances
   containing names, numbers, addresses, organizations, plus utterances with
   none) and labels. Compares the combined pass against the two-step baseline
   (existing `TranscriptionService`, then a text sanitize pass) on: sensitive
   span recall, damage to non-sensitive words, structured-output validity rate,
   restoration-pass correctness on Russian cases, and latency. The decision
   rule and thresholds are frozen in the spike card before the run (precedent:
   `spike-single-pass-tts-block.md`). Output: a recorded decision (combined,
   or two-step) in `PROJECT.md`. Boundary: no production code except the
   measurement script under `manual/` and its pure-logic scoring helpers.

2. **Locality contract and capability.** (Size: S-M.) Amend the runtime
   locality contract in `PROJECT.md` with the external-inference capability
   (explicit, off by default, reported on the data-source axis). Add the
   `[personal_proxy]` config section (endpoint, model, key env var name,
   dry-run flag, topics file path, timeouts) with parsing and validation; the
   `--personal-proxy` flag in `parse_args()` (`app.py`); `DataLocality.EXTERNAL`
   wiring to the transport and Status Console. Boundary: no pipeline.

3. **Outbound gate.** (Size: M.) Pure logic: the single outbound-payload
   builder and the deterministic gate (patterns, Luhn, mapping original and
   stem check, topics-text check), blocking results with category and
   position. Fully unit-tested with fixtures. Boundary: no model, no HTTP.

4. **Sanitize pass.** (Size: M.) The profile and prompt (a new generation
   profile beside `voice_guide`, reasoning off), the topics file loader, the
   structured-output parser and validator, verdict handling, fail-closed on any
   malformed output. Tested with a fake backend. Shape follows task 1's
   decision. Boundary: no external client, no restoration.

5. **External client.** (Size: S-M.) The OpenAI-compatible request/response
   code, key from the environment variable, timeout, typed errors, nothing
   logged. Tested against a loopback fake HTTP server (CI-safe; no real
   network, no secrets). Boundary: no pipeline.

6. **Restoration pass.** (Size: M.) Placeholder detection, per-sentence
   restoration through the local model, deterministic validation, the
   substitution fallback with the metadata mark, sentence-boundary buffering.
   Tested with a fake backend. Boundary: no external client.

7. **Pipeline composition and dry-run.** (Size: M-L.) `PersonalProxyService`
   wiring tasks 3-6 behind `--personal-proxy`; mic input as in normal mode;
   `text_voice` presentation; dry-run showing raw transcript, sanitized text,
   mapping, verdict, gate result, and the exact payload; block feedback spoken
   and shown. The card lists every `HotkeySettings` field and says bound or
   not. Tested with fakes end to end. Boundary: no journal changes.

8. **Journal, provenance, and Status Console surfaces.** (Size: M.)
   Journal events for the request/answer pair with external provenance
   (automatic-retrieval exclusion enforced at the existing single chokepoint,
   `select_automatic_retrieval_passages()`), `search_history` labeling, fork
   behavior, Status Console state (mode, locality label, dry-run indicator,
   last block reason). Boundary: no new Journal features.

9. **Refactoring and optimization sweep.** (Size: S-M.) Behavior-preserving
   consolidation of this story's code and tests. Boundary: this story's code
   only.

10. **Docs and release verification.** (Size: M.) `PROJECT.md`: architecture
    section for v2.1.0 and the spike decision. Renumber the roadmap's "v2.1 -
    Canvas-guided voice" section. User-facing setup: the endpoint, the key
    environment variable, the topics file. A human-run handoff per the Testing
    protocol (self-sufficient, with every hotkey/config key/command named with
    a source reference): dry-run on the spike corpus, a real send, a block
    case for each gate category, a refusal on a topics-file topic, restoration
    on Russian cases, and the Journal/Status Console labels. A recall report
    on the labeled corpus is part of the handoff output. Gates:
    `python -m pytest`, `ruff check`, `ruff format --check`, and
    `tools/check_handoff_self_sufficiency.py`.

## Acceptance criteria

- [ ] The spike's frozen rule produced a recorded decision (combined or
      two-step) in `PROJECT.md`. (Task 1.)
- [ ] The locality contract names the external-inference capability; with it
      off (default) the runtime is byte-identical to v2.0 behavior; a turn
      answered externally reports `DataLocality.EXTERNAL`. (Task 2.)
- [ ] Every outbound request goes through one builder and the gate; a unit
      test fails if a new input source reaches the builder. A block names its
      category and position and never contains the value. (Task 3.)
- [ ] A malformed or unparseable sanitize result sends nothing. A topics-file
      match produces `refuse`. (Task 4.)
- [ ] The API key is read only from the environment; it, the payload, and the
      response body never appear in logs or events. (Task 5.)
- [ ] The restoration pass touches only sentences with placeholders, and a
      failed validation falls back to substitution with the mark. (Task 6.)
- [ ] With dry-run on, nothing is sent and the full intermediate state is
      shown; with it off, the cleaned request is sent and the restored answer
      is presented in `text_voice`. No audio, image, history, memory, or
      `--mcp-mode` text is ever in the payload. (Task 7.)
- [ ] The external answer is journaled with external provenance, excluded
      from automatic retrieval, and labeled in search and in the Status
      Console. (Task 8.)
- [ ] The sweep leaves the suite green. (Task 9.)
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green;
      the end-to-end check and the recall report are a prepared,
      self-sufficient human-run handoff; docs state the honest limits.
      (Task 10.)

## Stop conditions

- Stop if the task 1 spike fails its frozen rule: re-plan to the two-step
  shape and confirm with the owner (0.4). Do not switch silently.
- Stop if the outbound payload cannot be built at a single chokepoint, so
  that the gate would need to be applied at several call sites (0.3).
- Stop if the pipeline turns out to need `Orchestrator`'s turn state, the same
  shape problem as story-v2.0 task 3 (0.3, 0.4).
- Stop if the restoration pass alters the external answer beyond restoring the
  details (validation cannot detect the change) in the task 1 or task 6 runs:
  the "through Gemma" decision then needs revisiting with the owner.
- Stop if recall on the labeled corpus is too low for the owner to accept the
  mode as a default-capable feature; that is a product decision, not a tuning
  loop (0.7).
- Stop if any path is found by which journal, memory, or retrieval text can
  reach the outbound builder without passing the gate (a confirmed leak path
  is fixed in the current task, never deferred).
