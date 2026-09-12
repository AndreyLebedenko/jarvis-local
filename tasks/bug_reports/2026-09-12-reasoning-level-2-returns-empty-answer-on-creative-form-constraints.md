# Bug report: reasoning level 2 spends the whole generation budget thinking and returns an empty answer

Commit: `6431b97` (v1.9.2 closure). Observed on branch
`stage0-damage-probe` while running the Rethink probe archived in
`docs/experiments/v1.9.2-rethink-probe/`; no runtime code was involved or
changed.

**Status:** Open. Reproduced on two independent generation budgets, so this
is not a one-off. Not investigated further: it surfaced inside a study about
a different question and fixing it is outside that study's scope.

## Symptoms

With reasoning level 2 (`think: "medium"`, `.jarvis/prompts/think-level-2.md`
appended to the system prompt), a creative request carrying a formal
constraint makes the model generate until it runs out of budget entirely
inside the thinking block, then stop with **zero characters of answer
content**.

From the user's seat this is Jarvis burning the GPU and never replying. In
the uncapped case that was 22 minutes of silence.

Four of twelve creative calls at level 2 returned empty. Zero of thirty
analytical calls at level 2 returned empty, and zero of any call at reasoning
OFF. The affected artifacts are in `docs/experiments/v1.9.2-rethink-probe/out/`:
`c01-crit-medium-over-draft-off`, `c02-crit-medium-over-draft-off`,
`c02-draft-medium`, `c03-crit-medium-over-draft-medium`.

Sharpest reproduction, case `c02`, prompt "восьмистрочное стихотворение с
рифмовкой ABAB":

| Budget | Wall | Thinking | Answer |
| --- | --- | --- | --- |
| none (`num_ctx` 65536 is the only stop) | 1330 s | 159 887 chars, 63 843 tokens | 0 chars |
| `num_predict = 4000` | 79 s | 10 056 chars, 4 000 tokens | 0 chars |

In the uncapped run `prompt_eval_count` 1693 + `eval_count` 63843 = 65536
exactly, i.e. the generation ended by hitting the context ceiling, not by the
model deciding it was done.

The same `c02` prompt at reasoning OFF produced a correct eight-line poem with
a real ABAB scheme in 4 s.

## Suspected cause

`think-level-2.md` prescribes an explicit multi-phase self-verification
protocol - Phase B "Orthogonal Self-Verification" with an inversion test, an
edge-case stress test and a hostile-expert critique. On a task whose
constraint is mechanically checkable but not mechanically satisfiable in one
shot (count the syllables, check the rhyme scheme, try again), that protocol
appears to have no exit condition: each candidate fails its own check, which
triggers another round.

Analytical prompts terminate because their verification converges - the
arithmetic either checks out or does not. A rhyme scheme judged by the same
model that wrote it does not converge.

This is a hypothesis from the artifacts, not a diagnosis. The thinking traces
were captured only as character counts, not text, so the loop was not read
directly. Capturing one full trace is the obvious first step for anyone
picking this up.

## Temporary decision

None. Nothing was changed in the runtime or in `[prompts]`.

Considered and rejected for now:

- **Capping `num_predict` in `[backend]`.** This converts 22 minutes of
  silence into 79 seconds of silence. It bounds the damage and does not fix
  the defect, and it silently truncates legitimate long answers on every
  other turn. The cap is worth having anyway for a different reason and is
  filed separately as
  `2026-09-12-backend-has-no-num-predict-cap-so-only-num-ctx-stops-generation.md`;
  it must not be mistaken for a fix to this report.
- **Editing `think-level-2.md` to add a stopping rule.** Plausible, and
  cheap to try, but the prompt is user-authored and shapes every level-2 turn
  in the product. Changing it to chase a defect seen on four calls, without
  first reading a thinking trace, risks degrading the analytical behaviour
  that the same study measured as strong.
- **Blocking level 2 for creative requests.** There is no classifier for
  "creative", and inventing one to route around an unexplained loop is a
  larger and worse change than understanding the loop.

## Future considerations and boundaries

- Reproduce with the thinking text retained, not just its length, and read
  where the loop turns over. `docs/experiments/v1.9.2-rethink-probe/run_probe2.py`
  already collects `message.thinking`; it only discards the text.
- Check reasoning levels 1 and 3 on the same prompt. If level 3 does not loop,
  the cause is specific to level 2's phase protocol rather than to thinking in
  general.
- An empty answer must not reach the user as silence regardless of cause. The
  runtime currently has no "model produced no content" outcome distinct from a
  normal completion; whatever the fix, that distinction is worth having, and it
  belongs to whoever picks this up rather than to this report.
- Scope note: observed through a standalone script using the production
  payload builder and the production system-prompt composition, not through a
  live turn. A live turn adds a `time_context` system message and history,
  which were absent here. Confirming the loop through `main.py` is a
  prerequisite to calling it a product defect rather than a prompt defect.
