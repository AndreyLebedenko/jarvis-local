# Task v2.1.0-2: outbound payload builder and gate

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 2 (Size: M), and its design
decisions "Gate scope is the whole outbound payload", "A block reports category and
position, not the value", "The topics file is local-only", "Nothing but the
sanitized request goes out". Follows task 1 (`personal_proxy` package exists).

## Summary

Pure logic, in `src/jarvis/personal_proxy/`: the single function that builds the
outbound chat payload, and the deterministic gate that runs on its output. No
model, no HTTP, no config reading (callers pass values in).

## Owner decisions (2026-10-20, planning questions of this task)

- The mapping-original check uses the prefix heuristic of the spikes: promote
  `tokenize` and `stem_present` (declension-tolerant stem match, constants
  `MIN_STEM_LENGTH`, `STEM_ENDING_LENGTH`) from `manual/personal_proxy/text.py`
  into `src/jarvis/personal_proxy/` and keep the same behavior. The `manual/`
  code is left as it is (spike records stay reproducible); the new module does not
  import from `manual/`. No pymorphy3.
- The system prompt is an input of the builder (a typed source) and task 2 supplies
  one minimal default constant: answer in the language of the request; keep
  placeholders such as `<PERSON_1>` exactly as written. The text is refined by
  tasks 6 and 9; the gate checks whatever it receives.

## Boundary

In scope:

1. **Builder** (one public function, e.g. `build_outbound_payload`). Inputs are an
   explicit, closed set: the system prompt, and the sanitized request text. Output
   is a payload object (OpenAI-style `messages`: system, user) that is the only
   thing later tasks may send. A test enumerates the builder's parameters and fails
   when a new input source appears (the allowed set is written in the test), and
   a second test shows the payload contains nothing but those two texts (no image,
   history, journal, memory, `--mcp-mode` text field exists to pass).
2. **Gate** (pure function over the built payload plus gate context). Context:
   the mapping (placeholder to original value) and the topics text (may be empty).
   Result: allowed, or blocked with a list of findings. A finding holds a category
   (enum) and a position (message index and character offset range), and never
   the matched value; `repr`/`str` of findings, results, and exceptions must not
   contain it either. Checks, over every message of the payload:
   a. deterministic patterns: e-mail; phone number (international, Russian, with
      common separators); payment card number (13-19 digits, separators allowed,
      Luhn-valid only); IBAN (country prefix, length and mod-97 valid); long digit
      runs (a run of 9 or more digits not matched above, separators allowed);
      API-key-like strings (long high-entropy token, or known prefixes such as
      `sk-`, `AKIA`, `ghp_`, JWT shape); password-like strings (value after
      `password`/`пароль`/`pwd` markers); street-address shapes (Russian street
      markers `улица/ул./проспект/пр-т/переулок/шоссе` followed by a name and a
      house number, and the English equivalents).
   b. each original value of the mapping (and its tokens) must not appear in the
      payload, exactly or by stem (`stem_present`); a short original (under the
      stem minimum) is checked exactly, on token boundaries.
   c. the topics text must not appear in the payload: any non-trivial line of it
      (case-insensitive, whitespace-normalized) found inside a message blocks.
3. Fail closed: a gate error or an unexpected input type is a block, not a pass.
4. Tests with fixtures, including Russian declension cases, a Luhn-invalid digit
   run that must not be reported as a card but as a digit run, and the
   no-value-in-output property for every category.

Out of scope: the sanitize pass, the HTTP client, config changes, wiring into the
application, the Status Console or voice feedback for a block, the restoration
pass. `manual/` is not changed.

## Acceptance criteria

- [x] Every outbound request is built through the single builder; a test fails when
      an input source is added or when a non-listed text reaches the payload.
- [x] Each pattern category blocks on a positive fixture and passes a negative one
      (ordinary numbers, dates, short digit groups, plain prose).
- [x] A mapping original present exactly, or in another declension, blocks; a
      placeholder-only payload passes.
- [x] A topics-file line inside the payload blocks; an empty topics text blocks
      nothing.
- [x] A block carries category and position only; no value appears in findings,
      their `repr`, or exceptions (a test per category).
- [x] Gate errors fail closed.
- [x] `python -m pytest`, `ruff check`, and `ruff format --check` are green.

## Outcome (2026-10-20)

Accepted by the owner after four review rounds (two independent subagent reviewers,
then GLM as the second opinion; each round's confirmed findings were fixed test
first). Suite: 4165 passed, 1 skipped; ruff clean. Code: `src/jarvis/personal_proxy/`
(`payload.py` builder, `gate.py`, `normalize.py` with an offset map, `detectors/`,
`original_values.py`, `topic_lines.py`, `text.py` promoted from the spikes).

Added beyond the card, by review: Unicode normalization before detection (spaces,
dashes, zero-width, NFKC, NFC) with findings mapped back to original offsets; a
20000-character message cap and a topics cap (blocks, GATE_ERROR with a stage, never
exception text); payload constructible only through the builder; system-message
mapping check by whole token only; tokens inside placeholders ignored by the
mapping check.

Documented limits (not defects, to carry into the docs of task 12):

- Names of three letters (Юля, Яна, Лев) do not match other declensions (the
  spike's prefix heuristic, owner decision); transliteration and mixed-script
  homoglyphs pass.
- Unusual e-mail forms (quoted local parts) and separators CGJ, VS16, Hangul filler,
  Braille blank pass; a payload can be forged only by deliberate misuse.
- Passwords are matched after the markers password, pass, passphrase, passcode,
  api key, pwd, парол*; pin, secret, token are not markers (too common as words).
- Blocked on purpose: English "pass", hex strings of key length, digit runs of 9+
  digits (including big numbers in prose), two lines with 4+ digits each and 9+
  in total, "пароль" followed by a line break and an ordinary word.
- Lowercase English addresses are caught only after an address cue or at the start of
  a sentence; Russian addresses need a street marker and a house number.
