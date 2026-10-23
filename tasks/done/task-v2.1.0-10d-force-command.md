# Task v2.1.0-10d: The /force command

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 10d. Origin: the owner's proposal of
2026-10-24 after two false refusals of harmless requests by the local sanitize model
(`bad_placeholder` on "what is a relay"; a refusal with the reason `DATE` on "what happened
with the internet on Wednesday, 21 October this year?" with no topics file present). Follows
`tasks/done/task-v2.1.0-10c-proxy-input-dock.md`.

## Summary

Introduce the notion of a command in the typed request. The first command is `/force`, short
form `/f`:

```
/force What happened with the internet on Wednesday, 21 October this year?
```

It sends this one message to the external model without the local model stages (the
transcript check, the sanitize model, the topics refusal, the confirmation question), once and
only this message. The deterministic outbound gate still runs.

## Boundary

The typed-request intake, the pipeline branch for a forced request, the sent block and
Journal marking, the dock help text, strings, tests, `PROJECT.md` and a short handoff. No
change to the stages themselves, the gate rules, the spoken path, the external client or
the restoration stage. No other command. No setting. No live call by the agent.

## Owner decisions (2026-10-24)

1. `/force` bypasses the **local model stages only**: transcript check, sanitize (with the
   topics refusal) and the confirmation question. The **deterministic gate stays** (phone,
   card, IBAN, e-mail, key, password and the other detectors, and its topic-phrase check as
   it is today). A forced request blocked by the gate is not sent and posts the usual
   content-free block notice.
2. The command applies to **typed text only** (the Journal dock). A spoken request is never
   forced.
3. **One message, once.** The command does not switch any mode; the next request goes the
   normal way.

## Design

**Command syntax.** A typed request whose first token is `/force` or `/f` (lowercase, the
token ends at whitespace or the end), followed by the request text. Leading and trailing
whitespace around the command and text is trimmed. An empty text after the command posts a
fixed notice ("nothing to send") and sends nothing. A leading token that looks like a command
(`/` followed by letters) but is not known posts a fixed notice ("unknown command") and sends
nothing, so a typo such as `/forse` is visible and not sent as an ordinary request. A
leading slash followed by anything else (a path such as `/etc/hosts`, or a lone `/`) is an
ordinary request. The parser is a small pure module with its own tests; it knows the command
table (a mapping name -> handler tag) so that further commands are an addition, not a
rewrite.

**Forced flow.** Instead of check and sanitize the pipeline builds the payload directly from
the verbatim text: `build_outbound_payload(DEFAULT_SYSTEM_PROMPT, text)` with an empty
mapping, then the existing gate with `GateContext(mapping={}, topics_text)`, then the
existing dry-run stop or send, restoration (nothing to restore, sentences pass through) and
presentation. Dry run still applies: a forced request in dry run is not sent and posts the dry-run
state. The service posts the heard block without a question and does not start the
confirmation exchange.

**Visibility.** The "sent" block (Status ribbon and Journal feed) and the stored
`proxy_sent` record carry a "forced" marker, displayed as "FORCED: sent without the local
checks" (en/ru) next to the text that went out. The heard record is stored as for any typed
request. The Journal's provenance and exclusions are unchanged. The dock shows a short help
line in the proxy mode: "`/force` text sends one message without the local checks" (en/ru).

**Privacy.** The gate still protects against structured identifiers, but a forced request
may contain names and other personal text, since the model that finds them is skipped; this is
the owner's explicit trade-off and is stated in `PROJECT.md` (the contract paragraph) and in
the handoff. The forced text appears only in the chat and the Journal as the heard and sent
text, never in logs, exceptions or `repr`.

## Required behavior

1. Everything in Design, written test first (each test before the code it covers).
2. Tests: the parser (`/force x`, `/f x`, case, extra whitespace, no space, empty text,
   unknown command, path-like slash text, the word `force` without a slash, a request that
   merely contains `/force` later); a forced request skips check, sanitize and confirmation
   (fakes record that they were not called) and sends exactly
   `DEFAULT_SYSTEM_PROMPT` plus the verbatim text; the gate still blocks a phone number and a
   card number in a forced request (nothing sent, notice posted); dry run does not send a
   forced request; a spoken request never takes the forced path; a second normal request is
   not forced; the sent block and the stored record carry the marker and the Journal
   exclusions still apply; the answer is restored and presented as usual; no text in `caplog`;
   the strings in en and ru; the dock help line; the 9a, 9b, 10, 10b, 10c invariants (full
   suite). Mutation checks by the developer on: skipping the gate for forced, forcing a
   spoken request, keeping the mode on after one message, dropping the marker.
3. `PROJECT.md` and the story are updated in the same change: the privacy contract now says
   what leaves the machine, with the one explicit exception.
4. A short self-sufficient handoff (`manual/personal-proxy-force-handoff.md`, passing
   `tools/check_handoff_self_sufficiency.py`): the command, a request that the local model
   refuses falsely, a request with a phone number that the gate still blocks, dry run with
   force, the unknown command, the marker.

## Acceptance criteria

- [x] `/force` and `/f` send one typed message without the local model stages; the gate
      still applies; dry run still applies.
- [x] Spoken requests are never forced; the next request is normal.
- [x] The forced message is visibly marked in the sent block and in the Journal record.
- [x] Unknown commands and an empty text send nothing and say so.
- [x] The privacy contract text in `PROJECT.md` states the exception.
- [x] `python -m pytest`, `ruff check` and `ruff format --check` are green.


## Outcome (2026-10-24)

Accepted by the owner. Developer subagent; one independent review round (15 mutations by the
developer and about 20 by the reviewer; no leak, the gate always runs, no state leakage,
no way to force from a spoken request, a typed answer to a pending question, or any other
source). Fixed after review, test first: an invisible-only text after the command now gets
the empty-command notice (a surviving mutant), the unknown-command notice says how to send
the text as plain text (a word before the slash), `PROJECT.md` and the handoff state what the
gate does not cover, the stale story bullet is reworded, the handoff has an optional
"spoken is never forced" part. Suite: 5785 passed, 1 skipped; ruff clean.

Built: `request_commands.py` (a pure parser with a command table; `/force` and `/f`, lowercase,
typed text only; any other `/letters` token is an unknown command, any other leading slash is an
ordinary request), `verbatim_result.py`, the forced flow in `request_pipeline.py` (no check,
no sanitize, no confirmation; `build_outbound_payload(DEFAULT_SYSTEM_PROMPT, text)` with an
empty mapping; the same gate with the topics text; dry run still applies), `Heard.forced`,
`SentBlock.forced`, `DryRunBlock.forced`, `metadata.forced` on the stored `proxy_sent`,
the "FORCED: sent without the local checks" marker in the Status ribbon and the Journal feed,
the dock help line, new notice kinds `UNKNOWN_COMMAND` and `EMPTY_COMMAND`.

Privacy statement (in `PROJECT.md`): a forced message carries only the system prompt and the
text as typed; the gate recognises structured identifiers in their usual written forms; names,
addresses in free text, spelled-out or obfuscated numbers and e-mails are not recognised
and nothing else catches them in a forced request. That is the owner's explicit trade-off.

Known limits: for an unknown or empty command the dock has already cleared the text box and
shown "Sent" (the typed text is lost; fixing it needs a synchronous rejection from the
transport); `/etc` alone is an unknown command (`/etc/hosts` is ordinary); a typed `/force`
text while a question is pending is taken as the answer; cancellation of a forced request
mid-stream uses the shared path and has no dedicated test.

Follow-up: task 10e (false refusals of the local sanitize model).
