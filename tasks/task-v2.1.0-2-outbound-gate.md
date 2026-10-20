# Task v2.1.0-2: outbound payload builder and gate

Status: Open.

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

- [ ] Every outbound request is built through the single builder; a test fails when
      an input source is added or when a non-listed text reaches the payload.
- [ ] Each pattern category blocks on a positive fixture and passes a negative one
      (ordinary numbers, dates, short digit groups, plain prose).
- [ ] A mapping original present exactly, or in another declension, blocks; a
      placeholder-only payload passes.
- [ ] A topics-file line inside the payload blocks; an empty topics text blocks
      nothing.
- [ ] A block carries category and position only; no value appears in findings,
      their `repr`, or exceptions (a test per category).
- [ ] Gate errors fail closed.
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green.
