# The model stopped comprehending voice audio, and offers a transcript instead

**Detected at commit:** branch `fix/microphone-device-identity` (working
tree), during the human-run verification of
`tasks/done/story-microphone-device-identity.md`, step A4.
**Reported by:** owner, 2026-07-25.
**Status:** Open, and root-caused elsewhere. Updated 2026-09-02: the wording
fix (`tasks/task-voice-turn-audio-framing.md`, Option A) is **not** a fix for
this bug. The acceptance session for it, running live first-turn refusals down,
found something larger than any wording: **attention to attached audio is
suppressed by the dialog request shape itself** - tool declarations, the
system prompt, and the current-turn wording each break it independently,
measured at 10 runs per condition in
`tasks/bug_reports/2026-09-01-request-shape-suppresses-audio-attention.md`.
That report is where this bug is now tracked. It explains this one's
long-standing "refusing vs bluffing" puzzle, and it contradicts this report's
own first/second experiments, which cleared tools on four requests total. This
report's primary open question (does comprehension work at all today?) is
answered YES but narrowly: it works reliably through the transcription path
(bare request, no system prompt, no tools) and unreliably through the dialog
path, with long clear clips surviving where short ones do not. **Caveat on
everything below: these experiments run one to five requests per condition,
and this failure is probabilistic - nothing here may be read as a controlled
result. See the seventh data point's corrections.**
Prior status (2026-08-11): open and unblocked once the debug mode
(`tasks/done/task-debug-mode-and-request-transcript.md`) shipped. One mechanism
confirmed, one input taxonomy established, and the live first refusal not
reproducible from anything that could be reconstructed.
Confirmed: the model follows its own previous answer, so one refusal in
conversation history makes every later voice turn in that session a
refusal. Reopened by the owner's zero-gain control: a non-refusal is not
evidence of comprehension. That control is now superseded - the sixth data
point separates comprehension from bluffing directly (transcription of the
exact refused wav). Not caused by the microphone work; see "Why the
microphone fix is not the cause" - that half is verified working by this
very run.

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

## Fifth experiment: what each kind of input actually produces (2026-07-25)

The owner pointed out that this model tokenizes audio directly, with no
built-in transcription step, so silence, noise without intelligible
speech, and no audio at all are three different inputs that need not
produce the same answer. Measured, agent-run against the live endpoint
with the owner's authorization:

| input | runs | refusals | typical answer |
|---|---|---|---|
| synthesized digital silence, 2 s | 3 | 2 | "не могу прослушать аудиофайлы напрямую" |
| the weak 22:00 utterance (speech -28 dB, 1.1 s) | 5 | 0 | "Да, я вас слышу и готов помочь" |
| the loud 22:16 utterance (speech -21 dB, 2.1 s) | 5 | 0 | "Да, я вас отлично слышу" |
| the weak utterance again, `stream=true` | 5 | 0 | same |
| heavy interference, live (owner) | 1 | 0 | "аудиосообщение не было распознано должным образом" |

**The refusal wording means "there was nothing in this audio".** It is
what digital silence produces, not a denial of the capability. That is a
different failure from "не было распознано", which is what audio
carrying unintelligible sound produces - the model distinguishes the two,
which is what direct tokenization would predict.

**And the reproduction gap is now explicit.** Eighteen requests carrying
the real recordings - including the exact utterance the engine refused
live, non-streamed and streamed - produced no refusal at all. So the live
first-turn refusal is not reproducible from the recorded audio plus any
payload variable that can be reconstructed: tools, memory, placeholder,
time context, streaming, and history have each been varied and none of
them turns that wav into a refusal.

What differs between the engine's request and every reconstruction is
whatever the engine actually sent, and nothing records it. This is
exactly the gap `tasks/done/task-debug-mode-and-request-transcript.md` exists
to close, and further reconstruction is not the way to close it: the next
step on this bug is a debug run, not another script.

## Sixth data point: comprehension confirmed, first-turn refusal on a clean clip (owner, 2026-09-01)

**Code state:** owner ran a fresh copy with empty history (`D:\AI\Jarvis.bck`),
code equivalent to `main` at `601e0f3` (story-v1.9.1 merged). This bug predates
and is unrelated to that story and to the v1.9.0 response-mode/voice-intent
work; it is the same first-turn refusal this report has tracked since
2026-07-25.

**What happened.** A fresh context was created (session
`20260901-003423-ba4272`, New context at 00:34:23). Its **first** voice turn -
`utterance-20260901-003449-0001.wav`, `audio_duration=2.5s`, an English
question - was answered:

> К сожалению, ваше голосовое сообщение не дошло до меня или не было
> преобразовано в текст. Пожалуйста, попробуйте отправить его еще раз, и я
> сразу же приступлю к расшифровке.

This is the same "there was nothing in this audio" refusal wording the fifth
experiment characterized, now emitted on turn one of a session with **no prior
answer in history to follow** - so the confirmed session-poisoning mechanism
("the model follows its own previous answer") does not explain this instance.
It is a first-turn refusal.

**The decisive contrast.** At 00:36:20, in the same run, the owner ran the
manual transcription on that exact wav and it produced the correct verbatim
text (log: `Transcription transcribed for 20260901-003423-ba4272:1`,
model `gemma4-12b-jarvis-free-mm`):

> Can you tell me about yourself and a few words?

So on one wav, in one run, two framings gave opposite outcomes:

| framing | current-turn user text | outcome |
|---|---|---|
| dialog turn | `[голосовое сообщение]` (`VOICE_PLACEHOLDER_TEXT`) + conversational system prompt | refusal ("нечего слушать") |
| transcription | `DEFAULT_TRANSCRIPTION_INSTRUCTION` ("Transcribe this recording verbatim...") | correct verbatim transcript |

This is a stronger contrast than any earlier reconstruction: same audio, same
`build_payload()`/`images` transport, same session, minutes apart. It settles
two things the report left open:

1. **Comprehension works today.** The transcription proves the audio is
   intelligible and the model decodes it. The fifth experiment's worry ("does
   comprehension work at all today?") is answered yes, without relying on the
   worthless "как ты меня слышишь" criterion - transcription of the exact
   refused wav cannot be produced by bluffing.
2. **The first-turn refusal is not gated on a short or unclear clip.** Section
   "Third experiment" attributed the first refusal to "ordinary model behavior
   on a short or unclear clip". This clip is 2.5s and fully intelligible (the
   transcript is perfect), yet turn one refused. So the first refusal is driven
   by the **current-turn framing**, not clip quality.

**Code path verified correct (framing, not plumbing).** The dialog voice turn
attaches the wav to `messages[-1]["images"]` via the same
`OllamaBackend.build_payload()` the transcription path uses
(`backend.py`), and for a VOICE turn automatic retrieval is skipped, so the
placeholder message is genuinely the final message the audio rides on. The
audio is sent. What differs is only the accompanying text: a caption-like
placeholder versus an explicit "listen and transcribe" instruction. This is
exactly the mechanism "Future considerations" ranked first.

**New variable worth a test dimension:** the utterance was **English** while
the dialog system prompt forces Russian ("Отвечай по-русски") and the user
line is a bracketed Russian placeholder. Whether the audio/prompt language
mismatch raises the first-turn refusal rate is now a cheap thing to vary in the
fix card's acceptance session (English clip vs Russian clip, same wording).

**Recommendation.** Proceed with the wording fix (its own card, per "Future
considerations"): make the voice turn's current-turn text read as a request to
listen rather than a caption for an attachment - candidate direction: replace
the bare `[голосовое сообщение]` with a short instruction-framed line, and
check the history/journal rendering in the same change since that text is also
what past turns show the model. The audio/prompt language mismatch is an extra
axis for the acceptance session. Do not ship on one run: this remains
probabilistic, and the acceptance test is a session (several voice turns,
including one deliberately unintelligible and one English), not a single
request. This data point does not itself justify a code change in the current
release branch; it justifies opening the fix card.

## Seventh data point: three wording iterations, and two wrong conclusions drawn from them (owner + agent, 2026-09-01)

> Read this section with its two corrections at the end. Written as the
> session ran, it twice announced a root cause on one-to-three runs per
> condition, and both announcements were overturned by 10-run measurements the
> same night. It is kept intact as the record of how the real cause was
> reached; the standing account is
> `tasks/bug_reports/2026-09-01-request-shape-suppresses-audio-attention.md`.

Human-run acceptance session for the wording fix (`tasks/task-voice-turn-audio-framing.md`, Option A), same day as the sixth data point, later that evening.

**Three wording iterations, live.** The card's first candidate (English,
borrowing `DEFAULT_TRANSCRIPTION_INSTRUCTION`'s proven-good direction) leaked
into the *response* language: the owner spoke Russian, first-turn answer came
back in English ("I haven't received an audio recording yet. Please attach or
upload the file..."). Cause: the system prompt's own conditional - "Отвечай
по-русски, **если пользователь явно не попросил другой язык**" - reads an
English user-role message as such a request, regardless of what language the
audio is in. A literal Russian translation of the same sentence structure
removed the language leak (confirmed: Russian speech, Russian answer) but kept
the refusal, now echoing the instruction's own vocabulary back near-verbatim
("Пожалуйста, прикрепите аудиозапись... как если бы я был участником этого
разговора") - read as a standing instruction about a future attachment, not a
statement that audio is already in this message. Dropping "attached" ("приложенную")
and the "as the next turn of this conversation" clause - "Прослушай эту запись
и ответь на то, что в ней сказано." - stopped the refusal on the first live
retry.

**Checked against known content, not a live guess** - but, as the first
correction below shows, against clips that could not discriminate.
`manual/manual_check_audio_comprehension.py`
(fixed in this same card to resolve `[prompts].voice_turn_instruction` instead
of ignoring it) replayed the three known-good July wavs under the new wording:
all three landed on-subject - cyclic cosmology with real detail, "some humans
become addicted to AI", the sycophancy phenomenon named correctly - in both the
fresh-context and after-a-refusal (poisoned-history) cases. Genuine
comprehension, confirmed the same way the sixth data point confirmed it, not
the "как ты меня слышишь"-style bluff the fourth experiment already
discredited as a criterion.

**Then a live first turn still refused - "Как ты меня слышишь?", 1.3s, spoken
Russian, under the new wording.** Root-caused directly (agent, `OllamaBackend`
called straight from a script, no Jarvis process/journal/history in the loop,
so nothing but the wav and the prompt text could be in play):

- The exact wav replayed 3x against the new wording: refused 3/3 -
  reproducible, not a one-off.
- The same wav against the **pre-fix** bracket placeholder
  (`[голосовое сообщение]`), as a control: also did not answer the question -
  a generic self-introduction ("Вы можете обращаться ко мне как к Джарвису...
  Чем я могу быть полезен прямо сейчас?"), not "да, слышу вас хорошо" and not
  anything about this recording's content. The owner's "this phrase always
  worked" read on the pre-fix wording was a read on a *plausible-sounding,
  content-free* answer - exactly the fourth experiment's "worthless success
  criterion" - not a verified one. The new wording did not break a working
  case here; it turned an unverifiable bluff into a visible failure.
- **Decisive contrast, same method as the sixth data point:** the exact wav
  through `DEFAULT_TRANSCRIPTION_INSTRUCTION` - the path that correctly
  transcribed a different refused clip earlier the same day - refused 3/3
  ("Please provide the audio file/recording you would like me to
  transcribe..."). This rules out dialog wording/framing entirely for this
  clip: even the proven-good, non-dialog, no-persona instruction fails on it.
- `jarvis.audio.metrics.utterance_metrics_from_wav_bytes` against the three
  known-good clips: this clip is `duration=1.30s peak=-4.1dBFS`, the
  **shortest** of the four compared (July clips: 2.70-6.60s) and **louder**,
  not quieter (July clips: -8.2 to -12.1dBFS peak) - ruling out signal level
  as the discriminator, consistent with the report's earlier level analysis.

**Conclusion drawn at the time (WRONG, see both corrections): two independent
causes, separable by clip, both real** - the framing fix working on the three
substantive clips (2.70-6.60s), and the 1.30s clip failing at the audio level
before any dialog framing enters the picture.

**First correction, same evening, after a properly powered measurement.** The
paragraph above attributed the second cause to the clip being *short*, on the
strength of one to three runs per condition. Both the attribution and the
method were wrong. The failure is probabilistic per request: the same bytes
returned a refusal on one run and a correct transcript on the next, which
produced two flatly contradictory "controlled" results within the same hour of
this session. At 10 runs per cell, duration is not the discriminator: a
0.3s-padded copy of the 1.30s clip is 10/10 where the original is 0/10, level
normalization without added silence stays 0/10, and the bytes are
byte-identical 16 kHz mono PCM_16 in every case.

**Second correction, later the same night.** The first correction then named
*trailing silence* as the real discriminator. That does not hold either: a
July clip with a 0.140s tail is 9/10 while the 0.114s-tail clip above is 0/10
at identical duration and byte size, and a 2.70s clip with a 0.093s tail
works. Padding moves a marginal clip across a threshold; it does not identify
what makes a clip marginal. The cause is the request shape, and the framing
fix is not confirmed working - the three substantive clips pass under the old
wording too, so they never discriminated. Full tables, the threshold sweep,
and what this retires from the sections above are in
`tasks/bug_reports/2026-09-01-request-shape-suppresses-audio-attention.md`.

That report also answers this one's "Fourth experiment" question. In the
dialog request shape the model frequently has no usable audio at all and
answers from the current-turn text alone, so refusing and bluffing (and
fabricating) were never separate behaviors -
they are the same state, and which one surfaces depends only on what the
accompanying text invites. **Methodological note for anything built on this
report: its own experiments are n=1 to n=5 per condition. At that sample size
this failure is indistinguishable from noise; treat those conclusions as
provisional until re-measured at n>=10.**

**Second correction, later the same night: the padding story above is itself
superseded.** Re-measured at n=10, the request *shape* is what suppresses
audio attention - tools, the system prompt, and the current-turn wording each
independently drop a clip from 10/10 heard to 0/10, and the clip this section
called undecodable transcribes fine in a bare request. Silence padding still
moves a marginal clip across the threshold, but it is an intervention without
an explained mechanism, not the cause. See
`tasks/bug_reports/2026-09-01-request-shape-suppresses-audio-attention.md`;
no fix card exists yet, because the direction (tools off for audio turns vs a
two-pass transcribe-then-answer shape) is the owner's call.

**Not this card's target either way.** `tasks/task-voice-turn-audio-framing.md`
is scoped to the current-turn text and is not blocked by this. The acceptance
session continues with substantive first-turn questions (verifiable against
real content, like the known-good replays) rather than short channel-check
phrases like "как ты меня слышишь", which cannot distinguish comprehension
from a bluff on either the old or the new wording.

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
