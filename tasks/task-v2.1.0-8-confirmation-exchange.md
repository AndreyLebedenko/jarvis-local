# Task v2.1.0-8: confirmation exchange (design card and implementation)

Status: Open.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 8 (Size: L), "Revisions of
2026-10-19" items 2 and 4, and the stop conditions on the exchange. Facts: spike
v2.1.0-10 (`tasks/done/spike-v2.1.0-10-ask-policy.md`), tasks 4 (`CheckedTranscript`,
`would_ask`, `Doubt`) and 6 (`OutboundPayload`) of this story, `PROJECT.md`
(echo and half-duplex rules, response modes). Task 9 composes this stage into
`PersonalProxyService`; task 10 persists the chat blocks.

## Summary

Before a request is sent, the user may be asked to confirm it. When the transcript check
found a reason to doubt, Jarvis shows the whole heard text, speaks what to check, and
waits for a clear "yes" (spoken or typed). Anything else sends nothing and offers to
correct by text or to dictate again. Without a doubt the request is sent without a
question. Two chat blocks always record what was heard and decided, and exactly what went
out.

This task builds the state machine, the answer classifier, the question and offer
texts, the blocks as data, and the ports to everything else, all tested with fakes. It
touches neither `Orchestrator` nor the microphone loop nor the Journal.

## Owner decisions (2026-10-22)

1. **Input in this mode.** Under `--personal-proxy` every utterance and every typed message
   is a request to the proxy; the local dialog does not answer (the `Orchestrator` is not
   subscribed to speech and the dock text goes to the proxy, task 9). While a question is
   pending, the next utterance or typed message is the answer, never a new request.
   Outside a pending question, "yes"/"no" are ordinary requests.
2. **Answer words.** Only an exact vocabulary counts (see "Answer classifier"); any extra word
   makes the answer unclear, which sends nothing.
3. **Chat blocks.** Typed data plus a `ChatSink` port, tested with a fake. Task 9 wires a
   temporary transient sink; task 10 does the Journal, provenance and rendering. This task
   does not change the Journal.
4. **Hotkey `interrupt` during a pending question means "no"** (the exchange is cancelled, nothing
   is sent). The other hotkeys are not used by this task.

## Design answers (the two questions the story asks this card)

**Who listens for the answer while `PersonalProxyService` lives outside the turn lifecycle?**
The service owns a `ProxyInbox`: its handlers on speech (`UtteranceChunk`) and on typed dock
text only enqueue and return at once (the event bus awaits every handler inline, so a
handler that did the work would stop the microphone loop; this is the stop condition and it
is avoided). A worker task of the service takes items from the inbox one at a time. When no
exchange is pending the item starts a request; when one is pending the item is delivered to
the exchange as the answer. A spoken answer is transcribed by the existing guarded
speech-to-text stage (task 3) and classified from the Whisper text alone (no Gemma check, no
sanitize). `Orchestrator` turn state is not used anywhere: the exchange has its own small
state and no `_busy`.

**How is a spoken "yes" kept apart from ordinary input?** By state, not by guessing: only an
utterance that arrives while the exchange is in the awaiting-answer state is read as an
answer, and it is consumed there (never also a request). It must consist entirely of
vocabulary words; anything else is "unclear" and sends nothing. Before the question is
spoken the microphone is paused and the answer window opens only after speech ends and the
microphone is live again, so the question is not heard as the answer (PROJECT.md: no echo
cancellation, half-duplex). A typed answer is accepted from the moment the block is posted.
Residual risks, stated plainly: Whisper's accuracy on one-word answers is not measured
(handoff A measures it), the answer arrives after the end-of-speech pause
(`[vad].request_end_pause_seconds`), and a misheard "yes" cannot be told from a real one,
which is why only the vocabulary words count and why the second block records exactly
what went out.

## `HotkeySettings` (src/jarvis/core/config.py), every field

All eight are bound by default. In this mode:

| field | default | role in this task |
|---|---|---|
| `screenshot_full` | `ctrl+alt+s` | not used; inert (nothing subscribes it in this mode, task 9) |
| `screenshot_region` | `ctrl+alt+r` | not used; inert |
| `shutdown` | `ctrl+alt+q` | unchanged; ends the app (the exchange is dropped, nothing sent) |
| `mic_sleep_toggle` | `ctrl+alt+m` | not used; with the microphone asleep only a typed answer is possible, the timeout applies |
| `clipboard_submit` | `ctrl+alt+v` | not used; inert in this mode |
| `thinking_toggle` | `ctrl+alt+t` | not used |
| `interrupt` | `ctrl+alt+i` | pending question = "no": `cancel()` ends the exchange, nothing is sent |
| `response_mode_toggle` | `ctrl+alt+o` | not used |

No new hotkey and no new setting key (the timeout is the existing
`confirmation_timeout_seconds`, the trigger threshold the existing `doubt_min_listed`).

## Boundary

New code in `src/jarvis/personal_proxy/`. Reuse `CheckedTranscript` and `Doubt`
(`check_result.py`), `OutboundPayload` (`payload.py`), `PersonalProxySettings`. No
`Orchestrator` or `app.py` change, no microphone-loop change, no Journal/provenance/search
change, no new Status Console block kind, no new HTTP route, no new setting. The real
speaker, microphone gate, chat sink and transcriber are task 9's adapters; here they are
protocols and fakes. No live call by the agent except as stated in the handoffs.

## Required behavior

1. **Answer classifier.** `classify_answer(text) -> AnswerKind` (`YES`, `NO`, `UNCLEAR`),
   pure. Normalization: case fold, `ё`→`е`, drop punctuation, collapse spaces. The whole
   normalized text must equal one phrase of a closed vocabulary (constants in one module,
   starting values): YES = `да`, `да отправляй`, `отправляй`, `отправь`, `давай`, `ок`,
   `окей`, `верно`, `подтверждаю`, `yes`, `send`, `send it`, `ok`, `okay`, `confirm`;
   NO = `нет`, `не надо`, `не отправляй`, `стоп`, `отмена`, `no`, `stop`, `cancel`,
   `dont send`. Everything else (including empty, "да нет", "да но исправь", a sentence
   containing a vocabulary word) is `UNCLEAR`. No model call.
2. **Exchange state machine.** States: `ASKING` (block posted, question being spoken),
   `AWAITING` (window open, timer running), `DONE`. `run(...)` returns an `ExchangeOutcome`:
   `CONFIRMED` (a YES), `DECLINED` (a NO), `UNCLEAR`, `TIMED_OUT`, `CANCELLED` (interrupt),
   `FAILED` (any other exception inside the exchange). Only `CONFIRMED` may lead to a send;
   every other outcome sends nothing. `CancelledError` of the surrounding task propagates
   unchanged.
3. **Order.** The heard block is posted first, then the question is spoken (a muted TTS is
   `DISABLED`: text-only, the window opens at once). The microphone is paused before speech and
   resumed after it (port `MicrophoneGate`); the window opens when `resume()` returns. The
   timeout (`confirmation_timeout_seconds`) runs from the window opening and also covers a
   typed answer that comes earlier. A typed answer during speech stops the speech and decides.
4. **One exchange at a time.** A second `run` while one is pending raises (the service
   serializes; tested). Items that arrive while pending are answers.
5. **Texts.** The shown question contains the whole heard text and the listed doubts; the
   spoken question names the doubts only (fragments, at most the first ones, capped) and says
   to answer yes or no. The offer after any outcome except `CONFIRMED` says nothing was
   sent and offers to correct by typing or to dictate again. Texts exist in Russian and
   English, chosen by the `language` the service passes (the app's `resolve_speech_language`
   result in task 9); fixed strings, no model call, no f-string of anything but the heard text
   and the fragments.
6. **Decision to ask.** `should_ask(checked, settings)` is `checked.would_ask` as task 4
   defines it (the judge listed at least `doubt_min_listed` doubts). A request without a doubt
   goes on without an exchange. Handoff B confirms the threshold.
7. **Blocks.** `HeardBlock(heard_text, doubts, decision)` and `SentBlock(text)`, frozen,
   built only from the transcript and the `OutboundPayload` (the sent text is taken from
   the payload object, so the block cannot differ from what goes out; a test asserts equality
   with `payload.messages`). Their `repr`/`str` hide the text. Posted through `ChatSink`;
   a failing sink is `FAILED`/not sent, never a send.
8. **`ProxyInbox`.** A small thread-safe-for-the-loop queue with `submit(item)` that only enqueues
   and returns at once, and `next_item()` for the service's worker. An item is typed text or
   an utterance (WAV bytes). The inbox knows nothing about the exchange; the service (task 9)
   routes the worker's item to the pending exchange or starts a request. A bounded size with
   a typed error when full (an item is dropped with a reported cause, never blocks `submit`).
9. **Privacy.** Nothing from the transcript, doubts, answers or blocks in logs, exceptions,
   `repr`; the answer text is not kept after classification.
10. Tests with fakes (pure logic): every classifier phrase and a set of near-misses (`да нет`,
   `да но`, `нет да`, `да, отправляй пожалуйста`, ``, punctuation, case, `ё`); each outcome;
   the typed and spoken paths; typed answer during speech; interrupt; the timeout (fake clock
   or short timeout); muted TTS; microphone paused before and resumed after speech even when
   speaking fails or is cancelled; the window not opening before `resume()` returns; sink or
   speaker raising; an answer arriving before the window opens counts only if typed; a second
   `run` raising; ordering of the calls (block, pause, speak, resume, wait); texts in both
   languages; no text in `repr`; the "sent" block equals the payload; `submit` returns at once with a slow worker and a
full inbox raises a typed error.

Out of scope: the real adapters (speaker over `ReplayPlayer`, microphone pause, transcription of the
answer, the chat sink, routing of dock text, `RunMode`), the pipeline, the Journal blocks,
retry loops (an unclear answer is not asked again), changing `would_ask`.

## Human-run handoffs

Both are prepared, not run, and self-sufficient per CLAUDE.md Testing protocol 4. The agent
runs them on the owner's request.

**A. Short answers through the real speech path.** The owner (or the agent on request, with
the owner at the microphone) says each of: `да`, `нет`, `отправляй`, `стоп`, `yes`, `no`,
`да, но исправь`, and a neutral phrase, ten times each, through the guarded speech-to-text stage
(task 3); the tool prints the Whisper text, the classification, the speech seconds and whether
the speech guard (`stt_min_speech_seconds` 0.3) rejected the clip. Question answered: how
reliably do one-word answers survive the guard and the engine? A speech-guard rejection or a
wrong text is an `UNCLEAR` (safe); the numbers decide whether the vocabulary needs more
variants.

**B. Doubt trigger on the production check stage.** Run the production transcript check (task 4)
over the 60 labeled recordings of spike v2.1.0-10 (the data section there) and compute, with
the labels and `WRONG_FRAGMENT_KEYS` of `manual/personal_proxy/ask_policy.py`: the asked share,
real errors covered, errors whose wrong fragment is named. Rule, frozen before the run
(2026-10-22): keep `doubt_min_listed = 1` if the asked share is at most 0.27 (the 25% budget
plus 2 points), covered errors at least 6 of 7, and at least 4 of 7 name the wrong fragment.
Otherwise the numbers go to the owner; the threshold is not tuned in a loop (stop condition).
Reuses the spike 8/9 harness where it can; no new corpus.

## Acceptance criteria

- [ ] `classify_answer` returns `YES` only for the closed vocabulary, `NO` likewise, `UNCLEAR`
      for everything else; a test lists the near-misses.
- [ ] Only `CONFIRMED` can lead to a send; every other outcome, every exception and a failing
      port send nothing; task cancellation propagates.
- [ ] The microphone is paused before the question and resumed after it in every path; the
      window and the timeout start after resume.
- [ ] The handlers' work stays out of the event bus: the service-side inbox only enqueues (a
      test of the inbox with a slow worker shows `submit` returns at once).
- [ ] The "sent" block equals the outbound payload; neither block shows in `repr` or logs.
- [ ] No `Orchestrator`, `app.py`, microphone loop, Journal or setting change.
- [ ] Handoffs A and B exist and are self-sufficient; B's rule is applied to measured numbers.
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green.
