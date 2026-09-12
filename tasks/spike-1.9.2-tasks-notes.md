# Review notes: v1.9.2 spike task cards

**Status:** Agent review of the first task-card set. Input for owner review, not
a decision record.
**Created:** 2026-09-12.
**Reviewed documents:** `task-v1.9.2-1-local-answer-revision-spike.md` (committed
in `cd03eed`) and `task-v1.9.2-2` through `-8` (uncommitted at review time).
**Companion file:** `story-v1.9.2-local-generation-critique-integration-notes.md`
holds findings 1-17 against the story drafts. Numbering continues here from 18
so a finding can be cited by number across both files.
**Boundary:** Review only. No card, protocol, fixture, or harness was changed.

## Overall assessment

The set is executable and the decomposition is right. A committed card 1 as the
single contract source, with thin gated slices that reference it rather than
restate it, is the correct shape for a spike whose live phases are human-run.
Arithmetic is internally consistent: 2 + 42 + 18 + 180 + 18 = 260 local calls and
1 + 20 + 36 + 12 + 144 + 20 = 233 cloud calls match their declared ceilings, and
the sheet counts (36 development, 12 injected, 144 held-out) match the arms.

Findings 18-20 are defects. 21-23 concern how the result will be read after the
fact. 24 is maintenance.

## External facts: verified

Both third-party claims in card 1's "Cloud endpoint and retention boundary" were
checked directly on 2026-09-12 and hold:

- `ollama.com/library/glm-5.3-flash` exists and lists exactly one tag,
  `glm-5.3-flash:cloud`, shown with a 1M context window and text+image modality.
- `ollama.com/privacy` states that request content is not stored beyond the time
  required to fulfill the request, that inputs and outputs are not used to train
  any AI models, and that collected device/usage metadata excludes prompt and
  response content.

The card characterizes the provider correctly. Re-verify at G0 rather than
citing this note: both pages can change, and the card's own rule is to confirm
access and version metadata in human-run preflight.

## Finding 18: card 4 calibrates the checker after the step that depends on it

Card 4's human-run steps run in this order: preflight probes, the 42-call
development batch with the framing choice made inside it, the injected
diagnostics using the already-selected revision, and only then GLM calibration
against the 20 preauthored sheets.

The framing choice requires knowing introduced material errors on development
outputs. Card 1 states the constraint plainly: calibrate GLM against the 20
human-scored sheets *before relying on its scores*. As ordered, one of two things
must happen, and neither is written down:

- a human scores the 36 development final sheets by hand, which is not in the
  resource envelope - "pilot choice 12" minutes cannot cover it; or
- GLM scores them while uncalibrated, contradicting card 1's own rule.

Calibration needs no local calls and no development output, since the 20 sheets
are preauthored. Move it ahead of the development batch, or state explicitly that
the framing comparison is human-scored and budget the minutes for it.

This is the failure mode the testing protocol's self-sufficiency rule exists for:
an executor following card 4 literally reaches step 2 and has to stop and ask.

## Finding 19: G2's decisive number has no stated denominator

`Introduced material/critical defects versus A or B: Zero` does not say whether
the count covers all 18 held-out cases or the 15 outside the correct-but-
suspicious category. The held-out set deliberately includes 3 cases of a category
whose purpose is to provoke exactly this damage, and card 1 and card 5 both warn
against reading the oversampled hard categories as an ordinary-user error rate.

If the zero is computed over all 18, the trap category becomes a hard veto on the
whole gate, and the gate will most likely fail for the reason the cards
themselves call unrepresentative. If it is computed over 15, that has to be
written down.

There is a third option the cards do not offer, and it looks better than either:
the stress category does not veto, it narrows the proposal - "qualifies except for
correct-but-suspicious inputs". Whichever is chosen, it must be fixed at G0,
because this single number decides the outcome (see finding 21).

## Finding 20: phase 5 has no response-mode filter, so it compares output contracts

Card 7 selects "text-only completed Journal turns", which constrains input
evidence, not output shape. A published answer's form depends on the response
mode in force at the time: `voice` produced a self-contained spoken answer,
`text` produced the canvas. Reusing a `voice`-mode answer as the draft and
revising it under the text output contract yields a "fix" consisting of
converting the answer into a canvas - a change with nothing to do with revision
quality, and one that will score as an improvement.

The mode is recoverable: the spoken derivative is stored in the same assistant
journal event with its metadata. Add a `text`-mode requirement to the exclusion
list, or record the mode and analyze those turns separately, and record the
reasoning level in force for each selected turn.

## Finding 21: the two G2 criteria differ in strictness while the table presents them alike

Three stable case wins out of 18 is a floor, not an effect size: five of the six
held-out categories carry a defect by construction, so a revision that rewrites
aggressively will repair three by luck. Zero introduced material or critical
defects across 36 answer instances is, by contrast, stringent.

A positive outcome will therefore be driven almost entirely by the absence of
damage rather than by demonstrated benefit. Card 1 partly guards this by limiting
any pass to a bounded text-slice proposal, but the report should be required to
state the observed win rate with its denominator *and* that the win threshold was
a floor. Otherwise "at least 3 stable wins" gets quoted later as evidence of
usefulness.

## Finding 22: baseline B will probably be degenerate, and that is a result

Card 1 handles the case where baseline A is already at high reasoning. It does
not anticipate the likelier outcome: `PROJECT.md:178` records that for this model
`high` matched `off` on faithfulness traps, and most held-out categories are
faithfulness traps. So B is likely to land on A's level of quality, the stronger
single-pass baseline will not be stronger, and "improvement over B" collapses
into the same test as improvement over A.

That is not a design flaw. It is an outcome the report should be ready to state
as a finding - a second, independent confirmation of v1.8.0-22 on a new task
class - rather than treat as a hurdle quietly cleared.

## Finding 23: the framing will probably be chosen by the tiebreak, not by evidence

Six development cases, one per category, one call per framing gives at most six
paired observations. The selection rule - fewer introduced material errors, then
more corrected defects, ties keep first-person - is deterministic and honestly
labeled exploratory, but at this sample size it will most likely resolve to the
tiebreak.

Finding 8 argued that framing, not settings, is the mechanism of the two-pass
strategy. If it is settled by default rather than measured, the report must say
so literally: framing selected by tiebreak, not tested. The alternative is to
spend a few additional development cases specifically on framing, which is the
only variable in this spike with a stated causal story.

## Finding 24: the G2 table is duplicated, and the seed list is not consolidated

Card 6 restates all eight G2 rows verbatim from card 1. Card 1 is already
committed, so any threshold adjustment at G0 has to change two cards plus the
machine-readable sidecar. Thresholds should live in card 1 and the sidecar only,
with card 6 referencing them.

Related: card 3 lists seed 19204 under "Contract details (from the spike card;
implement literally)", but card 1 mentions 19204 only in phase 4's audit text,
not in the phase-1 seed list. Not a conflict, but the sidecar should be the one
authoritative enumeration of seeds, and the cards should point at it.
