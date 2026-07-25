# Task: A debug launch that records what actually went to the model

**Status:** In progress on `feature/debug-mode-gate`. Slice 1 of 4 (the
gate) is implemented and green; slices 2-4 below are not started.

## Implementation slices

1. **The gate** - done, in two layers after a review finding. `--debug`
   without `--status-console` exits 2 from `parse_args()` with a readable
   message, and `run()` itself raises when `debug` is set without a live
   console. The first layer is the friendly error for a person; the
   second is the invariant, because `run()` is an entry point of its own
   and the first version let a caller reach it directly and record
   headlessly. `announce_debug_mode()` writes the WARNING line that says
   privacy is not guaranteed, and cannot run before the refusal.
   Deliberately first of the four: until the gate holds, every later
   slice could be switched on without the banner. Nothing is recorded
   yet, so the flag currently only announces itself.
2. **The per-turn record** - done. Taken in `OllamaBackend.iter_chat()`,
   the one seam every request passes through: plain turns, each pass of
   the tool loop, the forced-final pass, and the warm-up. Recording any
   higher would have missed some of them, which is how the 2026-07-25
   investigation lost the tool-loop follow-ups. `core/debug_transcript.py`
   owns the sink; `begin_exchange()` returns None when nothing is
   recording, so an ordinary run pays one level check and does no
   redaction work. Written in a `finally`, so a call that fails, hangs,
   or whose consumer stops reading still leaves a record - those being
   the cases a transcript is wanted for.
   Three boundaries survived the exception and have tests: the sink does
   not propagate to the root logger, so `jarvis.log` keeps its promise;
   media becomes a kind and a byte count, never base64; and reasoning
   traces stay out, because debug lifts the content rule and not
   PROJECT.md's separate isolation rule for `message.thinking`.
   Verified against the live endpoint, not only MockTransport: one real
   request produced one record carrying the model, options, message list,
   answer, and token counts.
3. **Utterance metrics** at debug level.
4. **The console banner** and the events-panel entry, both languages.
   `announce_debug_mode()` is the seam they join.
**Raised by:** owner, 2026-07-25, after the voice-comprehension
investigation: "вместо того, чтобы включить дебаг и повторить запуск с
полным журналированием всего ввода-вывода, мы занимались
реконструкцией".

## Summary

There is no debug mode. `parse_args()` knows two flags, neither of them
this; `configure_logging()` hardcodes `INFO`; and `src/jarvis` contains
zero `logger.debug()` calls, so a level knob alone would turn on nothing.
Give Jarvis a launch that records the exact model exchange, gate it
behind the console, and say so on screen while it is on.

## What the investigation actually needed

From `tasks/bug_reports/2026-07-25-model-stopped-comprehending-voice-audio.md`,
which took four experiments to reach an answer:

| needed | where it came from |
|---|---|
| the model's answer | journal - worked |
| audio characteristics | computed from journal wavs - worked |
| whether audio was attached | `inputs=audio count=1` log line - worked |
| **the history at request time** | **reading source code** - and this was the answer |
| which tools were attached | reading source code |
| the exact message list | reading source code, then rebuilt in a script |

The bottom three rows are the gap. Everything the engine sends is
invisible after the fact, so a live defect has to be re-derived instead
of re-read.

## Why this is not "add a log level"

The v1.6.4 content rule forbids payload content in either record, and
`README.md` states it to the user as a promise: neither record contains
what you actually said or sent. A debug transcript deliberately breaks
that promise for as long as it runs. So it is designed as an exception,
with the properties an exception needs: off by default, impossible to
enable by accident, impossible to leave on unknowingly, and visible on
screen while active. This is the same honesty axis as the `LOCAL` badge
and the tool panels - a claim the product makes must stay true, or stop
being displayed.

## Design decisions

1. **CLI only, no config key.** `--debug` and nothing in `config.toml`.
   A persisted switch is a privacy exception that outlives the session
   that needed it; a flag dies at the next start. This also keeps it out
   of the Settings form and out of `config.ui.toml`, which the console
   rewrites wholesale.
2. **Requires the console.** `--debug` without `--status-console` exits
   with a message rather than starting. The banner is the consent
   surface; a headless debug run is a recording with nobody told.
3. **Media is described, never embedded.** A dump carries kind, byte
   size, and duration for audio and images, plus the journal path when
   there is one. Base64 in a diagnostic file would multiply its size for
   nothing readable.

## Requirements

- `--debug` flag; `--debug` without `--status-console` exits non-zero with
  a message naming the requirement.
- While debug is on, each turn writes one record containing: the full
  message list as sent (roles and text, including history and the time
  context), a media descriptor per attachment, the tool declarations
  attached, the reasoning level, and the model's complete answer. Tool
  calls and their results belong in the same record, in order.
- Records go under the configured logging directory, separate from
  `jarvis.log`, and are bounded the way the system log is - a debug run
  must not fill a disk either.
- Utterance metrics at debug level for every captured chunk: duration,
  peak dBFS, RMS dBFS, speech level, and noise floor. Today's finding is
  that these separate a comprehended utterance from an unintelligible
  one, and nothing records them.
- The console header shows, in red and unmissable, `DEBUG MODE` /
  `РЕЖИМ ОТЛАДКИ` and `PRIVACY NOT GUARANTEED` /
  `ПРИВАТНОСТЬ НЕ ГАРАНТИРУЕТСЯ`. It sits with the honesty indicators
  (`index.html:22`, the locality badge), so it is on every tab and
  survives a tab switch, and it travels in the state snapshot like
  `data_locality` (`transport.py:367`) so a reconnect still shows it.
- Both string catalogs gain the keys; `tests/test_ui_i18n.py` already
  asserts the two languages stay key-identical.
- A startup log line and one events-panel entry record that debug is on.
- Automated tests: the gate refuses a headless `--debug`; a dump contains
  the message list and no base64 media; the state snapshot carries the
  debug flag; the banner keys exist in both languages; utterance metrics
  are computed from samples without touching hardware.

## Boundary

- Recording only. No new UI beyond the banner, no viewer for the dumps,
  no change to what the engine sends.
- Not a second journal, and not part of the journal. The journal is a
  user-facing surface with an append-only invariant and its own retention
  controls; debug records are a third sink beside `jarvis.log`, existing
  only while the flag is up. Writing request content into the journal
  would put it on a screen the user browses and in files the console
  serves.
- If the record format starts growing features (filtering, redaction
  levels, a viewer), that is a second card, not scope creep in this one.

## Rejected: an always-on ring buffer (owner decision, 2026-07-25)

The alternative considered was an in-memory ring buffer of the last N
turns, always on, written to disk only when something failed - evidence
for the failure that already happened, which is exactly what was missing
during the voice-comprehension investigation.

Rejected, and on the stronger of the two available arguments. The agent's
case was cost ("re-running may be cheap enough"); the owner's is
capability: in normal operation Jarvis must not hold, in memory, content
it promises never to write. A promise that survives only because no code
path chose to dump the buffer is not a promise. This matches how the
product treats every other capability - MCP off means the capability does
not exist, camera off means no frame is captured at all rather than
captured and discarded.

**The accepted cost, stated plainly:** the first occurrence of a defect
is never captured, so every investigation pays one reproduction. That is
a real cost for probabilistic failures - the refusal that started the
voice investigation could not have been reproduced on demand.

**If that ever bites, the answer is replay, not capture.** The journal
already holds the wavs and screenshots a turn was built from, with the
user's knowledge. A debug run able to re-send a recorded turn through the
same request composition gives evidence after the fact while reading only
what the user already keeps, and only when explicitly asked. That is what
the manual scripts did by hand during the investigation. Separate card if
it is ever needed; deliberately not in this one.

## Acceptance criteria

- [ ] `python -m jarvis --debug` without the console refuses to start.
- [ ] With the console, the header carries the red debug and privacy
      warnings in both interface languages, on every tab.
- [ ] One turn of each kind (voice, screenshot, clipboard, typed,
      attachment) produces a readable record of exactly what went to the
      model and what came back.
- [ ] A voice turn's record carries the utterance metrics.
- [ ] No base64 media appears in any record.
- [ ] `logs/jarvis.log` in a normal (non-debug) run is unchanged, still
      carrying no payload content.
- [ ] `python -m pytest` and Ruff are green.
- [ ] Human-run: a debug session, then the same session's records read
      back to confirm they answer the questions the table above lists.
