# Task: Generation length cap - `num_predict` per profile, visible truncation

**Status:** Completed. Owner review passed; the human-run handoff
(`tasks/done/task-generation-num-predict-cap-handoff.md`) passed on
2026-09-26. Open question resolved as recommended: no audible truncation
notice in this card.
**Origin:** owner planning dialog, 2026-09-26 ("variant 1": the cap depends on
the request kind; history budget variant (a)). Closes
`tasks/bug_reports/done/2026-09-12-backend-has-no-num-predict-cap-so-only-num-ctx-stops-generation.md`.
**Depends on:** `tasks/done/task-config-generation-profiles.md` (landed
2026-09-26, merge `97e318a`).
**Blocks:** the mode-3b spike (`tasks/done/spike-single-pass-tts-block.md`). Its
runaway criterion and its tag-failure analysis need a bounded generation and
a recorded `done_reason`.
**Kind:** behavior change. Every request gains a length cap, and a turn that
hits it is recorded and shown as truncated.

## Summary

Today no request carries `num_predict`, so a single turn is bounded only by
`[backend].num_ctx`. One measured runaway took 1330 s and 63 843 tokens, and
ended with an empty answer. When a generation is cut off, nothing says so.

This card does two things:

1. **Cap.** Every request gets a `num_predict`, resolved from the
   generation profiles like any other option. The code default is
   `[generation].num_predict = 16384`. This is the value of the current
   `[history].reasoning_generation_reserve_tokens`. The reserve key goes
   away: the dialog profiles' caps now play its role in the history budget.
2. **Visible truncation.** Ollama's `done_reason` travels with
   `ResponseComplete`. A dialog turn that ends with `done_reason = "length"`
   is recorded in the journal as truncated, is labelled as truncated in the
   Journal UI, and leaves a note in the conversation history. That way
   neither the user nor the model reads a cut answer as a finished one.

## Why these numbers

The bug report left the number to the owner and asked for it to be chosen
from the observed distribution, not by eye. The data available on
2026-09-26:

| Source | Kind | n | median | max |
| --- | --- | --- | --- | --- |
| `logs/jarvis-debug.jsonl` (2026-07-26..09-26) | dialog, reasoning off | 12 | 90 | 508 |
| same | dialog, low / medium | 2 / 2 | ~1100 | 2067 |
| same | spoken derivative | 5 | 104 | 326 |
| same | annotation / transcription / warm-up | 1 / 2 / 4 | - | 293 |
| `docs/experiments/v1.9.2-rethink-probe/out/` | reasoning medium | 38 | 2210 | 7025 |
| same | reasoning off | 28 | 110 | 513 |

These samples are small. The probe rows exclude its four runs capped at
`PROBE_NUM_PREDICT=4000`. Those are exactly the four empty answers, and they
were runaways, not long answers: 9.8k to 15.7k characters of thinking and no
content. The probe's analytical cases are the worst legitimate load we have
on record, and the longest of them is 7025 tokens.

16384 is chosen because:

- It is already a verified default. Together with
  `prompt_capacity_tokens = 49152` it gives exactly `num_ctx = 65536`
  (`PROJECT.md`, context budget defaults). The history budget arithmetic
  therefore does not change.
- It sits more than 2x above the longest legitimate answer on record.
- At roughly 87 tok/s (`PROJECT.md`, measured generation speed), the
  worst-case turn falls from about 22 min to about 3 min.

Tighter per-level caps, for example `[generation.dialog.off] num_predict =
2048`, are owner tuning in `config.toml` and not code defaults. The
distribution above is too thin to justify them.

## Design

### Cap

- `GenerationSettings().defaults.num_predict` becomes `16384`. This is the
  only option with a non-`None` code default. It exists because an unbounded
  request is exactly what this card removes, and TOML has no way to write
  "unset". Every other option keeps "unset means omitted".
- Profiles override it like any other option, through the same one-level
  rule: profile, then `[generation]`, then the code default.
- Validation replaces the reserve check.
  `[history].prompt_capacity_tokens + max(num_predict over the four dialog
  profiles) <= [backend].num_ctx`, otherwise `ConfigError`. The error names
  the dialog profile that holds the maximum. Non-dialog profiles are not part
  of the dialog history budget and are not checked against it.
- `num_predict <= 0` in any table is a `ConfigError`. Ollama reads `-1` as
  unlimited, which this card exists to prevent.
- The budget's generation reserve (`ContextBudgetLimits.
  reasoning_generation_reserve_tokens`) becomes that maximum. It stays
  constant across turns because `prompt_capacity_tokens` does not change with
  the reasoning level (variant (a)). The internal field name and the
  `prompt_budget` payload key stay the same: they still mean "room left for
  reasoning plus answer", and renaming them would ripple through the UI and
  the request log for no gain.
- Hard migration: `[history].reasoning_generation_reserve_tokens` is added to
  `MOVED_CONFIG_KEYS`, pointing to `[generation].num_predict` (or a dialog
  profile's `num_predict`). The owner's `config.toml` does not set it, so the
  owner's migration is a no-op. `config.example.toml` loses the key.

### `done_reason`

- `ResponseComplete` gains `done_reason: str | None`. It is taken from the
  `done: true` chunk, and is `None` when the stream ended without one. It is
  not part of `LatencyMetrics`, which describes timing only. The value is
  carried as Ollama sends it; only `"length"` has a meaning in this card.
- `OllamaBackend.chat()` and the tool loop's completion
  (`src/jarvis/dialog/tool_presentation.py`, where it republishes
  `ResponseComplete`) both pass it through. In the tool loop it is the final
  request's `done_reason`.
- `OllamaBackend` logs a warning for any request that ends with `"length"`,
  whatever its kind. This is the only surfacing for non-dialog request kinds
  (see Out of scope).

### Truncated dialog turn

- `TurnOutcome` gains `TRUNCATED = "truncated"`. Its meaning: the model
  stopped because it hit the length cap. `text` holds whatever answer was
  produced, which may be empty when reasoning consumed the whole cap.
- `Orchestrator.on_response_complete` records it through the existing
  `record_assistant(..., outcome=...)` path.
- The conversation history gets the assistant text and then a system note,
  following the existing `_INTERRUPTED_HISTORY_NOTE` pattern. The note is
  runtime dialog data, in Russian. Proposed text: «Предыдущий ответ обрезан:
  достигнут лимит длины генерации.»
- Mode 3:
  - **Pass 1 truncated.** The turn's outcome is `truncated`. Pass 2 still
    runs over whatever canvas text exists, or is skipped if the canvas is
    empty.
  - **Pass 2 truncated.** This is recorded as
    `metadata.spoken_derivative_truncated = true`, not as the outcome, for
    the same reason `spoken_derivative_interrupted` exists: the outcome
    describes `text`, and `text` is complete here.
- Journal UI: a new `journal_outcome_truncated` string in `strings.js` (EN and
  RU), rendered by the existing `_journalOutcomeDetail`. There is one label
  for both cases, with or without partial text: the text body shows which
  case it is.

## Code boundary

- `src/jarvis/core/config.py`: the `num_predict` default, validation, moved
  key, removal of `HistorySettings.reasoning_generation_reserve_tokens`.
- `src/jarvis/app.py`: `_history_limits_from_settings` takes the reserve from
  the dialog profiles; truncation handling in `on_response_complete` and
  `run_derivative_pass`; the history note.
- `src/jarvis/dialog/backend.py`, `src/jarvis/dialog/tool_presentation.py`:
  `done_reason` on `ResponseComplete`, and the warning.
- `src/jarvis/journal/events.py` (`TurnOutcome`),
  `src/jarvis/journal/recorder.py` (`spoken_derivative_truncated`).
- `src/jarvis/ui/status_console_ui/strings.js`, `app.js` if the outcome
  renderer needs the new key.
- `config.example.toml`, `PROJECT.md` (architecture section on generation
  profiles: the "Not moved" paragraph becomes the new rule; context budget
  defaults paragraph), `README.md` / `README.ru.md` if they name the reserve.
- Tests that construct `ContextBudgetLimits` or `HistorySettings` with the
  reserve, and fakes that construct `ResponseComplete`.
- Every `manual/` script that constructs `ResponseComplete` or reads
  `history.reasoning_generation_reserve_tokens`. They must be found with a
  pyright pass over `manual/` and `src/`, not by grep alone (lesson of the
  profiles card).

## Acceptance criteria

1. With no `[generation]` `num_predict` anywhere in config, every request
   kind's payload carries `options.num_predict = 16384`. Pinned per profile
   in `tests/test_generation_payloads.py`.
2. `[generation.dialog.off] num_predict = 2048` changes only the
   `dialog.off` payload.
3. `prompt_capacity_tokens + max(dialog num_predict) > num_ctx` is a
   `ConfigError` that names the profile. The default config passes exactly
   (49152 + 16384 = 65536).
4. `num_predict = 0` and `num_predict = -1` are `ConfigError`s in
   `[generation]` and in a profile.
5. `[history].reasoning_generation_reserve_tokens` raises the moved-key
   `ConfigError`.
6. A fake stream ending with `done_reason: "length"` produces:
   - a `ResponseComplete` with that value;
   - a journal record with `metadata.outcome = "truncated"`;
   - the history note after the assistant text.

   `"stop"` produces none of these. A stream with no `done` chunk gives
   `done_reason = None` and no truncation.
7. The same holds through the tool loop, using the final request's
   `done_reason`.
8. Mode 3 with pass 2 truncated records `spoken_derivative_truncated = true`
   and no outcome. Mode 3 with pass 1 truncated and empty text skips pass 2.
9. The Journal feed renders `journal_outcome_truncated` in both UI languages.
10. `python -m pytest`, `ruff check`, and `ruff format --check` are green. A
    pyright pass over `manual/` and `src/` shows no new call-signature or
    attribute errors compared with `main`.

## Human-run handoff

Written: `tasks/done/task-generation-num-predict-cap-handoff.md`.

This needs a live Ollama. Outline:

- A tiny cap (`[generation.dialog.off] num_predict = 30`) on a long question
  in text mode. Expect a cut answer, the truncated label in the Journal, and
  `done_reason: "length"` with `num_predict: 30` in the debug transcript.
  Then "Продолжи": the model should acknowledge the cut, which confirms the
  history note works.
- The same cap in text+voice mode, then a tiny cap on
  `[generation.spoken_derivative]`.
- A small cap at medium on a creative prompt with a formal constraint (the
  empty-answer case). Expect a truncated label with an empty body.
- Remove the overrides. Every exchange shows `num_predict: 16384`.
- `[generation.dialog.high] num_predict = 20000` fails at startup with the
  budget `ConfigError`.

## Out of scope

- The reason level-2 generation runs away on creative prompts with a formal
  constraint. That is its own open report
  (`2026-09-12-reasoning-level-2-returns-empty-answer-on-creative-form-constraints.md`).
  This card only bounds it and makes it visible.
- A wall-clock budget. The bug report raised it. Tokens are what Ollama can
  enforce, and seconds vary with prefill.
- Truncation outcomes for annotation, transcription, voice-intent, and
  warm-up. Their outputs on record are at most a few hundred tokens, so
  hitting 16384 there is itself a runaway: the backend warning covers it.
  Services keep their current outcomes.
- A spoken or sound-cue notice on truncation (see the open question).
- Recording the reasoning level and response mode per turn. That is the
  separate report `2026-09-12-journal-turn-does-not-record-response-mode-or-reasoning-level.md`.

## Open question for the owner

Should a truncated turn in a voice mode (2 or 3) be audible? For example, play
the existing `error` sound cue, or only when the answer is empty.
Recommendation: not in this card. A partial spoken answer ends audibly
mid-thought anyway. The empty case is the runaway, which after this card
lasts about 3 min at most and is labelled in the Journal. If it proves
confusing in use, add it separately.

## Implementation notes (2026-09-26)

Commits `cca2cd8` (cap and budget), `4b14316` (`done_reason`), `5df519c`
(truncated turns), plus the documentation and handoff step. Choices and
deviations from the design text above:

- The budget `ConfigError` names the table where the maximum is written, not
  only the profile: `GenerationSettings.dialog_generation_reserve()` returns a
  `DialogGenerationReserve(profile, tokens, table)`, and `table` is
  `generation.dialog.<level>` when the profile sets `num_predict` itself, or
  `generation` when it inherits. Naming a profile that does not contain the
  value would send the owner to the wrong table. With equal caps the first
  dialog profile in `DIALOG_PROFILE_BY_REASONING` order wins, which only
  matters for the message.
- `ResponseComplete.done_reason` is a required field with no default, so every
  constructor, including the fakes and the `manual/` scripts, had to state it;
  a default of `None` would have let a forgotten call site pass silently as
  "not truncated". `hit_length_cap` is a property on `ResponseComplete`.
- The length-cap warning lives in `OllamaBackend.iter_chat`, which both
  `chat()` and the tool loop (and every service) go through, so each request
  cut at the cap logs exactly once whatever its kind.
- Pass 2 learns whether it hit the cap from its dispatch's return value:
  `OllamaBackend.chat()` and `ToolAwareDialog.chat()` return the
  `ResponseComplete` they publish, and `_dispatch_backend_request()` returns
  it, or `None` when the request was interrupted, cancelled, or failed.
  Revised after owner review, before the handoff: the first version recorded
  every `ResponseComplete` in `_on_full_response_complete()` ahead of
  `claim_turn_end()` and read the last one after pass 2. `ResponseComplete`
  carries no request identity, so any other publisher during pass 2 would
  have flagged it falsely. `_on_full_response_complete()` is again a pure
  no-op when it loses the claim.
- Pass 2 is skipped only for a truncated empty canvas. A non-truncated empty
  canvas still runs pass 2, as before this card.
- A truncated empty answer still adds an empty assistant entry to the history,
  followed by the note. `on_response_complete()` already added the assistant
  entry unconditionally for a completed turn, and the truncation path keeps
  that. This differs from `record_aborted_turn()` (interrupted, failed,
  mode-switched), which adds the assistant entry only when text was
  streamed.
- `manual/manual_check_generation_profiles.py` now also prints each
  exchange's `done_reason` for the handoff.

