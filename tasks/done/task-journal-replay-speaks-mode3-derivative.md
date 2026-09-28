# Task: Replay speaks the mode-3 derivative, in the current TTS language mode

**Status:** Completed.
**Source:** Owner request, 2026-09-28 (commit `526c950`): "re-listen to an AI
reply, respecting whether the reply had one text or two"; language handling
requested 2026-09-29.

## Summary

Re-listening to an assistant reply already exists (Play / "Воспроизвести" in
the message meta bar and in the "More actions" menu, story-v1.8.2/v1.8.3).
Two gaps:

1. A mode-3 turn has two texts (the canvas in `event.text` and the spoken
   derivative in `metadata["spoken_derivative"]`). Replay should speak the
   derivative, the text the live turn spoke. Today it re-synthesizes the
   canvas. The retarget was planned in v1.8.2/v1.9.0 and never done
   (`tasks/done/story-v1.9.0-response-modes.md:133,186`).
2. Replay is always charset-routed (PROJECT.md "Architecture: TTS language
   mode": "Journal reply replay stays charset-routed"). It should apply
   `[tts].language_mode`.

## Decisions (owner, 2026-09-28/29)

- A derivative marked `spoken_derivative_interrupted` or
  `spoken_derivative_truncated` is replayed as stored (the partial
  derivative), not replaced by the canvas and not regenerated.
- Replay applies the **current** `[tts].language_mode`, read from the same
  owner the live path reads (`Orchestrator`), not a per-turn record in the
  journal. Accepted consequences:
  - a mode-1 (text) reply cannot be told apart from a mode-2 reply in the
    journal, so with a non-`dynamic` setting a mode-1 reply is replayed in
    one language, although live it was charset-routed;
  - after the setting changes, older replies sound different from how they
    sounded live.

## Design

- Language for a replayed reply:
  `resolve_speech_language(current_mode, text_language(event.text))` - the
  same rule mode 3's live derivative pass uses (`app.py`, derivative pass:
  `text_language(canonical_text)`). `dynamic` gives `CharsetSpeechRouting`,
  i.e. today's behavior. In single-language modes the voice follows the
  first sentence with letters anyway (`SingleLanguageUnitBuffer`), so the
  expected language only affects leading letterless sentences.
- Text for a replayed reply: `metadata["spoken_derivative"]` when present
  (key constant `SPOKEN_DERIVATIVE_METADATA_KEY`, `journal/corpus.py`), else
  `event.text`.
- One pure accessor decides both for an assistant event; the single-reply
  path (`replay_reply`) and the play-from-here path (`SequencePlayer`) both
  use it.
- The choice between `SingleLanguageUnitBuffer` and `SpeechUnitBuffer` is
  shared with `TtsOutput._new_units()` rather than duplicated.

## Current Boundary

- `audio/replay.py`, `audio/tts.py` (buffer-choice extraction only),
  `app.py` (read-only mode accessor on `Orchestrator`, replay wiring),
  tests, `PROJECT.md`.
- No journal schema change, no UI change, no playback-engine change.
- The derivative stays out of retrieval/memory; replay only reads it.

## Acceptance Criteria

- [x] Replaying a mode-3 reply with a stored derivative speaks the
      derivative; a partial derivative is spoken as stored.
- [x] Replaying a reply without a derivative speaks `event.text`.
- [x] Replay segments in one language when the current `[tts].language_mode`
      is `request`, `ru` or `en`, and charset-routes when it is `dynamic`.
- [x] Play-from-here uses the same text and language selection for every
      assistant reply in the sequence.
- [x] PROJECT.md no longer says replay stays charset-routed; the v1.8.2
      "forward seam" note says the retarget is done.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` green.
- [x] Listening check on real replies is a human handoff (speakers).

## Manual Handoff (human-run: speakers, live Ollama)

Prerequisites:

- The Russian and English TTS routes must use different engines, or the
  language steps are not audible: `[tts.languages.ru].engine = "silero"`,
  `[tts.languages.en].engine = "piper"` (check `config.ui.toml`, then
  `config.toml`; the Silero-only default in `config.example.toml` voices both
  languages with one engine).
- TTS on: `[tts].enabled = true`.
- Known open bug: after a spoken turn, Settings "Apply" can stay disabled
  (`tasks/bug_reports/2026-09-28-settings-apply-stays-disabled-after-a-spoken-turn.md`).
  So every settings change below is made right after a fresh start, before
  any exchange.
- Before step 1, note your current "Режим ответа" and "Язык озвучки" values
  in Settings; step 8 restores them. Both are persisted to `config.ui.toml`.

Steps (start Jarvis with `Jarvis.cmd`, `README.md:313-316`; UI labels are
the Russian `strings.js` values):

1. Fresh start. "Настройки" view: set "Режим ответа" to "Текст и голос"
   (`[response].mode = "text_voice"`) and "Язык озвучки" to "Всегда
   русский" (`[tts].language_mode = "ru"`). Press "Применить". Close and
   start Jarvis again (the language mode is restart-to-apply).
2. "Журнал" view: type and send
   `Одним предложением: что такое WebSocket?`. Listen to the live answer
   and wait for it to finish. Expected: the whole spoken answer is in the
   Russian voice, including "WebSocket".
3. On that reply, expand the collapsed "озвучено" block; it holds the
   spoken derivative. Press "Воспроизвести" on the reply. Expected: you hear
   the "озвучено" text, not the canvas above it, and "WebSocket" is in the
   Russian voice, as in step 2.
4. Close Jarvis and start it again. "Настройки": set "Язык озвучки" to
   "Автоопределение языка ответа" (`dynamic`), press "Применить", close and
   start Jarvis again.
5. "Журнал": select the session from step 2 and press "Воспроизвести" on
   the same reply. Expected: the same "озвучено" text, but now "WebSocket"
   (and any other Latin word) is in the English voice.
6. Partial derivative: type and send `Расскажи подробно, как работает
   WebSocket.` As soon as the first spoken sentence has played, press
   `Ctrl+Alt+I` (`[hotkeys].interrupt`, `config.example.toml:211`).
   Expected: the "озвучено" block of that reply says "Прервано хоткеем, не
   закончено." Press "Воспроизвести" on it. Expected: you hear only the
   stored partial text, not the full canvas. (If the interrupt landed before
   any speech, the reply has no "озвучено" block and Play speaks the canvas;
   retry.)
7. Fresh start, restore the two settings noted before step 1, "Применить".

"Воспроизвести" on a reply plays that reply and every later reply of the
session (play-from-here, `SequencePlayer`); in steps 3, 5 and 6 the reply is
the last one, so exactly one reply plays.

Report: pass/fail for steps 3, 5, 6.
