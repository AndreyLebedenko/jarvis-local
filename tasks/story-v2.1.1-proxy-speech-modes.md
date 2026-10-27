# Story v2.1.1: Personal proxy speech modes (Text, Voice, Text+Voice)

**Status:** Approved by the owner, 2026-10-27 (version v2.1.1, second-pass timeout 30 s,
default mode as today). Tasks 1-4 done.
**Created:** 2026-10-27
**Predecessors:** `tasks/story-v2.1.0-personal-proxy.md` (delivered),
`tasks/done/story-v1.9.0-response-modes.md`.
**Executor profile:** same as story-v2.1.0. Task cards name files, precedents, and
boundaries literally and state up front what they must NOT touch.

## Origin

Live run, 2026-10-27. The spoken answer of the external model contains Markdown and Roman
numerals read badly ("asterisk asterisk", "Roman twenty"). The main Jarvis already solves
this by response mode: the text contract changes with how the text will be used (screen
first, script for TTS first, or both). The proxy ignores the response mode and speaks every
restored sentence verbatim.

## User-facing goal

The proxy follows the same response-mode switch as the main Jarvis (`text`, `voice`,
`text_voice`, hotkey `[hotkeys].response_mode_toggle`, Status Console control). Speech is on
in every mode when TTS is enabled; the modes differ in the text contract:

- **Text** - as today: the restored answer is shown and spoken as received, sentence by
  sentence. Nothing changes.
- **Voice** - the answer is written to be spoken, and cleaned before TTS:
  (a) a voice contract is added to the outbound system message, so the external model
  writes prose without Markdown, lists or tables;
  (b) a deterministic cleanup is applied to every sentence before TTS (Markdown markers,
  links, Roman numerals in unambiguous contexts, for example "XX век"), as a guarantee for
  what the model still gets wrong. Speech starts as early as in Text.
- **Text+Voice** - the shown text is the answer as received (canvas). After the whole answer
  is received and restored, the local model renders the spoken version with the existing
  `text_voice` contract (a retelling of the form, no new facts, references to the screen
  allowed). The spoken version is cleaned by the same deterministic cleanup. If the local
  pass fails or times out, the cleaned canvas is spoken instead.

## Revisions of earlier settled items (owner, 2026-10-27)

- Story v2.1.0 settled constraint 8 ("Output is `text_voice`") described the proxy as
  showing and speaking; it is now read as today's behavior = mode Text, and the output
  follows the switch.
- Story v2.1.0 boundaries "Switching modes without a restart" and "Any change to mode
  1/2/3" no longer apply to the proxy. `--mcp-mode` and the main Jarvis modes are unchanged.
- The outbound payload is no longer "only the fixed system prompt and the sanitized text":
  in Voice mode the system message carries one more paragraph, a fixed contract of Jarvis's
  own (no user data). `PROJECT.md` statements about this are amended by task 4.

## Design decisions (proposed here, confirmed by card approval)

1. **One switch.** The proxy reads the live mode once at the start of each request and
   latches it for that request (as `app.py` does for turns). Needed: `SET_RESPONSE_MODE`
   verdict for `PERSONAL_PROXY` becomes ALLOWED (`core/run_mode.py`), the hotkey listener is
   bound in `_personal_proxy_background_work` (`app.py`), `ProxyHost` gets a mode getter
   (`app_proxy.py`, `startup/proxy_assembly.py`).
2. **Text sends the byte-identical outbound system prompt** (`DEFAULT_SYSTEM_PROMPT`);
   many tests pin this.
3. **Voice contract.** A fixed English paragraph appended to `DEFAULT_SYSTEM_PROMPT` on the
   same paragraph (no blank line: `sent_view.request_after_default_system_prompt` relies on
   it), free of digit runs and address-like words (the gate scans the system message), and
   not combined with `speech_language_*` directives (they conflict with "Answer in the
   language of the request"). `sent_view` and the UI fold the known voice suffix like the
   default prompt.
4. **Deterministic cleanup is a pure module** applied inside the speech path, after
   `strip_speech_control_tags`, to Voice sentences and to Text+Voice output. Roman numerals
   are converted only in unambiguous contexts (a numeral followed by a word such as
   "век"/"веке"/"века"; the case form is taken from that word); ambiguous tokens (`I`, `V`,
   `X`, `MIX`) are left alone. Arabic digits are already spelled out by the Silero adapter
   (`audio/tts_silero.py`); the cleanup does not touch them.
5. **Text+Voice second pass** uses the local `CheckBackend` seam (`ChatRequest` with
   `system` = the `[generation.spoken_derivative].prompt` contract, via
   `dialog/canvas_speech.compose_canvas_speech_messages`; `prompt` = the restored answer).
   Not the Orchestrator derivative pass (the proxy service imports no application module).
   A new `[personal_proxy]` timeout key with validation; failure or timeout falls back to
   cleanup of the canvas. An interrupt speaks nothing.
6. **Journal.** The canvas stays the `proxy_answer` text. The spoken version is stored only
   as `metadata["spoken_derivative"]` (locator-only, never retrieval/memory). The mode used
   is recorded on `proxy_answer` metadata (pairs with
   `tasks/bug_reports/2026-09-12-journal-turn-does-not-record-response-mode-or-reasoning-level.md`).
   The mapping and the raw external answer are still never written.
7. **Incomplete answers.** The Journal write of a failed or interrupted stream no longer
   waits for speech (`tasks/bug_reports/proxy-incomplete-answer-journal-written-after-speech.md`);
   done before the presenter is reworked for Text+Voice.

## Honest limits (carried into docs and UI wording)

- The voice contract and the second pass are requests to a model, not guarantees; the
  deterministic cleanup is the only guarantee, and it covers Markdown and unambiguous Roman
  numerals only.
- Text+Voice starts speaking only after the whole answer and the local pass: more latency
  than Text and Voice. The microphone stays paused for that time.
- A table or a formula is read as sentences by the model in Text+Voice; in Voice it is
  whatever the external model wrote.

## Boundaries (explicitly out of scope)

- The sanitize pass, the check pass, the gate rules, the restoration stage and the public
  names file.
- Main Jarvis modes 1/2/3, `--mcp-mode`, and `[tts].language_mode` behavior in the proxy
  (the proxy keeps charset routing).
- Compression or commentary in Text+Voice beyond the existing contract.
- A timeout redesign of the external call
  (`tasks/bug_reports/proxy-external-deadline-total-and-undiagnosable.md`).

## Task-card sequence

1. **Speech cleanup module.** (Size: S-M. Done 2026-10-27, `tasks/done/task-v2.1.1-1-speech-cleanup.md`.) Pure function(s): Markdown markers, links, list
   markers, Roman numerals in unambiguous contexts; unit tests by examples from the owner's
   runs. No wiring.
2. **Journal write of an incomplete answer does not wait for speech.** (Size: S. Done 2026-10-27, `tasks/done/task-v2.1.1-2-incomplete-answer-journal.md`.) Fix in
   `answer_presenter`/`journal_writer`, with a failing-stream test and a held speaker.
3. **Proxy follows the response mode.** (Size: M. Done 2026-10-27, `tasks/done/task-v2.1.1-3-proxy-follows-response-mode.md`.) Verdict, hotkey, `ProxyHost` getter,
   per-request latch, mode recorded in Journal metadata, Status Console control enabled,
   amend `PROJECT.md` and `tests/test_personal_proxy_run_mode.py`. Behavior in all modes is
   still Text.
4. **Voice mode.** (Size: M. Done 2026-10-27, `tasks/done/task-v2.1.1-4-voice-mode.md`; the cleanup also expands abbreviations, approved by the owner.) Outbound voice contract, `sent_view` fold, gate test of the
   longer system message, cleanup per sentence in the speech path, docs.
5. **Text+Voice mode.** (Size: M-L.) Buffered answer, local second pass, timeout key,
   fallback, `spoken_derivative` metadata, tag stripping of the output, docs.
6. **Docs and release verification.** (Size: S-M.) README (EN, RU), `PROJECT.md`, handoff
   with human-run steps for all three modes (live model, TTS, hotkey).

## Open points for the owner

- Decided 2026-10-27: version v2.1.1.
- Decided 2026-10-27: the proxy default mode equals today's behavior for an unchanged
  config; task 3 reads the `[response].mode` default and reports it before wiring.
- Decided 2026-10-27: second-pass timeout default 30 s; task 5 measures a long answer.

## Acceptance criteria

- [ ] The proxy follows the switch (hotkey and Status Console) per request.
- [ ] Text: outbound payload and speech byte-identical to v2.1.0.
- [ ] Voice: contract in the outbound message, cleanup before TTS; "**" and "XX век" are
      not read as in the owner's run (human-run, live).
- [ ] Text+Voice: spoken text comes from the local pass; fallback to cleanup works; the
      canvas stays the Journal text and the spoken version is metadata only.
- [ ] An incomplete answer reaches the Journal without waiting for speech.
- [ ] README (EN, RU), `PROJECT.md`, and the handoff name the modes and their limits.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check`, and
      `tools/check_handoff_self_sufficiency.py` are green.

## Stop conditions

- Stop if the gate blocks the voice contract or the sent view cannot fold it without
  weakening the default-prompt check.
- Stop if the response-mode hotkey or the bus handlers are not live in proxy mode as
  expected (task 3 verifies first).
- Stop if Text+Voice latency makes the mode unusable on a long answer; report the figures.
