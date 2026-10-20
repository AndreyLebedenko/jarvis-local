# Story v2.1.0: Personal proxy (external model behind a local sensitive-data gate)

**Status:** Approved by the owner, 2026-10-18 (including `--personal-proxy`
as a launch flag); pipeline and interaction revised by the owner, 2026-10-19
(see "Revisions of 2026-10-19"). No task card is started; the task-card
sequence was re-cut on 2026-10-19.
**Created:** 2026-10-18
**Updated:** 2026-10-20
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

## Revisions of 2026-10-19 (owner, after spikes 1-10)

The 2026-10-18 text of this card is kept as written; where this section differs
from it, this section wins. The task-card sequence, the acceptance
criteria, and the stop conditions below were re-cut on 2026-10-19.

1. **Pipeline (settled constraint 2 is superseded).** The task 1 stop
   condition fired: the bare Gemma transcription and the combined pass did not
   meet their frozen rules (`tasks/done/spike-v2.1.0-1-combined-transcribe-sanitize.md`
   to `tasks/done/spike-v2.1.0-4-speech-present.md`). The owner decided to put a
   dedicated engine first: speech-to-text (Whisper large-v3-turbo through
   faster-whisper, on the GPU, `language="ru"`), then a local Gemma check of the
   transcript against the recording (a corrected transcript, then a judge that
   lists the doubtful fragments), then a text-only sanitize pass, the outbound
   gate, the external request, and restoration. Measured facts (spikes
   v2.1.0-5 to -10): Whisper has 4 failures of 88 and span fidelity 0.854
   (bare Gemma: 22 and 0.792); GigaAM v3 is rejected on fidelity 0.708; Whisper
   fits the GPU next to `gemma4:12b` (INT4, 7.6 GB) at `num_ctx` 8192 with no
   swap cost (about 12.7 GB used of 16.3); Gemma with the recording repairs
   spoken e-mail addresses and some digits but sometimes rewrites (it invented an
   address, it translated a request), and the temperature from 0 to 1 does not
   change that; silence and noise are separated by no confidence signal and
   need a guard before the engine.
2. **Interaction (owner's design).** In `text_voice`: (a) the chat always
   records what the engine heard, whole and without placeholders, and what it
   decided; (b) when there is a reason to doubt, a separate Text+Voice exchange
   asks for confirmation: the text shows the whole heard transcript, the voice
   names what to check; (c) with no reason to doubt, the request is sent without a
   question (settled constraint 5 stands: send by default); (d) a separate block
   in the chat always records exactly what went out. The ask budget is about 1
   request in 4 for sensitive and complex requests. Fail-closed: no answer
   within the timeout, an unclear answer, or "no" sends nothing and offers to
   correct by text or to dictate again; only a clear "yes", spoken or typed, sends.
3. **Where values may live (amends the design decision "A block reports category
   and position, not the value, so logs, the Journal, and the Status Console never
   become a store of the secrets the gate found").** The chat journal holds the
   heard text whole: it is the user's own words, and what the user chooses to
   record is theirs. The logs hold only what goes out, with placeholders. The
   gate's block messages and the Status Console keep reporting the category and
   the position without the value.
4. **Doubt trigger (a candidate, not frozen).** From spike v2.1.0-10: the judge's
   list of doubtful fragments for one Gemma sample asks on 13 of 60 sensitive
   recordings (22%), covers 7 of 7 real errors, and names the wrong fragment in
   5 of 7; the disagreement of six samples and Whisper's word probabilities add
   little. The evidence is thin (7 errors, one phrase in three voices); the
   trigger and its threshold are confirmed in the task that builds the pipeline,
   with a labeled evaluation in its handoff.
5. **Consequences for the task cards (applied in the re-cut of 2026-10-19):** task 1 is
   done as spikes v2.1.0-1 to -10; a new task for the speech-to-text and check
   stage (a new runtime dependency set with its CI and locality statement, the
   GPU memory budget, a speech-presence guard before the engine); task 4 becomes
   the text-only sanitize pass; a new task for the confirmation exchange (state,
   timeout, spoken and typed answers); task 7 composes the new stages; task 2 adds
   the new config fields; task 10 records all of this in `PROJECT.md`.

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

Re-cut on 2026-10-19 after spikes v2.1.0-1 to -10 (see "Revisions of 2026-10-19").
Tasks 2, 6, 7, and 11 are the 2026-10-18 tasks 3, 5, 6, and 9 unchanged; the
others are changed or new. Cards for tasks 1-12 do not exist yet.

0. **Spikes (done).** The old task 1 is replaced by the records
   `tasks/done/spike-v2.1.0-1-*` to `tasks/done/spike-v2.1.0-10-ask-policy.md`. **Spike
   v2.1.0-11 (Size: S, before task 5):** measure the text-only sanitize pass on
   `gemma4:12b` INT4 at `num_ctx` 8192, on the Whisper transcripts and checked
   transcripts of both recorded corpora (span recall, damage to non-sensitive
   words, structured-output validity), with the rule frozen in its card before the
   run. Offline harness under `manual/`; no production code. **Done 2026-10-20:**
   go with one accepted deviation (false refusals 23.5% against the 15% limit;
   the owner accepted it); see `tasks/done/spike-v2.1.0-11-text-sanitize.md`.

1. **Locality contract, capability, and config.** (Size: S-M. Done 2026-10-20, `tasks/done/task-v2.1.0-1-locality-and-config.md`.) Amend the runtime
   locality contract in `PROJECT.md` with the external-inference capability
   (explicit, off by default, reported on the data-source axis). Add the
   `[personal_proxy]` config section (endpoint, model, key env var name,
   dry-run flag, topics file path, timeouts) and the settings of the new stages:
   speech-to-text engine (model, device, language), the weak-word probability
   (0.5), the confirmation timeout, the doubt trigger threshold. The
   `--personal-proxy` flag in `parse_args()` (`app.py`); `DataLocality.EXTERNAL`
   wiring to the transport and Status Console. Boundary: no pipeline.

2. **Outbound gate.** (Size: M.) Pure logic: the single outbound-payload builder
   and the deterministic gate (patterns, Luhn, mapping original and stem check,
   topics-text check), blocking results with category and position. Fully
   unit-tested with fixtures. Boundary: no model, no HTTP.

3. **Speech-to-text stage.** (Size: M-L.) A Whisper large-v3-turbo engine
   (faster-whisper, GPU `float16`, `language="ru"`, beam 5, no built-in VAD) behind
   a small protocol, returning the text, every word with its probability, and the
   segments' `avg_logprob`, `no_speech_prob`, and `compression_ratio`. The
   dependencies live in an optional `requirements-stt.txt` with lazy imports; the
   main `requirements.txt` and CI are unchanged and tests use a fake engine. A
   one-time weights setup script mirroring `setup_tts_model.py` (needs the
   network once; the runtime stays offline). A speech-presence guard before the
   engine so that silence and noise never reach it (spike 8: no confidence
   signal separates them; Whisper invents text on them). Boundary: no Gemma, no
   pipeline.

4. **Transcript check stage.** (Size: M.) Promote the spike code to `src/`: the
   Gemma sample (the recording, the transcript with `[?]` after words under the
   probability threshold, the error hint, `gemma4:12b`, `num_ctx` 8192,
   temperature 0.618) and the judge (constrained JSON: the uncertain fragments;
   the confidence number is not used), producing the checked transcript and the
   doubt list. A parse or call failure falls back to the Whisper text plus a
   doubt, never a retry loop and never a send. Tested with a fake backend.
   Boundary: no sanitization.

5. **Sanitize pass (text only).** (Size: M.) The profile and prompt (a new
   generation profile beside `voice_guide`, reasoning off), the topics file loader,
   the structured-output parser and validator (`verdict`, `sanitized_text`,
   `mapping`), verdict handling, fail-closed on any malformed output. Its input is
   the checked transcript. The shape follows spike v2.1.0-11. Tested with a fake
   backend. Boundary: no external client, no restoration.

6. **External client.** (Size: S-M.) The OpenAI-compatible request/response code,
   key from the environment variable, timeout, typed errors, nothing logged.
   Tested against a loopback fake HTTP server (CI-safe; no real network, no
   secrets). Boundary: no pipeline.

7. **Restoration pass.** (Size: M.) Placeholder detection, per-sentence
   restoration through the local model, deterministic validation, the
   substitution fallback with the metadata mark, sentence-boundary buffering.
   Tested with a fake backend. Boundary: no external client.

8. **Confirmation exchange.** (Size: L.) **Starts with a short design card**
   answering who listens for the answer while `PersonalProxyService` lives outside
   the turn lifecycle, and how a spoken "yes" is kept apart from ordinary input
   (stop condition below). Then: the decision to ask (the doubt trigger of
   spike v2.1.0-10, confirmed with a labeled evaluation), a small state machine,
   the Text+Voice exchange (the whole heard text in the chat; the voice names the
   doubts), answers spoken or typed, the timeout, fail-closed (only a clear "yes"
   sends; no answer, unclear, or "no" sends nothing and offers to correct by text
   or dictate again), and the two chat blocks: what was heard and decided, and
   exactly what went out. The card lists every `HotkeySettings` field and says
   bound or not. Tested with fakes. Boundary: no journal changes.

9. **Pipeline composition and dry-run.** (Size: M-L.) `PersonalProxyService`
   wiring tasks 2-8 behind `--personal-proxy`; mic input as in normal mode;
   `text_voice` presentation; dry-run showing the Whisper text, the checked
   transcript, the doubts and whether it would ask, the sanitized text, the
   mapping, the verdict, the gate result, and the exact payload; block feedback
   spoken and shown. Tested with fakes end to end. Boundary: no journal changes.
   Calls the locality seam of task 1 (`personal_proxy/locality.py`,
   `external_locality`), which is not safe for nested or overlapping turns (an
   inner exit sets `LOCAL` under an active outer scope): the turn lifecycle here
   must keep one external turn at a time, or the seam must be reworked.

10. **Journal, provenance, and Status Console surfaces.** (Size: M.) Journal
    events for the request/answer pair with external provenance
    (automatic-retrieval exclusion enforced at the existing single chokepoint,
    `select_automatic_retrieval_passages()`), `search_history` labeling, fork
    behavior, Status Console state (mode, locality label, dry-run indicator,
    last block reason). The chat journal holds the heard text whole; the logs hold
    only what goes out, with placeholders (a test that the logs never contain the
    heard text). Boundary: no new Journal features.

11. **Refactoring and optimization sweep.** (Size: S-M.) Behavior-preserving
    consolidation of this story's code and tests. Boundary: this story's code
    only.

12. **Docs and release verification.** (Size: M.) `PROJECT.md`: architecture
    section for v2.1.0 (the spike facts are already recorded there). Renumber the
    roadmap's "v2.1 - Canvas-guided voice" section. User-facing setup: the
    endpoint, the key environment variable, the topics file, the optional
    speech-to-text dependencies and the weights setup. A human-run handoff per the
    Testing protocol (self-sufficient, with every hotkey/config key/command named
    with a source reference): dry-run on the recorded corpora, a real send, a block
    case for each gate category, a refusal on a topics-file topic, restoration on
    Russian cases, a request that makes the system ask (yes, no, timeout), silence
    that sends nothing, and the Journal/Status Console labels. A recall report on
    the labeled corpora is part of the handoff output. Gates: `python -m pytest`,
    `ruff check`, `ruff format --check`, and
    `tools/check_handoff_self_sufficiency.py`.

## Acceptance criteria

- [x] The spike records and the decision (a dedicated engine first) are in
      `PROJECT.md` (done 2026-10-19); the text-only sanitize pass on INT4 has a
      recorded result (done 2026-10-20). (Spike v2.1.0-11.)
- [x] The locality contract names the external-inference capability; with it off
      (default) the runtime is byte-identical to v2.0 behavior; the seam for
      reporting a turn as `DataLocality.EXTERNAL` exists (done 2026-10-20; the
      call is wired by task 9). (Task 1.)
- [ ] Every outbound request goes through one builder and the gate; a unit test
      fails if a new input source reaches the builder. A block names its category
      and position and never contains the value. (Task 2.)
- [ ] The speech-to-text stage returns word probabilities; silence and noise do
      not reach the engine or the checker; without the optional dependencies the
      main runtime and CI are unchanged. (Task 3.)
- [ ] The check stage returns a checked transcript and a doubt list; any failure
      falls back to the Whisper text with a doubt and sends nothing by itself.
      (Task 4.)
- [ ] A malformed or unparseable sanitize result sends nothing. A topics-file
      match produces `refuse`. (Task 5.)
- [ ] The API key is read only from the environment; it, the payload, and the
      response body never appear in logs or events. (Task 6.)
- [ ] The restoration pass touches only sentences with placeholders, and a failed
      validation falls back to substitution with the mark. (Task 7.)
- [ ] With a doubt, the exchange shows the whole heard text and names the doubts
      by voice; only a clear "yes", spoken or typed, sends; no answer, unclear
      answer, or "no" sends nothing; without a doubt the request is sent without a
      question; the "went out" block equals the actual payload (a test). (Task 8.)
- [ ] With dry-run on, nothing is sent and the full intermediate state is shown;
      with it off, the cleaned request is sent and the restored answer is
      presented in `text_voice`. No audio, image, history, memory, or `--mcp-mode`
      text is ever in the payload. (Task 9.)
- [ ] The external answer is journaled with external provenance, excluded from
      automatic retrieval, and labeled in search and in the Status Console; the
      logs never contain the heard text. (Task 10.)
- [ ] The sweep leaves the suite green. (Task 11.)
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green; the
      end-to-end check and the recall report are a prepared, self-sufficient
      human-run handoff; docs state the honest limits. (Task 12.)

## Stop conditions

- Stop if the outbound payload cannot be built at a single chokepoint, so that
  the gate would need to be applied at several call sites (0.3).
- Stop if the pipeline turns out to need `Orchestrator`'s turn state, the same
  shape problem as story-v2.0 task 3 (0.3, 0.4).
- Stop if the confirmation exchange needs the `Orchestrator` turn state or blocks
  the microphone loop, or a spoken "yes" cannot be kept apart from ordinary input
  (task 8's design card; 0.3, 0.4).
- Stop if the speech-to-text dependencies cannot be kept out of the main
  `requirements.txt` and out of CI (0.9).
- Stop if the spike v2.1.0-11 text-only sanitize pass on INT4 fails its frozen
  rule: the model or the pass shape is a product decision, not a tuning loop
  (0.4, 0.7).
- Stop if the restoration pass alters the external answer beyond restoring the
  details (validation cannot detect the change): the "through Gemma" decision then
  needs revisiting with the owner.
- Stop if recall on the labeled corpora, or the share of requests that the system
  asks about (the owner's budget: about 1 in 4 for sensitive and complex requests),
  is not acceptable to the owner for the mode as a default-capable feature; that
  is a product decision, not a tuning loop (0.7).
- Stop if any path is found by which journal, memory, or retrieval text can reach
  the outbound builder without passing the gate (a confirmed leak path is fixed in
  the current task, never deferred).
