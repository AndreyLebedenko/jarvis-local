# Story v1.9.2: Local answer revision and review - CLOSED, UNREALISTIC

**Status:** Closed as unrealistic by the owner, 2026-09-12. Measured and
refuted, not deferred and not blocked. Do not re-open without evidence that
contradicts the numbers below.
**Evidence:** `docs/experiments/v1.9.2-rethink-probe/` - 70 local calls,
scripts, raw outputs.
**Planning history:** the original story text, the eight task cards
(`task-v1.9.2-1`, `-3`..`-9`), the spike protocol story, the staged reduction
proposal and its notes, the stage-0 sampling handoff and the stage-0 stop-rule
record were deleted from the working tree on closure. They remain in git
history at `eb24bf9` and earlier. They described an evaluation ladder built
before anyone measured whether it could run, and a handoff written as live
instructions for a protocol that no longer exists; left in `tasks/`, they
invite agents to take their frozen parameters as given.

## 1. What we thought

Jarvis runs a 12B model locally. A 12B model misreads a task, drops an explicit
constraint, asserts things it cannot support, botches arithmetic, omits a
caveat. So the owner already asks hard questions knowing one pass will not hold
them, and re-prompts by hand until it does.

The idea was to make that second look a mode: a toggle ("Rethink" /
"Самокритика") that, while on, always sends the finished draft back to the same
model for an independent check before the answer is published. Fix material
errors, leave correct answers alone. The ladder behind it was one pass, then two
(generation plus self-revision), then three (generation, critique, integration).

The bet underneath: a fresh context looking at a finished candidate catches what
the generating context missed, because it is not committed to the sentence it
just started.

## 2. What we checked

Fourteen prompts written for the purpose - ten analytical with checkable ground
truth and planted traps (percent asymmetry, a banned word, a factor-of-2 in a
KV-cache formula, ceiling division, a multi-step latency budget, a false
premise, an unknowable sub-question, two mutually exclusive requirement sets),
four creative with damage criteria declared before the run.

Production-shaped requests throughout: `gemma4:12b-it-q8_0`, the `[backend]`
sampling options unchanged, seed 19200, and the system prompt composed the way
a live text turn composes it.

Four arms, so the draft quality and the critic's reasoning level could be moved
independently:

| Arm | n | wall | tokens | defects repaired | damage |
| --- | --- | --- | --- | --- | --- |
| draft at level 2, single pass | 10 | 428 s | 22 084 | - | - |
| critique at level 2 over those drafts | 10 | 637 s | 32 800 | 0 of 1 | 0 |
| draft at reasoning OFF | 10 | 43 s | 2 150 | - | - |
| critique at OFF over the OFF drafts | 10 | 57 s | 2 699 | 0 of 6 | 0 |
| critique at level 2 over the OFF drafts | 10 | 847 s | 43 170 | 3 of 6 | 0 |

## 3. What turned out

**The second look was already happening.** `.jarvis/prompts/think-level-2.md`
specifies a self-critique protocol in so many words - "Phase B: Orthogonal
Self-Verification (The Devil's Advocate Protocol)" with an inversion test, an
edge-case stress test and a hostile-expert critique, plus "Phase C:
Anti-Sycophancy Gate". Reasoning level 2 *is* the independent pass, inside one
call, before anything is emitted. An external pass with the same weights over
the same evidence re-does that work and arrives at the same place: 10 of 10
unchanged, and it missed the single defect that was there.

**A single level-2 pass was far better than expected.** It answered 9.5 of 10
analytical prompts correctly, catching every planted trap but one. Seven of my
ten written-in-advance predictions were wrong, all of them pessimistic.

**The critic only works where the draft was cheapened, and only up to the same
ceiling.** Dropping the draft to reasoning OFF produced six real defects; a
level-2 critic diagnosed four and repaired three exactly. But every one of those
was a defect a single level-2 pass never made. Two cases came out *worse* than
one level-2 pass, and none came out better. The pipeline that repairs anything
costs 890 s and 45 320 tokens against 428 s and 22 084 for one level-2 pass:
twice the price for the same ceiling.

**Diagnosis and repair turned out to be separate abilities.** Both critics
produced a correct verdict and then handed back an answer still containing the
named defect. One critic wrote "Requirements (a), (b), and (c) are mutually
exclusive; the draft violates (a) by proposing an UPDATE" and returned a schema
that proposes exactly that UPDATE. Worth knowing if multi-pass prompting is ever
revisited; it does not revive the ladder, because the repairs it would unlock
are the ones a single level-2 pass already makes.

**The mechanism is safe.** Zero damage across all 42 critique calls: no correct
answer broken, no creative text flattened. Safety was never the problem.

## Therefore

Within what we have - one local model, one set of weights, the same evidence on
both passes - a second pass has no room to add value. It cannot exceed the
reasoning level it runs at, and raising that level is strictly cheaper than
running twice. So the feature is closed.

The one cell left unmeasured is a critic at level 3 over a level-2 draft, the
only variant where the critic's prompt genuinely differs. Both surviving defect
classes were failures of reasoning about system design, which level 2's Phase B
and the critique checklist both targeted and both missed, so the expectation is
that it does not clear the bar either. Untested, and not a reason to hold the
story open.

Errors of missing knowledge and misheard audio lie outside any same-evidence
second pass and were never in scope.

## Process lesson

The original protocol froze a sample size of 30, and stop-rule thresholds worded
"of 30", before anyone checked whether the eligible population could supply 30.
It could not: the pool yielded 4 dispatchable turns, 2 of them unassessable.
Verify that a population can supply a parameter before freezing a protocol that
references it. A throwaway script over the data costs minutes and would have
replaced the entire ladder.
