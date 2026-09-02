# The dialog request shape suppresses the model's attention to attached audio

**Detected at commit:** `72b4a0b`, branch `fix/voice-turn-audio-framing`
(working tree), during the human-run acceptance session for
`tasks/task-voice-turn-audio-framing.md`.
**Reported by:** owner + agent, 2026-09-01/02.
**Status:** Open, mechanism established, no fix implemented. Read the
2026-09-02 sections at the end first - they supersede the model attribution in
the table below and narrow the cause to one mechanism with several doors into
it. Recommended direction: two-pass (transcribe in the bare shape that already
works, then answer the transcript as an ordinary text turn).

> **This file replaces an earlier draft of the same night**
> (`...-utterances-cut-flush-are-not-decoded-by-the-model.md`) that named
> flush-cut audio as the cause. That draft was wrong - see "What this
> supersedes" below. Its padding measurement is kept here as a secondary
> observation, because the intervention is real even though the causal story
> around it was not.

## Symptoms

Voice turns - especially short ones - are answered as if no audio had
arrived. Depending on the current-turn text, the model either refuses
("Пожалуйста, предоставьте аудиозапись..."), bluffs a generic greeting
("Да, я вас слышу отлично. Чем я могу вам помочь?"), or fabricates a
confident "transcript" of words that were never spoken (a 70-word quote from
a 1.3 s clip; "Здравствуйте. На связи команда разработчиков продукта
Jarvis..."). `logs/jarvis.log` records `inputs=audio count=1` for these turns
and the journal plays the recording back clearly, so the wav is captured and
attached.

Meanwhile the explicit transcription action on the *same* stored wav returns
the correct words verbatim.

## The measurement

One-shot `OllamaBackend` calls from a script (no engine, no journal, no
history) against `gemma4-12b-jarvis-free-mm:latest`, **10 runs per cell**.
Clip: `journal/20260902-002313-5af193/utterance-20260902-002320-0001.wav`,
1.1 s, the spoken phrase is "Как ты меня слышишь?". "heard" counts answers
that contain the actually spoken words.

| # | request | heard |
|---|---|---|
| A | `DEFAULT_TRANSCRIPTION_INSTRUCTION` alone, no system message, no tools | **10/10** |
| G | the voice turn's `VOICE_PLACEHOLDER_TEXT` alone | 0/10 |
| F | time context + `VOICE_PLACEHOLDER_TEXT` | 0/10 |
| E | system prompt + `VOICE_PLACEHOLDER_TEXT` | 0/10 |
| C | system prompt + time context + `VOICE_PLACEHOLDER_TEXT` | 0/10 |
| H | system prompt + `DEFAULT_TRANSCRIPTION_INSTRUCTION` | 0/10 |
| B | `DEFAULT_TRANSCRIPTION_INSTRUCTION` + two tool declarations | 0/10 (10/10 explicit refusals) |

## Cause

**Attention to the attached audio is fragile, and at least three independent
parts of an ordinary dialog request each suppress it on their own:**

1. **Tool declarations.** A vs B: the identical request stops seeing the
   audio the moment a non-empty `tools` array is attached - 10/10 explicit
   "you haven't provided an audio file". This is the mechanism the 2026-07-25
   report ranked first on plausibility ("a chat template that switches to a
   tool-calling path can stop honoring `images`") and never tested at a
   sample size that could show it. Builtin tools have been registered
   unconditionally since v1.6.1, so every engine turn carries them.
2. **The system prompt.** A vs H: adding the Jarvis persona system message to
   the *proven-good* transcription instruction drops it from 10/10 to 0/10,
   with no tools involved.
3. **The current-turn wording.** A vs G: with nothing else in the request,
   swapping the transcription instruction for the voice turn's own text drops
   it from 10/10 to 0/10.

The engine's dialog path carries all three at once, which is why it is the
worst configuration in the product for actually hearing the user, while
`TranscriptionService` - a single bare user message, no system prompt, no
tools (`journal/transcription.py`) - is cell A and works.

Fragility, not a hard switch: longer, clearer recordings still get through
the same suppressed configuration (the three known-good July wavs, 2.7-6.6 s,
answered on-subject through the full engine framing in
`manual/manual_check_audio_comprehension.py`), while short ones do not. That
is the "short questions stopped working" symptom, and it is a *threshold*
effect on top of the suppression, not a separate audio defect.

## Secondary observation: silence padding moves a marginal clip

Kept from the superseded draft, still valid as an intervention and still
unexplained as a mechanism. On
`journal/20260901-232544-9826cf/utterance-20260901-232552-0001.wav` (1.30 s),
transcription-instruction cells, 10 runs each: as recorded 0/10 correct; with
0.3 s of appended digital silence 10/10; level-normalized to -12 dBFS without
added silence 0/10; threshold sweep 0.00 s 0/10, 0.10 s 0/10, 0.15 s 10/10,
0.20 s 8/10, 0.25 s 10/10, 0.30 s 10/10.

What that does **not** support is the draft's causal claim. Trailing-silence
length does not predict which clips fail: a July clip with a 0.140 s tail is
9/10 as recorded while the 0.114 s-tail clip above is 0/10, two clips of
identical duration and byte size; and a 2.70 s July clip with a 0.093 s tail
works. Padding shifts a marginal clip across the fragility threshold; it does
not identify what makes a clip marginal.

## What this supersedes

- **The flush-cut/padding root cause** written earlier the same night. Wrong
  attribution; the padding numbers survive, the explanation does not.
- **The 2026-07-25 report's "Fourth experiment" puzzle** ("Да, я вас отлично
  слышу" is producible without comprehension, so the criterion is worthless).
  Now explained: in the dialog configuration the model frequently has no
  usable audio at all, so refusing, bluffing and fabricating are one state -
  which of the three surfaces depends only on what the accompanying text
  invites.
- **The 2026-07-25 report's "First/Second experiment" clearances of tools and
  wrapping.** Those runs used four requests total, and this failure is
  probabilistic per request. The tool clearance in particular is now
  contradicted at n=10.

**Methodological rule this bug establishes: nothing about this model's audio
handling may be concluded from fewer than 10 runs per condition.** Across one
evening, n=1 to n=3 sampling produced three mutually contradictory "controlled"
results, including two from the agent within the same hour.

## Temporary decision

No fix on `fix/voice-turn-audio-framing`. That card is scoped to the
current-turn text, its change is measured and independent, and the request
shape is a different and larger question. The wording card ships or does not
on its own merits; this gets its own card once the direction below is chosen
by the owner.

Workaround available today: the explicit transcription action on a recorded
voice turn (Journal -> the turn's menu -> generate transcript) is cell A and
returns the real words.

## Future considerations and boundaries

- **Do not attach tools to a voice turn's first pass.** The cheapest
  intervention with a measured effect: a turn carrying audio omits `tools`,
  and a tool-using follow-up pass (which no longer needs the audio, since the
  model has already answered from it) may carry them. Needs a decision about
  what happens to a voice turn that genuinely needs a tool.
- **The system prompt suppressing audio on its own (cell H) is the harder
  half** and has no cheap fix: the persona is what makes Jarvis Jarvis.
  Options worth measuring before choosing: a shorter system message on
  audio-carrying turns, moving the persona into the user turn, or a two-pass
  shape where a bare cell-A pass transcribes the audio and the dialog pass
  answers the resulting text (which would make voice turns as reliable as the
  transcription action, at the cost of a second request per turn).
- The two-pass option deserves special attention because it converts an
  unreliable capability into a reliable one using a path that is already
  measured at 10/10, and because it would make the recorded transcript a
  by-product of every voice turn rather than an explicit user action.
- Everything above is measured against one model
  (`gemma4-12b-jarvis-free-mm:latest`); the owner separately confirmed the
  same failure on `gemma4:12b-it-q8_0`, so it is not a quantization artifact.
  Whether it is specific to this model family is untested.

## 2026-09-02 measurement: what the suppressor actually is

Prompted by the owner's hypothesis that `tools` do not break audio as such,
but switch the request onto a template path that expects media in a different
field. Same clip and method as above, 10 runs per cell, payloads built through
`OllamaBackend.build_payload` so every cell carries the live config exactly as
the engine sends it.

**The hypothesis is refuted in its specific form - there is no other field.**

| request | heard |
|---|---|
| `images`, no tools | **10/10** |
| `images` + tools | 0/10 |
| `audio` field instead of `images`, no tools | 0/10 |
| `audio` field + tools | 0/10 |
| both `images` and `audio` + tools | 0/10 |
| no media at all + tools | 0/10 |

Ollama has no `audio` message field: the `audio`-only cells answer identically
to the no-media-at-all cell, so the field is silently dropped. And with `tools`
declared, the `images` cell is likewise indistinguishable from sending no media
- same refusal wording, same rate.

The OpenAI-compatible endpoint does carry audio as audio
(`/v1/chat/completions`, `input_audio` content part): 3/10 heard, and the
misses are Russian near-misses rather than refusals, so the model is decoding
something. It is worse than the native `images` path, and it collapses to 0/10
the moment tools are attached - so a different transport does not escape the
suppression either. (An audio `data:` URI passed as `image_url` is rejected:
HTTP 400 `invalid image input`.)

**The suppression is specific to audio, and one trivial tool is enough.**

| request | result |
|---|---|
| image (PNG) + no tools | 10/10 described correctly |
| image + 2 realistic tool declarations | 10/10 described correctly |
| image + 1 no-op tool | 10/10 described correctly |
| audio + no tools | 10/10 heard |
| audio + 1 no-op tool (name `noop`, description "Does nothing.") | 0/10, 10/10 refusals |

Images are untouched by tools. Audio dies from a single no-op declaration, so
this is the tool-calling template path, not prompt-token volume, and not media
in general. **A fix may keep tools on screenshot turns; only audio turns need
them gone.**

**Dropping tools is not sufficient - peeling the engine turn apart:**

| request (all with the audio attached) | heard |
|---|---|
| full engine shape: system + time context + voice text + tools | 0/10 |
| minus tools | 0/10 |
| minus tools and time context | 0/10 |
| minus tools and system prompt (time context + voice text) | 0/10 |
| voice text alone | 0/10 |
| system prompt + transcription instruction | 0/10 |
| transcription instruction alone | **9/10** |

**What in the accompanying text decides it - both language and task, and they
compound:**

| user text, no system message, no tools | heard |
|---|---|
| English "Transcribe this recording verbatim..." | **10/10** |
| Russian translation of the same instruction | 2/10 |
| English "Listen to this recording and answer what is said in it." | 4/10 |
| Russian `VOICE_PLACEHOLDER_TEXT` | 0/10 |

And the system message degrades it by its mere presence, before any content:

| system message | heard |
|---|---|
| none | **10/10** |
| empty string | 3/10 |
| "Ты - Джарвис, голосовой ассистент." | 2/10 |
| the full Jarvis persona | 0/10 |

## The model was an uncontrolled variable, and the earlier tables are mislabeled

`config.ui.toml` overrides `[backend].model` from `config.toml`. It currently
holds `gemma4:12b-it-q4_K_M`, so every measurement here that loaded settings
ran on that model, not on the `gemma4-12b-jarvis-free-mm:latest` named in
`config.toml` and in this report's original header. Which model last night's
tables actually used cannot be recovered - the effective value at the time is
recorded nowhere. **Everything in the 2026-09-02 sections above is
`gemma4:12b-it-q4_K_M` unless a row says otherwise.**

The two models differ sharply on the best-case cell:

| model | transcription instruction alone | + 1 no-op tool |
|---|---|---|
| `gemma4:12b-it-q4_K_M` (stock) | **10/10** | 0/10 |
| `gemma4-12b-jarvis-free-mm:latest` (the `config.toml` model) | 0/10 | 0/10 |

That looked like the custom model being deaf. It is not: its Modelfile bakes a
long English SYSTEM prompt, which Ollama injects whenever the request sends no
system message of its own. Overriding it with an *empty* system message lifts
it to 4/10, the misses now near-miss transcripts rather than refusals - it
hears the audio. So the custom model's apparent deafness is the same
system-prompt suppression measured above, arriving through the Modelfile
instead of through the request. The same effect from the other side: adding an
empty system message to the stock model drops it from 10/10 to 3/10.

## Standing conclusion

One mechanism, several doors into it: **the model attends to attached audio
only in a nearly bare request, and every layer of dialog structure placed
around that audio costs attention** - a baked or explicit system message
(empty ones included), tool declarations (one no-op is enough), an instruction
in Russian rather than English, and asking it to *answer* rather than to
*transcribe*. Each is independently costly; the engine's voice turn stacks all
of them, which is why it is the worst configuration in the product for hearing
the user. Images are unaffected by any of this.

The only configuration measured reliable is the bare one the product already
ships: a single user message carrying the English transcription instruction and
the audio, no system prompt, no tools - `TranscriptionService`
(`src/jarvis/journal/transcription.py`).

**This makes the two-pass option the recommended direction**, and no longer one
of three: pass 1 is exactly that already-working request and yields the words;
pass 2 is an ordinary text dialog turn over the transcript, needing no audio
and free to carry the persona, the time context and every tool. It converts an
unreliable capability into a measured-reliable one, and makes the transcript a
by-product of every voice turn instead of an explicit user action. Cost: a
second request per voice turn, and the transcription pass's own error rate
becomes the turn's error rate.

Open, and deliberately not chased tonight: whether a shorter or English-side
system prompt would be enough on its own (the gradient above says it would help
but not restore 10/10), and whether any of this is specific to the gemma4
family.
