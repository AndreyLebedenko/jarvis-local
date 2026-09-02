# Task: Reframe the voice turn's current-turn text to cut first-turn audio refusals

**Status:** Completed, re-scoped. Shipped as *make the voice turn's
current-turn text configurable and put it in the dialog language* - not as the
refusal fix it was written to be. **The card's original acceptance gate cannot
be met and this card does not fix the bug it was written for.** The owner's 2026-09-01/02 session, chasing the refusals this
card targets, measured the actual cause: the dialog request shape suppresses
the model's attention to attached audio, and the current-turn text is only one
of three independent suppressors - this exact shipped wording was heard 0/10
alone at n=10, where `DEFAULT_TRANSCRIPTION_INSTRUCTION` was 10/10
(`tasks/bug_reports/2026-09-01-request-shape-suppresses-audio-attention.md`).
No wording can pass a refusal-rate gate while the request shape holds, so the
handoff below is not runnable as an acceptance test for this card. What
survives is a mechanical, independently useful change (the wording is now a
tunable `[prompts]` key in the dialog language) and the measurement
infrastructure the session produced - both of which the request-shape fix will
use, so neither is worth holding behind it. The refusals themselves are now
tracked in
`tasks/bug_reports/2026-09-01-request-shape-suppresses-audio-attention.md`,
whose recommended direction (two-pass: transcribe in the bare shape that
already works, then answer the transcript as an ordinary text turn) gets its
own card.
**Origin bug report:** `tasks/bug_reports/2026-07-25-model-stopped-comprehending-voice-audio.md`
(see its "Sixth data point" and "Future considerations"). This card is the
"its own card" that report calls for.
**Executor:** Sonnet 5 High. This is a small, high-leverage prompt/framing
change with a probabilistic payoff, so its correctness gate is a **live
human-run session**, not the automated suite. The agent implements the change,
keeps the logic suite green, and prepares the handoff; it does NOT declare the
bug fixed - only the owner's session run can.

## The bug, in one paragraph

A voice turn attaches its wav to `messages[-1]["images"]` and sends the
placeholder text `[голосовое сообщение]` (`VOICE_PLACEHOLDER_TEXT`,
`src/jarvis/core/lifecycle.py:13`) as the current user turn. On a fresh session
the model sometimes answers "ваше голосовое сообщение не дошло / не было
преобразовано" - the "there was nothing in this audio" refusal - even though
the audio is intelligible. The 2026-09-01 data point proves this is framing,
not audio or plumbing: the exact same wav, transcribed via the transcription
instruction (`DEFAULT_TRANSCRIPTION_INSTRUCTION`,
`src/jarvis/journal/transcription.py`), returned a correct verbatim transcript
in the same run. A bracketed placeholder reads to the model like a caption for
an attachment that is not there; an explicit "listen and respond" instruction
reliably makes the model attend.

Scope of this card is the **first-turn** refusal only (current-turn framing).
The separate session-poisoning mechanism ("the model follows its own previous
refusal", confirmed in the report's third experiment) is explicitly OUT of
scope here - it needs the answer-based-drop option, a different and harder
change.

## Required reading before implementing

- The origin bug report in full, especially "Sixth data point", "Third
  experiment" (the poisoning mechanism this card does NOT address), and
  "Future considerations" (the option ranking and the acceptance-test shape).
- `src/jarvis/core/lifecycle.py:13` - `VOICE_PLACEHOLDER_TEXT`.
- `src/jarvis/app.py:476` (default `self._current_turn_history_text`),
  `:622` (`on_utterance` passes `VOICE_PLACEHOLDER_TEXT` as the turn text),
  `:979` (`_record_turn_user_event`), `:1064-1065`
  (`time_context=format_time_context(...)`, `current_request_text=history_text`
  in `assemble_working_context`). Note the report's old "second system message"
  concern (`app.py:497`) is already resolved: time context is folded into the
  working-context assembly, not a separate message.
- `src/jarvis/journal/transcription.py` - `DEFAULT_TRANSCRIPTION_INSTRUCTION`
  and the comment recording that instruction wording is what makes the model
  attend vs refuse. This is the proven-good framing to borrow from.
- `src/jarvis/journal/fork.py:121` - the other `VOICE_PLACEHOLDER_TEXT` use, so
  any wording decision is consistent across the fork seed path.
- `manual/manual_check_audio_comprehension.py` - the cheap "after a refusal"
  proxy check the acceptance handoff re-points at the candidate wording.

## The design decision (make it explicitly, do not just patch)

The current-turn text a voice turn sends is the SAME string that gets stored in
the journal and in `ConversationHistory` (`app.py:1065` feeds the model;
`app.py:622`/`_record_turn_user_event` feed storage). Two clean options; pick
one and record why in the card's completion notes:

- **Option A - change the placeholder wording (cheapest, report's first
  choice).** Replace the bare `[голосовое сообщение]` with a short
  instruction-framed line that reads as a request to listen and answer (borrow
  the transcription instruction's proven framing, but for *answering* not
  transcribing - e.g. an instruction to listen to the attached recording and
  respond to it). One change, flows to model + history + journal.
  *(This card's own candidate phrasing, written before the session: the
  acceptance session then measured "attached" and English wording as the two
  things to avoid - see Completion notes for what actually shipped.)*
  - Consequence to handle in the same change: this string is also what past
    voice turns show the model on every later turn, and what the Journal
    renders. The append-only journal keeps old events verbatim (History is not
    the Journal - report), so only new turns get the new text; still, check the
    Journal timeline rendering of the new line and confirm it reads sanely as a
    past user turn, not as a leaked instruction.

- **Option B - decouple model-facing framing from the stored record (more
  surgical, more code).** Send an instruction-framed current-turn text to the
  model while storing a clean human-readable label (e.g. keep a short
  "Voice message" style label in history/journal). Requires carrying two texts
  through `on_utterance` -> `_start_turn` -> `assemble_working_context`
  (`current_request_text` becomes distinct from the stored/history text).
  Cleaner separation of concerns (the durable record is not an LLM prompt), but
  touches the working-context assembly and the history/journal write path.

Recommendation: start with **Option A** because the report's owner ranked the
wording change first and it is nearly free; treat Option B as the fallback if A
helps but the placeholder-as-history side effect is undesirable, or if the
owner wants the record decoupled from prompt text on principle. Do not
implement both.

Whichever is chosen, keep the wording **configurable** the way
`DEFAULT_TRANSCRIPTION_INSTRUCTION` is (a default constant, tunable without a
code change), so the framing can be adjusted against the live model between
sessions.

## Explicitly out of scope

- The session-poisoning mechanism (answer-based drop / dropping voice exchanges
  from context). That is the report's harder option and a separate card.
- Any change to the audio transport, `build_payload`, or the `images` contract
  - the audio is already attached correctly; this is purely the accompanying
  text.
- The voice-intent probe (`voice_intent_directive`, `config.py:687`) - do not
  alter the mode-switch classification pass.
- Microphone gain / capture level (a separate open item in the report).

## Completion notes

**Option chosen: A.** `VOICE_PLACEHOLDER_TEXT` (`src/jarvis/core/lifecycle.py`,
name kept - only its value changed, to keep the diff to the one thing this
card is about) went through three iterations in the owner's live acceptance
session (2026-09-01) before landing on the shipped wording. Full account with
the actual live outputs at each step is in the origin bug report's "Seventh
data point" section - summary here:

1. English, mirroring `DEFAULT_TRANSCRIPTION_INSTRUCTION`'s proven-good
   framing direction: leaked into the *response* language (Russian speech,
   English answer) via the system prompt's own "Отвечай по-русски, если
   пользователь явно не попросил другой язык" reading an English user-role
   message as such a request.
2. A literal Russian translation of the same sentence: fixed the language
   leak, still refused. Read at the time as the model echoing "attached"/"as
   the next turn of this conversation" back as an unfulfilled request - a
   single-turn reading that the n=10 runs later did not support.
3. **Shipped:** "Прослушай эту запись и ответь на то, что в ней сказано." -
   dropped "attached" and the "next turn" clause.

**This shipped wording is not validated, and the earlier claim in this card
that it was is retracted.** It was written from
`manual/manual_check_audio_comprehension.py` answering on-subject on the three
known-good July wavs (2.7-6.6 s) in both the fresh-context and poisoned-history
cases. Those clips also pass under the *old* framing: they are long and clear
enough to survive the suppression, so they discriminate nothing. Measured
properly afterwards, this text alone was heard 0/10 on a short clip that
`DEFAULT_TRANSCRIPTION_INSTRUCTION` heard 10/10 (cell G vs cell A,
`tasks/bug_reports/2026-09-01-request-shape-suppresses-audio-attention.md`).
It is retained as the least-bad default - dialog language, no reference to an
attachment - not as a fix. The same report records the rule this episode
established: nothing about this model's audio handling may be concluded from
fewer than 10 runs per condition.

The Russian choice is the one part that is evidence-based rather than a
stylistic call, and it stands independently of the audio question: an
English string in the `user` role of a Russian-persona dialog is a real
mechanism for accidental language switching, independent of the audio's own
language, given how the system prompt's language rule reads it.

**Configurable, mirroring the cited precedent exactly.** Added
`PromptSettings.voice_turn_instruction: str | None = None`
(`src/jarvis/core/config.py`), resolved through the same `_resolve_prompt_field`
machinery as `reasoning_low`/`voice_intent_directive` (so `@file` references
and non-empty validation come for free). `Orchestrator.on_utterance()`
resolves `self._reasoning_prompt_settings.voice_turn_instruction or
VOICE_PLACEHOLDER_TEXT` and passes the result as both the model-facing
current-turn text and (via `_start_turn` -> `_current_turn_history_text`) what
`ConversationHistory` records - one value, one place it is decided, matching
Option A's "one change" framing. Production wiring needed no new plumbing:
`Orchestrator` already receives the live `PromptSettings` as
`reasoning_prompt_settings=settings.prompts` (`app.py`, `run()`). Config key:
`[prompts] voice_turn_instruction` (documented with an example in
`config.example.toml`, next to `response_voice`/`response_text_voice`).

**Correction to this card's own framing (flagged and confirmed with the
owner before implementation): the Journal is not a consequence here.** This
card and the origin bug report both describe `VOICE_PLACEHOLDER_TEXT` as
"the SAME string that gets stored in the journal" and ask for a check of
"the Journal timeline rendering of the new line." That is not how the code
works: `JournalRecorder.record_voice_user()` (`src/jarvis/journal/recorder.py`,
`_write_voice_user`) always writes `text=""` for a voice event - the
placeholder/instruction text never reaches the journal store. The frontend
(`_journalEventBodyText()`, `status_console_ui/app.js:2606`) just echoes
`event.text` with no fallback string of its own. This matches `PROJECT.md`'s
own settled, do-not-relitigate fact: *"A voice turn is recorded with empty
`text` and its audio as media"* (`PROJECT.md:113`). So there is no Journal
rendering to check - that acceptance-handoff bullet is inapplicable and is
removed below rather than kept as dead ceremony.

The real consequence surface is narrower than the card described:
`ConversationHistory` (in-memory, feeds the model on later turns of the same
session via `self._history.add("user", self._current_turn_history_text)`,
`app.py`) and `journal/fork.py:_model_facing_text()`'s fallback for an old
voice event with no transcript.

**Correction (Codex stop-review, 2026-09-02): "it imports the same constant,
so it tracks the new wording automatically" was the wrong conclusion, and
shipping it would have been a bug.** A fork seed reconstructs past turns as
text and carries none of their audio, so tracking the new wording meant
seeding the model an instruction to listen to a recording the request does
not contain - the same refusal-shaped input this whole line of work is about.
`fork.py` now owns `UNTRANSCRIBED_VOICE_TURN_TEXT`
("[голосовое сообщение без расшифровки]"), a label for something that
happened rather than an instruction, and no longer imports from
`core.lifecycle` at all. Two tests pin it: one on the label, one asserting a
seed never carries `VOICE_PLACEHOLDER_TEXT`. This also matches the precedent
already in the codebase - `inputs/attachment_audio.py`'s cue is deliberately
not `VOICE_PLACEHOLDER_TEXT` for the same class of reason. The live
`[prompts]` override still does not reach `fork.py`, which stays a pure,
settings-free module.

**Tests added/changed** (TDD - written before the implementation above):
`tests/test_config.py` (defaults-to-None, literal override, `@file`
reference, empty-string-raises - mirroring the `reasoning_low` tests),
`tests/main_split/test_main_orchestrator_turns.py` (override flows to the
backend-facing message), `tests/main_split/test_main_attachment_turns.py`
(override flows to recorded history), `tests/main_split/test_main_journal_typed_turns.py`
and the same orchestrator file's existing default-path assertions (hardcoded
`"[голосовое сообщение]"` literals replaced with the imported constant, so
they no longer silently re-pin the old wording). `tests/test_journal_fork.py`'s
`test_fork_seed_uses_voice_placeholder_without_transcript` had its
`budget_chars=100` bumped to `len(VOICE_PLACEHOLDER_TEXT) + 50` - the new
wording is longer than the old bracketed caption, and 100 was never a
documented budget contract, just headroom for the old text.
`tests/test_backend.py` and `tests/test_debug_transcript.py` also contain the
old literal, but only as arbitrary example message content for unrelated
transport/transcript-recording assertions - left untouched.

`python -m pytest` (2374 passed, 1 pre-existing skip), `python -m ruff check`,
and `python -m ruff format --check` are all green.

**Codex stop-review finding, fixed:** the first draft of the handoff below
told the runner to read `logs/jarvis-debug.jsonl`'s *last* record's
`messages[-1]` (or `[-2]` with a screenshot) to confirm the active wording,
and claimed `manual/manual_check_audio_comprehension.py` exercised a
configured `[prompts].voice_turn_instruction` override automatically. Both
were wrong: a tool-calling turn writes more than one debug record and later
ones no longer end with the voice turn's own message (fixed by matching on
the message carrying `"media"` with a `wav` entry instead of a fixed index/
"last record"), and the manual script hardcoded the bare
`VOICE_PLACEHOLDER_TEXT` import (`ask()`, line 96) rather than reading
config at all, so a configured override was silently ignored. Fixed the
script itself - `main_async` now resolves `settings.prompts
.voice_turn_instruction or VOICE_PLACEHOLDER_TEXT` once, threads it through
every `ask()` call as `voice_turn_text`, and prints it as `voice turn text:
...` - so the claim in step 5 below is now true instead of documented around.

**Second Codex stop-review finding, fixed:** that first fix was incomplete -
the "after a refusal" poisoned-history case still built its simulated *prior*
voice turn from the module-level `REFUSAL_HISTORY` constant, which hardcoded
the bare `VOICE_PLACEHOLDER_TEXT` default for the fake prior user message
regardless of the resolved `voice_turn_text` used for the live turn right
after it. With a configured override active, that produced a history no real
session ever has - a session's past voice turns and its current one always
carry the same resolved text, because `ConversationHistory` records
`_current_turn_history_text` (the one resolved value, `app.py`) for every
voice turn alike. `REFUSAL_HISTORY` is now `refusal_history(voice_turn_text)`,
a function called with the same resolved value after config load, so the
simulated prior turn and the live turn agree, matching what an override
session actually looks like.

## Tests (automated, logic only)

The automated suite cannot prove the refusal is gone (that is the live gate),
but it must pin the mechanical change:

- Update/extend the tests that assert the voice turn's current-turn text and
  its history/journal recording to the new wording (grep tests for
  `VOICE_PLACEHOLDER_TEXT` and `[голосовое сообщение]`).
- If Option B: a test that the model-facing `current_request_text` for a voice
  turn is the instruction-framed text while the recorded history/journal text
  is the clean label - i.e. the decoupling actually holds.
- `python -m pytest`, `python -m ruff check`, `python -m ruff format --check`
  green.

## Acceptance criteria

- [x] The voice turn's current-turn model-facing text is an instruction to
      listen to and answer the recording, not a bracketed caption; the
      wording is a tunable default constant.
- [x] The chosen option (A or B) is implemented cleanly with its history/journal
      consequence handled and recorded in completion notes; not both options.
- [x] Automated logic suite, `ruff check`, and `ruff format --check` are green.
- [ ] A self-sufficient human-run acceptance handoff is prepared (below). The
      bug is NOT marked fixed by this card; the owner's session run decides that
      and the report is updated with the result.
      **Unmet, and not meetable as written.** The handoff was prepared and the
      owner ran it; the run is what produced the request-shape measurement. Its
      pass condition - a drop in the first-turn refusal rate - cannot be
      attributed to this card's wording while tool declarations and the system
      prompt each suppress audio attention independently, so re-running it
      would measure the request shape, not this change. Kept below as the
      record of what was run, not as a gate to re-run.

## Human-run acceptance handoff (prepare; owner runs)

> **Superseded as a gate, kept as a record.** This is the handoff the owner
> ran on 2026-09-01/02. It did not decide this card; it uncovered the
> request-shape suppression (see Status). Do not re-run it expecting a verdict
> on the wording - the steps below are still mechanically correct and remain
> useful for confirming what text actually reaches the model, which is why
> they are kept.

Per the report, the acceptance is a **session, not a single request**, because
the failure is probabilistic.

**0. Confirm the active wording.** Default lives in `VOICE_PLACEHOLDER_TEXT`,
`src/jarvis/core/lifecycle.py` ("Прослушай эту запись и ответь на то, что в
ней сказано."). Unless
`config.toml` has a `[prompts] voice_turn_instruction = "..."` line (see the
commented example in `config.example.toml`, next to `response_voice`), the
active value is the default above - open `config.toml` and check for that
key if unsure (if you were testing an earlier candidate via that key and it
now duplicates the shipped default, remove the line - harmless either way,
just redundant). To see
the literal text actually sent on a real turn instead of trusting the config
read: run with `--debug` (step 1 below), do one voice turn, then open
`logs/jarvis-debug.jsonl` (one JSON line per backend request - a turn that
triggers a tool call writes more than one line, each the *next* pass, so the
file's *last* line is not reliably the voice turn's own request). In that
turn's records, find the message that carries `"media": [{"kind": "wav",
...}, ...]` - the audio always rides on the voice turn's own current-turn
message, never on an older history message or a tool-loop follow-up - and
read that message's `content`. That is the exact string that reached the
model for the voice turn, no source reading required.

**1. Run Jarvis.** From the repository root:

```
python -m jarvis --status-console --debug
```

(`--debug` requires `--status-console`; it records each request to
`logs/jarvis-debug.jsonl` per step 0 - plaintext message content, so treat that
file as sensitive and delete it after the session per the debug-mode privacy
warning the console shows on startup.)

**2. Before each first-turn test below, start a fresh context.** Journal tab
-> **"New context"** button (`journalNewContextButton` in the status console;
confirms with a "Start a blank context and leave the current one?" dialog).
Do not reuse a session that has already had a voice turn in it - the confirmed
session-poisoning mechanism (a prior refusal in history) would confound a
first-turn result.

**3. Run several first-turn voice utterances, each in its own fresh context
(step 2 before each one). Ask something substantive - a real question with
content you can check the answer against - not a short channel-check phrase
like "как ты меня слышишь?". That phrase produces an unverifiable bluff on
both the old and the new wording, and short clips of it fail under the
suppressed dialog request shape regardless of the text accompanying them
(`tasks/bug_reports/2026-09-01-request-shape-suppresses-audio-attention.md`)
- so a failure there tells you nothing about this card's wording.**
   - a clear Russian clip,
   - a clear **English** clip (the 2026-09-01 case; the audio/prompt language
     mismatch is a suspected aggravator worth isolating),
   - one deliberately unintelligible clip as a negative control (a refusal
     here - "нечего слушать" / "not recognized" wording - is correct behavior,
     not a regression; see the report's fifth experiment for how to read the
     wording).
   - Repeat enough first turns of each kind to be meaningful, not just one -
     the report's per-session refusal counts (table near the top of the
     origin bug report) are the model for how many.

**4. Record the refusal rate.** For each first turn: utterance language, clip
clarity (clear/deliberately unintelligible), and whether the answer was a
refusal ("ваше голосовое сообщение не дошло/не было преобразовано" or similar
- see the report for the exact wording family) or a real answer to the
content. Compare against the origin report's pre-fix counts (table under
"Evidence from the journal history" and the 2026-09-01 "Sixth data point").

**5. Check session-poisoning is not worse.** Run
`manual/manual_check_audio_comprehension.py`'s "after a refusal" cases. The
script resolves `[prompts].voice_turn_instruction` the same way
`Orchestrator.on_utterance()` does (`settings.prompts.voice_turn_instruction
or VOICE_PLACEHOLDER_TEXT`) and prints the resolved value as `voice turn
text: ...` at the top of its output, so it exercises whatever is actually
configured - confirm that line matches what you expect before reading the
results:

```
python -m manual.manual_check_audio_comprehension --quiet-wav <path to a recording with nothing intelligible in it>
```

Read the "after a refusal" result lines beside the "fresh context" ones for
the same wav (see the script's own docstring for how to read the three
cases). This change does not target the poisoning mechanism, but must not
make it worse.

**6. Decide.** Do not conclude success from one lucky session; ship only if
the first-turn refusal rate drops across repeated fresh-context runs
(step 3-4), with the negative control (step 3's unintelligible clip) still
refusing as expected. On success, update the origin bug report
(`tasks/bug_reports/2026-07-25-model-stopped-comprehending-voice-audio.md`)
with the session result and close it; if the rate does not drop, record that
result there too - Option A did not work and the fallback (answer-based drop,
"Future considerations" in the report) is the next card.
