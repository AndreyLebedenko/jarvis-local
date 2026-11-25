# Story: Silero v5 emphasis markers in spoken text

**Status:** Approved 2026-11-25 with decisions A, B, C as recommended. Branch
`feat/silero-emphasis-markers`. Task 1 done (pure module `audio/speech_emphasis.py`,
not wired anywhere yet; runtime behavior unchanged). Next: task 2.
**Created:** 2026-11-25
**Predecessors:** `tasks/done/task-silero-tts-v5-6.md` (the `v5_6_ru` route).
**Executor profile:** task cards name files, precedents, and boundaries
literally and state up front what they must NOT touch.

## Origin

The Silero v5 announcement (Habr, "Теперь silero-tts v5 на русском языке умеет
задавать вопросы", author snakers4, https://habr.com/ru/articles/1015942/) says
the intonation centre of a question can be marked with asterisks:
`Организаторы *прислали* нам электронные билеты?`.
The article names `v5_4_ru`, says the marker is strongly recommended for
general (yes/no) questions, optional for the other question types, and that
emphasis in statements is only planned. It does not say what an unpaired or
doubled marker does, and does not mention `v5_6_ru`.

## Spike results (owner, by ear, 2026-11-25)

Script: `manual/manual_check_silero_v5_question_intonation.py`
(`--round 1|2|3`). Model `v5_6_ru`, voices heard: xenia, eugene, baya, aidar.
Sentences: one general question in round 1, three general questions in rounds 2
and 3 (round 3 is the same three as statements). One listener; treat as
evidence, not as a measurement.

- Voices: xenia and eugene convey the emphasis best, baya is acceptable, aidar
  is the weakest.
- Every variant with asterisks changes the intonation. The marker works.
- One marked word in a question: good rise and fall, but "too correct"; people
  do not usually speak like that.
- One unpaired asterisk, or one pair around two words: sharp rise, smooth fall,
  no emphasis.
- Two marked single words in a question, "a meaningful word + the last word":
  the liveliest and most natural variant, but only when the first word is the
  natural focus. `Твой брат всё ещё *живёт* в *Лондоне*?` is natural;
  `*Твой* брат всё ещё живёт в *Лондоне*?` is not, because nobody asks it that
  way. So the choice of the first word is semantic, not structural.
- Statements: the markers work and are not excessive, but one marked word only.
  Two marked words make the statement sound like a question.

Not tested: special (wh-) and alternative questions as a pair pattern (round 1
had them, without a verdict), exclamations, several sentences in one synthesis
call, the interaction with `put_accent` / `put_yo`, a literal `**bold**`, and
whether a plain asterisk is silent on `v3_1_ru` (assumed: its symbol set drops
it).

## User-facing goal

When the caller of the MCP `speak` tool writes `spoken_text` with markers, the
Silero v5 voice stresses the intended words and the question or statement
sounds natural. Nothing else changes: all other speech is unmarked and sounds
as before.

## Design (proposed)

1. **Pure normalizer** for one sentence, TDD, no I/O. Rules from the spike:
   - question (`?`): keep at most two marked single words; keep the first and
     the last marker found;
   - statement (anything else): keep at most one marked single word;
   - drop unpaired asterisks and markers around more than one word (the spike
     heard a rise with no emphasis).
2. **Strip function**: removes every `*` marker. Piper, `v3_1_ru`, and any
   sentence that is not trusted use it.
3. **Provenance.** Only `spoken_text` written by the caller
   (`SpeechOrigin.CALLER`, `dialog/voice_guide.py`) may carry markers. Canvas
   read verbatim, the local guide pass, Gemma answers, and the personal proxy
   carry Markdown asterisks by accident and must be stripped. The engine
   cannot tell the origin, so the decision is made before the text reaches it.
4. **Capability** on the Silero route, so the runtime is unchanged unless the
   owner turns it on (see decision A).
5. **Instruction for the caller**: one short rule in the `speak` tool
   description (`speak_tool_description`, `mcp_mode/server.py`): in a question
   mark the meaningful word and the last word, in a statement one word.

## Decisions (owner, 2026-11-25)

- **A. Default.** An explicit opt-in key on the Silero route, default off, so
  v3_1_ru and every existing config behave as today. (Rejected: on
  automatically for `v5_*_ru` models.)
- **B. Scope.** `spoken_text` from the caller only. Local-model markers are out:
  the local prompt forbids Markdown and a 12B model will not pick a semantic
  focus reliably.
- **C. Voice.** Document `xenia` and `eugene` as the voices that carry
  emphasis; `aidar` stays selectable.

## Ordered task cards

1. **Emphasis normalizer and stripper** - new pure module under `src/jarvis/audio/`
   with tests; the rules above; no wiring.
   Card: `tasks/done/task-silero-emphasis-1-normalizer.md` (completed 2026-11-25).
2. **Silero capability and engine boundary** - the route key (decision A),
   Silero v5 keeps normalized markers, every other engine and every untrusted
   path strips them; tests with stub engines.
3. **Provenance wiring** - mark caller `spoken_text` as trusted in the
   voice-guide path, strip everything else; check that `app.py` and the personal
   proxy path are not changed and that `speech_cleanup.py` still removes Markdown
   emphasis from untrusted text.
4. **Caller instruction and docs** - `speak_tool_description`, `config.example.toml`,
   `PROJECT.md` (verified facts from the spike, the decision), README mention.
5. **Manual verification** - one handoff through the real MCP `speak`: a question
   and a statement with markers on xenia and eugene; the same canvas in verbatim
   mode with `*italic*` and `**bold**` must sound unchanged; check `**bold**`
   and `put_accent`/`put_yo` interaction on `v5_6_ru`.

## Boundaries

- No new network access; the runtime stays local (`CLAUDE.md`, tooling note 2).
- No change to the Gemma response path, the proxy answer path, or SSML.
- No automatic marker placement; the focus word is a semantic choice.
- The `intensity` parameter from the announcement is not used.
- The spike script and its tests stay as the record of the experiment.

## Acceptance criteria

- With the capability on, caller `spoken_text` such as
  `Твой брат всё ещё *живёт* в *Лондоне*?` reaches a Silero v5 engine with
  exactly the normalized markers and sounds as in the spike.
- With the capability off, or on any other engine, no `*` reaches the engine.
- Text from any untrusted origin never reaches a Silero engine with a marker.
- Rules: a question keeps at most two single-word markers, a statement one;
  unpaired and multi-word markers are removed.
- Automated tests cover the normalizer, the stripper, and the engine boundary;
  the audible check is the manual handoff of task 5.
