# Task: Reframe the voice turn's current-turn text to cut first-turn audio refusals

**Status:** Not started.
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

- [ ] The voice turn's current-turn model-facing text is an instruction to
      listen to and answer the attached recording, not a bracketed caption; the
      wording is a tunable default constant.
- [ ] The chosen option (A or B) is implemented cleanly with its history/journal
      consequence handled and recorded in completion notes; not both options.
- [ ] Automated logic suite, `ruff check`, and `ruff format --check` are green.
- [ ] A self-sufficient human-run acceptance handoff is prepared (below). The
      bug is NOT marked fixed by this card; the owner's session run decides that
      and the report is updated with the result.

## Human-run acceptance handoff (prepare; owner runs)

Per the report, the acceptance is a **session, not a single request**, because
the failure is probabilistic. The handoff must, from its own text:

- Name how to run Jarvis in voice mode and where the wording default lives
  (constant name + file), so the runner can confirm the active value.
- Run several first-turn voice utterances in **fresh** contexts (New context
  before each), including:
  - a clear Russian clip,
  - a clear **English** clip (the 2026-09-01 case; the audio/prompt language
    mismatch is a suspected aggravator worth isolating),
  - one deliberately unintelligible clip as a negative control (a refusal here
    is correct behavior, not a regression).
- Record the refusal rate before vs after across enough first turns to be
  meaningful (the report's per-session counts are the model for this).
- Use `manual/manual_check_audio_comprehension.py`'s "after a refusal" cases as
  the cheap proxy for the poisoning interaction, to confirm this change did not
  make session poisoning worse (it does not target it, but must not regress it).
- State explicitly: do not conclude success from one lucky session; the change
  ships only if the first-turn refusal rate drops across repeated fresh-context
  runs. On success, update the origin bug report with the result and close it.
