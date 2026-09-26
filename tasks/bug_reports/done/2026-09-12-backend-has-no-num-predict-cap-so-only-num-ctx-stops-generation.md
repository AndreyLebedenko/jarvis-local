# Bug report: `[backend]` sets no `num_predict`, so the only bound on a single turn is the context ceiling

Commit: `6431b97` (v1.9.2 closure). Noticed while running the Rethink probe
archived in `docs/experiments/v1.9.2-rethink-probe/`. Config observation, not
a code change.

**Status:** Closed 2026-09-26 by
`tasks/done/task-generation-num-predict-cap.md`; see "Resolution". Originally
filed as a missing safety bound, not a malfunction: a runaway generation
observed separately
(`tasks/bug_reports/2026-09-12-reasoning-level-2-returns-empty-answer-on-creative-form-constraints.md`)
was allowed to run for 22 minutes precisely because no bound existed.

## Symptoms

`num_predict` is one of `_OPTION_FIELDS` in `src/jarvis/dialog/backend.py`,
and `build_payload()` includes an option only when the corresponding setting
is not `None`. `config.toml`'s `[backend]` section does not set it, so no
`num_predict` reaches `/api/chat` and Ollama generates until the model stops
or the context is exhausted.

With `num_ctx = 65536` that upper bound is roughly 64k tokens for one turn.
Measured directly: one request produced `prompt_eval_count` 1693 +
`eval_count` 63843 = 65536 exactly, taking 1330 seconds. Ollama counts
thinking tokens against the same budget, so a reasoning-level turn can spend
the entire ceiling before emitting any answer.

Nothing warns, and nothing distinguishes "the model finished" from "the model
was cut off at the context wall".

## Suspected cause

Not a defect in code. `num_predict` is plumbed correctly and is simply unset,
which is Ollama's documented default of unlimited. The gap is that the
project has no stated position on how long a single local turn may run, so
the effective policy is whatever `num_ctx` happens to be - a value chosen for
context capacity, not for latency.

The two settings drifted into serving one purpose: raising `num_ctx` to fit
longer conversations silently raised the worst-case turn duration too.

## Temporary decision

None applied to the product. The probe used an environment variable
(`PROBE_NUM_PREDICT`) local to its own script, so the archived study could
finish; nothing in `src/jarvis` or `config.toml` was touched.

Deliberately not setting a cap yet, because picking the number is the whole
question and it needs the owner:

- Too low silently truncates legitimate long answers - and truncation is
  indistinguishable, at the seam, from a model that finished.
- Too high does not bound anything worth bounding.
- A cap sized for text-mode analysis is wrong for `text_voice`, where the
  spoken derivative is a second pass over the same turn.

Guessing a value and committing it would look like a fix while changing
every turn in the product.

## Future considerations and boundaries

- Whatever cap is chosen, hitting it must be a distinct, visible outcome.
  Ollama reports `done_reason` on the final chunk; the runtime does not
  currently surface it. A truncated answer that reads as a completed one is
  worse than no cap at all.
- Consider whether the bound belongs in `[backend]` as a hard `num_predict`
  or in the dialog layer as a wall-clock budget. Tokens and seconds are not
  interchangeable here: prefill dominates on large evidence, decode dominates
  on long answers, and the observed runaway was pure decode.
- Related but distinct: `read_timeout_seconds = 120.0` bounds *silence* from
  the endpoint, not total duration. A streaming runaway delivers a chunk well
  within every 120-second window, so that timeout never fires. Do not treat
  it as an existing bound.
- This report is only about the missing bound. The reason a runaway happened
  in the first place is the separate report named above and should not be
  closed by capping.

## Resolution (2026-09-26)

Fixed by `tasks/done/task-generation-num-predict-cap.md` (the owner chose the
number from the observed distribution recorded in that card):

- Every request carries `num_predict`. `[generation].num_predict` defaults to
  16384, the former `[history].reasoning_generation_reserve_tokens` value;
  profiles may override it. At ~87 tok/s the worst-case turn falls from about
  22 min to about 3 min. `num_predict <= 0` is a config error.
- The largest dialog-profile `num_predict` is now the history budget's
  generation reserve, validated against `[backend].num_ctx` together with
  `[history].prompt_capacity_tokens`, so raising `num_ctx` no longer silently
  raises the worst-case turn. The history reserve key is a moved key.
- Hitting the cap is a distinct, visible outcome: `ResponseComplete` carries
  `done_reason`, the backend logs a warning for any request cut at the cap,
  and a dialog turn cut at the cap is journaled as `outcome: truncated`,
  labelled in the Journal UI, and followed by a history note so the model
  does not read it as finished.

The wall-clock budget considered above was not added: tokens are what Ollama
enforces, and seconds vary with prefill. The runaway itself stays open in its
own report, named above; this fix bounds it and makes it visible, as this
report asked.
