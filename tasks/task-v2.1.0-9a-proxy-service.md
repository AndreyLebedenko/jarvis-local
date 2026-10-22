# Task v2.1.0-9a: PersonalProxyService (pipeline composition, dry-run)

Status: Open.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 9 (split by the owner on 2026-10-22 into
9a, this card, and 9b, the application wiring), and "Revisions of 2026-10-19" item 2.
Diagram: `docs/architecture/personal-proxy-sequence.puml`. Follows tasks 1-8 (all stages
exist behind small interfaces) and uses the notes of `tasks/done/task-v2.1.0-8-confirmation-exchange.md`
("Notes for later tasks") and of tasks 4-7.

## Summary

`PersonalProxyService` composes the stages into one pipeline for one request at a time:
input (an utterance or typed text) -> speech guard and transcription -> transcript check ->
sanitize -> (confirmation when there is a doubt) -> payload and gate -> dry-run stop or the
external request -> restoration -> presentation. It is plain asyncio logic over ports and
injected stage callables, so a complete run is tested with fakes. It does not touch
`app.py`, the `Orchestrator`, the microphone loop, the Journal, the UI or any setting.
9b connects it to the application.

## Boundary

New code in `src/jarvis/personal_proxy/`. Reuse every earlier stage as it is; wrap, never
copy. No `app.py`, `run_mode.py`, transport, JS, UI-string or config change (9b). No
Journal (task 10). No live call by the agent. The real adapters (microphone gate,
speaker over `ReplayPlayer`, chat sink over the transport, Whisper engine, local and
external backends) are 9b; here they are protocols and fakes.

## Owner decisions (2026-10-22)

1. Split into 9a (this) and 9b.
2. Presentation: each restored sentence is shown in the chat and spoken verbatim as it
   arrives; no paraphrasing pass (it can be a later task). Markdown or lists in the answer
   are spoken as written; the `<speak>`/`<lang>` control tags of the speech layer must not be
   interpreted: see "Presentation".
3. From task 8: every utterance and typed message is a request to the proxy; while a
   question is pending the next item is the answer; chat blocks go through a `ChatSink` port
   (transient in 9b, persisted in task 10); the `interrupt` hotkey during a question means "no".

## Design

**Stages as injected callables** (`PipelineStages`, a frozen dataclass of async/sync
callables with the signatures of the existing stages, each bound by 9b with its settings
and backends): `transcribe(clip) -> Transcription | NoSpeech` (the guarded stage of task 3),
`check(transcription, clip) -> CheckedTranscript` (task 4), `sanitize(checked) ->
SanitizeResult | SanitizeFailure` (task 5), `gate(payload, context) -> GateResult` (task 2),
`open_stream(payload) -> AsyncIterator[str]` (task 6, the `ExternalClient.stream`),
`restore(deltas, mapping) -> AsyncIterator[RestoredSentence]` (task 7), `warm_up()`.
Tests pass fakes. The service imports no backend, no engine, no `httpx`.

**Ports** (new, beside the task 8 ports): `AnswerSpeaker.speak(text, language) ->
SpeechResult` and `stop()` (the exchange's `ExchangeSpeaker` is the same shape; one protocol
may serve both), `MicrophoneGate` (task 8), `ChatSink.post(block)` extended to the new
blocks, `LocalityReporter` (task 1), a `language()` provider, a clock seam where needed.

**Router and worker.** `submit(item)` only enqueues into the `ProxyInbox` (task 8) and returns
at once. A router task reads the inbox: while a confirmation exchange is active every item is
an answer attempt (typed text -> `submit_typed`, an utterance -> `submit_spoken`); an attempt
the exchange rejects is dropped, never turned into a request. Otherwise the item goes to a
bounded FIFO of requests (a full FIFO drops the item with a notice block: "busy"). One
worker task takes requests one at a time, so there is never more than one external request
at a time and the locality seam (not safe for overlapping scopes) is safe.

**Request flow (worker), fail closed everywhere.**
1. Typed text: no speech stage and no check; it is user-authored: `CheckedTranscript` with no
   doubts (a small factory for typed text), source marked typed. Utterance: WAV bytes to a
   float32 mono 16 kHz clip (a pure helper, `soundfile`), `transcribe`; `NoSpeech` or an empty
   text posts a notice block ("no speech heard") and ends the request; otherwise `check`.
2. `sanitize(checked)`. A `SanitizeFailure` posts a notice (the failure class, no content) and
   ends the request. A `refuse` verdict posts a notice with the refusal reason (local chat
   only) and ends it.
3. `HeardBlock` always goes to the chat: with a doubt (`should_ask`) the exchange posts it and
   asks; without one the service posts it with `SEND_WITHOUT_QUESTION`. A request whose
   outcome is anything but `CONFIRMED` posts the offer text (task 8), spoken and shown, and
   ends: nothing is built or sent. An empty heard text is never sent.
4. Payload: `build_outbound_payload(DEFAULT_SYSTEM_PROMPT, sanitized_text)` (`payload.py`) and
   the gate with a `GateContext(mapping, topics_text)`. A block posts a notice with the
   categories and positions (never a value), spoken and shown, and ends the request.
5. Dry run (`settings.dry_run`): post a `DryRunBlock` with the full intermediate state (the
   Whisper text, the checked text, the doubts and whether it would ask, the sanitized text,
   the mapping, the verdict, the gate result, the exact payload messages) and stop. It is
   shown in the chat only; it holds personal values and is never logged or spoken beyond a
   short fixed sentence ("dry run, nothing was sent").
6. Send: post the `SentBlock` built from the payload object, then open the stream under
   `external_locality(reporter)` (EXTERNAL from the first byte request to the end of the
   stream or an error; restoration and speech after the stream are local). `restore(...)`
   consumes the stream. Each `RestoredSentence` is posted as an answer block and spoken
   verbatim, one at a time, in order; the microphone is paused for the whole answer speech
   and resumed after it (the gate adapter does the cooldown). A stream or restoration
   exception posts a notice ("the answer is incomplete"; already shown sentences stay) and
   ends the request.
7. Any other exception inside a request posts a content-free "internal error" notice, the
   worker continues with the next request; `CancelledError` always propagates.

**Presentation.** The answer block carries the sentence text and the restoration method
(`PASSTHROUGH`, `MODEL`, `SUBSTITUTED`, plus the unresolved flag) so the UI can mark rough
sentences. Before speaking, a sentence has the speech layer's control tags (`<speak>`,
`<lang ...>` and their closers) removed so that external text cannot steer the speech
markup; nothing else is changed. A muted TTS (`DISABLED`) means text only.

**Interrupt.** `interrupt()` (called by the hotkey adapter in 9b, on the loop): cancels a
pending exchange (it ends as `CANCELLED`); otherwise cancels the in-flight request task
(nothing is sent if the stream was not opened; an open stream is closed and the answer
speech stopped) and posts a notice. It never raises.

**Lifecycle.** `start()` starts the router and worker; `close()` is idempotent, cancels both,
cancels a pending exchange, stops the speaker, resumes the microphone if paused, and waits for
the tasks. `warm_up()` calls the injected warm-up once before the first request and may be
called by 9b earlier.

**Texts.** All fixed user-facing strings (notices, spoken block feedback, dry-run sentence)
in Russian and English by the `language` provider, in one module, with a test that both
catalogs have the same keys. No f-string of anything but a category name or an enum value.

**Privacy and logging.** Nothing derived from the transcript, mapping, payload, answer or
notice details in logs, exceptions, `repr` or `str`; blocks' text is hidden in `repr`. The
service writes no log line at all except through typed notice blocks (a `caplog` test).

## Required behavior

1. `PersonalProxyService` with the design above; blocks `NoticeBlock(kind, detail)`
   (enum kinds and an enum/int detail, never content), `DryRunBlock`, `AnswerBlock`, and the
   union accepted by `ChatSink`; the typed-text `CheckedTranscript` factory; the clip helper;
   the control-tag stripper; the texts module.
2. The invariants, each with a test: (a) nothing reaches `open_stream` unless the gate allowed
   the exact payload that is sent (the stream receives the same object that was gated);
   (b) the payload holds only `DEFAULT_SYSTEM_PROMPT` and the sanitized text (assert
   `payload.to_chat_messages()`), never the heard text, the mapping originals, audio or the
   Whisper text; (c) the `SentBlock` equals the payload; (d) only `CONFIRMED` (or no doubt)
   leads to a payload; (e) dry run sends nothing and posts the full state; (f) the locality is
   EXTERNAL during the stream and LOCAL after it on every path, including errors and
   cancellation; (g) never two external requests at once (two queued requests run in order);
   (h) every stage failure posts a notice and sends nothing.
3. Tests with fakes, end to end (pure logic, no sleeping; use seams): voice request without a
   doubt sent and answered; voice with a doubt then yes / no / unclear / timeout / typed yes /
   interrupt; typed request; no speech; empty transcript; topics refusal; malformed sanitize;
   gate block (phone number in the sanitized text); dry run; external error before and during
   the stream; restoration fallback sentences; unresolved placeholder; items arriving during
   an exchange and during a request; full FIFO; `close()` during a request; interrupt before
   and after the stream opened; microphone paused and resumed around the answer speech and
   resumed on every failure; control tags stripped; both languages; `caplog` empty.

Out of scope: `app.py`, `RunMode`, transport and JS, hotkey binding, the real adapters, the
Journal, startup validation, model warm-up of the real backends, persistence of the blocks.

## Acceptance criteria

- [ ] A complete run from an utterance to the spoken answer works with fakes for every stage,
      with the invariants (a)-(h) tested.
- [ ] Every failure path posts a content-free notice and sends nothing; cancellation
      propagates; the worker survives an internal error.
- [ ] One external request at a time; the locality is EXTERNAL only around the external
      stream.
- [ ] Dry run posts the full intermediate state, sends nothing, and the details are never
      logged.
- [ ] The payload holds only the fixed system prompt and the sanitized text.
- [ ] No `app.py`, `Orchestrator`, microphone loop, Journal, UI or setting change; no log
      line from the service.
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green.
