# The model stopped comprehending voice audio, and offers a transcript instead

**Detected at commit:** branch `fix/microphone-device-identity` (working
tree), during the human-run verification of
`tasks/done/story-microphone-device-identity.md`, step A4.
**Reported by:** owner, 2026-07-25.
**Status:** Open, one mechanism confirmed and the main question reopened.
Confirmed: the model follows its own previous answer, so one refusal in
conversation history makes every later voice turn in that session a
refusal. Reopened by the owner's zero-gain control: a non-refusal is not
evidence of comprehension, so it is not yet established that the model
comprehends the audio at all. Not caused by the microphone work; see "Why
the microphone fix is not the cause" - that half is verified working by
this very run.

## Symptoms

A voice turn is captured, recorded, and sent, and the model answers:

> Извините, но я не могу прослушать или расшифровать аудиофайлы
> напрямую. Пожалуйста, пришлите текст сообщения...

Both turns of the 2026-07-25 session answered this way. The recorded
utterance plays back clearly from the Journal view, twice confirmed by the
owner.

## Why the microphone fix is not the cause

Everything the microphone owns is provably working in the failing run:

- `logs/jarvis.log` records `[LLM] Model request: inputs=audio count=1
  audio_duration=1.1s` and `...=1.5s` for exactly the two refused turns,
  so the request carried the audio.
- The recorded wavs are 16 kHz mono, 1.1 s and 1.5 s, peak -18.8 and
  -20.1 dBFS - audible, and the owner confirms they play back clearly.
- The same refusals appear in journal sessions from 2026-07-22 and
  2026-07-24, before this branch existed.

## Evidence from the journal history

Counting refusals per session across the whole journal (assistant answers
that decline to listen and ask for text instead):

| date       | voice turns | refusals |
|------------|-------------|----------|
| 07-17/18   | 15          | 0        |
| 07-19      | 11          | 1        |
| 07-20/21   | 9           | 0        |
| 07-22      | 10          | 2        |
| 07-24      | 13          | 4        |
| 07-25      | 2           | 2        |

The 2026-07-17 answers prove comprehension outright, not politeness: a
spoken question produced an explanation of cyclic cosmology, another
produced an answer about AI sycophancy. Those are answers to what was
said. Nothing in the recent sessions demonstrates comprehension; the
"answered" turns there are all replies to a camera frame, or hedges like
"я не совсем уверен, что именно вы имеете в виду".

**Capture level does not explain it.** Sorting the same turns by peak
level puts an answered turn at -22.9 dBFS above a refused one at -16.0
dBFS. Level is therefore not the discriminator, though it is worth noting
separately that the 07-17 era captured ~11 dB hotter (peak ~-7 dBFS) than
today - a gain question of its own, not this one.

## First experiment: both original suspects cleared (2026-07-25)

The owner ran the check script against the refused wav (then named
`manual_check_audio_tool_payload.py`; replaced by
`manual/manual_check_audio_comprehension.py` once its success criterion
turned out to be worthless - see the fourth experiment). All four cases - tools on/off crossed with memory on/off -
answered "Да, я вас прекрасно слышу". The model hears that exact audio
through that exact `build_payload()`. Tools and memory are not the cause,
and neither is the recording.

That narrows it sharply: the difference is no longer *whether* audio
arrives, but what the engine wraps around it. Two ingredients the
one-shot request did not have:

- **The user text is `[голосовое сообщение]`** (`VOICE_PLACEHOLDER_TEXT`,
  `core/lifecycle.py:13`). A bracketed placeholder reads like a caption
  describing an attachment that is not there - which is close to what the
  refusals keep saying. The control request said
  "Голосовое сообщение пользователя." and was heard.
- **A second `system` message sits between the prompt and the user
  turn**, carrying the time context (`app.py:497`). The one-shot request
  had one system message and one user message.

The second run of the same script bisects exactly these two, ending on
the engine's real first turn. The owner also turned MCP off and raised
the microphone gain between runs; neither changed the outcome, which is
consistent with the first experiment's result.

## Second experiment: the wrapping is cleared too (2026-07-25)

All four cases were heard, including case 4 - the engine's first turn
reproduced exactly, bracketed placeholder and time-context system message
included, against the very wav the engine had just been refused on. So
neither ingredient is the trigger, and the model, the audio, the options,
and `build_payload()` are all now excluded by experiment.

## What is left, and why it fits everything

One difference remains between a heard request and a refused one: **the
conversation history**, which the script has never sent.

`ConversationHistory` records a voice turn as its placeholder text and no
audio (`app.py:557`, `history.add("user", self._current_turn_history_text)`
where the text is `[голосовое сообщение]`). So from the second turn of a
session onward, the model sees this above the current request:

```
user:      [голосовое сообщение]
assistant: Я не могу прослушать голосовое сообщение напрямую...
```

A model that has just declared it cannot hear audio stays consistent with
itself. Every later turn inherits the claim, regardless of what the audio
contains.

This explains the whole data set, including the parts the earlier
hypotheses did not:

- **Sessions are all-or-nothing**, which is what the per-session counts
  show: 07-17/18 sessions have zero refusals, recent sessions refuse from
  some point onward and never recover.
- **The script always hears**, 10 out of 10 across two runs: every request
  it sends is a fresh two-message context with no prior answer to be
  consistent with.
- **The 07-22 era plausibly seeded it**: capture was ~11 dB quieter then
  (the wrong device, per the quiet-microphone report), a genuinely
  unintelligible clip drew an honest refusal, and the refusal outlived the
  cause.

It also explains why nothing in the code changed on the day the behavior
did: the trigger is a model answer, not a commit.

## Third experiment: confirmed (2026-07-25)

Cases 5 and 6 differ in exactly one thing - what the assistant said one
turn earlier - with identical audio, wrapping, tools, and memory:

```
engine turn, after a refusal    -> Я не могу прослушать ваше голосовое
                                   сообщение напрямую...
engine turn, after being heard  -> Да, я вас отлично слышу. Качество
                                   связи хорошее, можете говорить...
```

**Cause: the model follows its own previous answer.** One refusal in
history makes every later voice turn in that session a refusal,
regardless of what the audio contains. Confirmed by experiment, not
inferred.

What this does *not* explain is the first refusal of a session, which has
no history to follow. That one is ordinary model behavior on a short or
unclear clip - today's was 1.1 s - and it would have been a harmless
one-off before it started being permanent. Two defects were stacked: an
occasional bad answer, and a context that makes it stick.

## Fourth experiment, by the owner: the success criterion was worthless

With the microphone gain at zero, on a recording where nothing is
intelligible, the model answered that it hears well. The owner compared
that recording against the first one in the poisoned session and
confirmed the failing one is markedly louder and more detailed.

This invalidates the criterion every run above used. "Да, я вас отлично
слышу" is producible from `[голосовое сообщение]` alone - the question
"как ты меня слышишь" needs no comprehension to answer. So the three
experiments prove what they prove and nothing more:

- tools, memory, placeholder wording, and the time-context message do not
  cause the *refusal*;
- the refusal is driven by the model's own previous answer.

They do **not** establish that the model ever comprehended the audio in
any of those runs. Refusing and bluffing are both non-comprehension; the
experiments only ever separated the two.

**Open, and now the primary question: does comprehension work at all
today?** The only hard evidence of it is the 2026-07-17 journal, where
spoken questions produced answers about cyclic cosmology, AI addiction,
and sycophancy - none of which can come from a placeholder.

`manual/manual_check_audio_comprehension.py` replays those exact
utterances against today's model in a fresh context, prints July's answer
beside today's, repeats each with one refusal in history, and takes the
zero-gain recording as a negative control:

```
python -m manual.manual_check_audio_comprehension --quiet-wav <zero-gain wav>
```

If the replays come back on-subject, comprehension works and the history
effect is the whole bug. If they come back generic while the negative
control produces the same confidence, then comprehension is gone
entirely, the refusals were the honest answers, and the history effect is
a second-order finding rather than the cause.

## Earlier suspected cause (superseded by the run above)

Two things entered every request between the working era and the failing
one, and both are in the message payload rather than the audio:

1. **Tool declarations, since v1.6.1 (2026-07-20).** Builtin tools are
   always registered and enabled, so `build_payload()` now attaches
   `tools` to every request, MCP or not. Before that, with MCP off, the
   payload had no `tools` key at all. A chat template that switches to a
   tool-calling path can stop honoring `images`, which is the field audio
   travels in (PROJECT.md's verified media contract).
2. **Curated memory injected into the system prompt, since v1.5.3
   (2026-07-19)** - the date of the first refusal. The current
   `memory.md` and `self.md` contain nothing about audio or about being a
   text-only model, but they do change the system prompt the model reads
   before deciding what it is.

Ranked: (1) is the stronger suspect on mechanism, (2) on timing. They are
independent and cheap to separate.

## The next experiment

The check script (now superseded, see the fourth experiment) sent one wav
four times, varying the placeholder text and the time-context system
message, and ending on the engine's exact first turn. It reused the
production `VOICE_PLACEHOLDER_TEXT`, `format_time_context()`, and
`build_payload()`, so the payload could not drift from what Jarvis sends.

## Temporary decision

No fix on this branch. The active story is microphone device identity and
capture-failure visibility; both are complete and this is neither. Folding
a payload-contract change into them would put an unverified request-shape
change into the same commit as a capture fix, and the two would then have
to be released or reverted together.

The workaround for the owner in the meantime is the Journal tab's text
input, which drives a normal turn including tool calls.

## Future considerations and boundaries

- If the placeholder is the trigger, the fix is a one-line wording change
  with a real consequence attached: `VOICE_PLACEHOLDER_TEXT` is also what
  the journal and the conversation history record for a voice turn, so
  changing it changes what past turns look like to the model on every
  later turn. Pick wording that reads as a request rather than a caption,
  and check the history rendering in the same change.
- If the extra system message is the trigger, the time context needs a
  different carrier - most likely folded into the single system prompt
  rather than sent as its own message. PROJECT.md's v1.3.2 section
  records why it is separate; that reasoning has to be revisited, not
  quietly overridden.
- If neither reproduces, the remaining variable is outside this
  repository - the Ollama or model version installed on the machine - and
  the next step is recording those versions in PROJECT.md's day-0
  environment notes, which currently pin neither. Note that the first
  experiment already makes a silent model update less likely: the same
  model heard the same wav minutes after refusing it.
- **History is not the journal.** Leaving something out of the model's
  context does not rewrite a recorded event, so the append-only rule does
  not constrain this fix. Whatever is decided, the journal keeps every
  turn exactly as it happened, refusals included.
- The fix is a design decision, not a patch, and it belongs in its own
  card. The options are not equal:
  - **Change what the user side of a voice turn looks like in history.**
    Today it is `[голосовое сообщение]`, which reads like an attachment
    the model never received. Cheapest to try and needs no detection of
    anything, but it is a hope, not a mechanism: the anchor the model
    follows is its own answer, not the user line. Test it before
    believing it.
  - **Keep the audio on the history turn.** `ConversationHistory`
    already carries `media_b64` and `as_messages()` already emits
    `images`, so the model would see the real prior audio instead of a
    placeholder. Costs context and latency on every turn, and
    `backend.py`'s docstring records that media on a non-final message
    has never been verified to be used at all.
  - **Drop the exchange from context when the answer shows the model did
    not hear.** The only option with a mechanism rather than a hope, and
    the only one that needs fragile matching against model text in the
    user's language.
  - **Drop voice exchanges from context wholesale.** Robust and needs no
    detection, but it also throws away every good answer, which is real
    continuity the user relies on for follow-up questions.
  My order: try the wording first because it is nearly free, and treat
  the answer-based drop as the fallback that will actually work. Do not
  ship the wording change on the strength of one lucky run - the failure
  it addresses is probabilistic.
  Whichever is chosen, the acceptance test is a session, not a request:
  several voice turns after one deliberately unintelligible one. The
  "after a refusal" cases in
  `manual/manual_check_audio_comprehension.py` are the cheap version of
  the same check and can be re-pointed at any candidate wording.
- Streaming remains the one difference no script covers: they all send
  `stream=false` while the engine streams. It is the next variable to
  isolate if the ones above run out, and it is cheap to add.
- The capture-level drop (~11 dB versus the 07-17 era) deserves its own
  look regardless of this bug's outcome.
