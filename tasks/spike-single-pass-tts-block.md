# Spike: mode 3b - single-pass Text + voice with a trailing `<tts>` block

**Status:** Approved (owner, 2026-09-26), including the decision rule.
Not started.
**Origin:** owner planning dialog, 2026-09-26. Pulls the "single-pass tagged
output" direction of roadmap v2.1 (`roadmap-v1.9-v2.0.md`, "v2.1 -
Canvas-guided voice") forward as a measured spike, in its simplest form only.
**Type:** investigation spike. No change under `src/jarvis`. Model runs are
human-run (live Ollama); the parser and grader are pure logic and CI-tested.
**Depends on:** `task-config-generation-profiles.md` landed, so the harness
reads production prompts from their new locations instead of being written
twice. Does not depend on the `num_predict` card: the harness carries its own
cap (see "Runaway guard").

## Question

Is a single generation - the canvas first, then one trailing `<tts>...</tts>`
block - worth offering as an additional response mode "3b" beside today's
two-pass mode 3? That requires three things at once: the canvas is not worse,
the voice is acceptably close, and the voice starts noticeably sooner.

## Framing: an additional mode, not a replacement (owner)

Two passes are more tunable: pass 2 is an independent request, so it can get
its own reasoning level, sampling, and cap (through the
`spoken_derivative` generation profile). In a single pass the voice inherits
whatever the canvas was generated with. So 3b is "faster, less finely
tunable", and mode 3 stays. This changes what the spike must show: not "B is
no worse than A everywhere", but "B's canvas is no worse, its voice is within
an agreed tolerance, and its speed gain is real".

## Fixed design choices (owner, do not re-open in this spike)

- **The block goes last.** The voice is written after the canvas exists, so
  every canvas token is in context when the voice is generated. Voice-first is
  rejected: it trades grounding for latency.
- **Exactly one block.** Interleaved canvas/voice blocks stay in v2.1 as a
  possible, questionable later improvement. Not measured here.
- **Pass 2 stays the fallback in any 3b design this spike might justify:** a
  missing, broken, or truncated block falls back to today's pass 2 over the
  canvas. The spike measures how often that would happen; it does not build
  it.

## What is honestly expected

At production settings pass 2 runs with reasoning OFF, and the voice text is
about the same number of tokens in both arms, generated at the same speed. B
saves only pass 2's prefill of the canvas and the second request's start-up.
The agent's estimate, before measurement, is that this is well under a second.
That is why the speed criterion below is a gate of equal rank with canvas
quality, not a side metric: if the gain is below the threshold, 3b has nothing
to offer even at equal quality.

## Known risks carried in from earlier findings

- **Tag compliance precedent.** v1.2.8 rejected an LLM-authored
  `<speak>`/`<lang>` contract because Gemma4 nested tags and left speakable text
  outside the final tag (`PROJECT.md`, "v1.2.8 speech-markup prompt contract
  is not stable enough yet"). That contract was fine-grained inline markup; a
  single trailing block is a much smaller demand, but it is not proven.
- **Level-2 runaway on form constraints.**
  `tasks/bug_reports/2026-09-12-reasoning-level-2-returns-empty-answer-on-creative-form-constraints.md`:
  at reasoning level 2 some prompts with a formal constraint spent the whole
  budget inside thinking and returned nothing. A mandatory trailing tag is a
  formal constraint. Count such outcomes per arm; do not treat them as noise.

## Arms and blocks

Reasoning levels: OFF and medium (level 2). Seeds: two fixed seeds, the same
for every arm. Sampling: production `[generation]` values unless stated.

- **A-prod (today's mode 3).** Pass 1 composed exactly as a production mode-3
  first pass (system prompt plus the dialog profile's prompt for the level).
  Pass 2 exactly as `run_derivative_pass` in `app.py`: the spoken-derivative
  contract as system message, the pass-1 canvas as user message, reasoning
  OFF, production sampling.
- **A-eq (pass 2 equalized to pass 1).** Same pass-1 output as A-prod - it is
  not regenerated - with pass 2 re-run at pass 1's reasoning level. Exists
  only at medium: at OFF both passes already share reasoning OFF and the same
  sampling, so A-eq at OFF is A-prod. The equalization is approximate by
  nature: B's voice follows one shared reasoning phase, while A-eq's pass 2
  reasons again over a finished canvas.
- **B (mode 3b).** The same pass-1 composition plus one appended contract
  telling the model to finish the answer, then write one `<tts>...</tts>`
  block: a spoken commentary over the answer above, prose only, no Markdown,
  no new facts. Contract text is drafted with the harness and frozen before
  the run; it reuses the intent of today's spoken-derivative contract so that
  the arms differ in mechanism, not in what they ask the voice to be.

Two blocks follow from this:

- **Production block** (decides): B against A-prod at OFF and medium.
- **Equalized block** (explains, does not decide): B against A-eq at medium,
  voice only. If B loses to A-prod on voice but not to A-eq, the gap comes
  from pass 2's parameters, not from single-pass generation.

A pass-2 variant with a different temperature is not included: there is no
tuned pass-2 value to test, and an arbitrary one would be a guess. If the
owner names a hypothesis (for example a colder pass 2 for faithfulness), it is
added as a named A variant before the run.

## Corpus

16 Russian prompts, drafted by the agent and frozen after owner review, before
any run. Categories, two each:

- a table is the natural answer;
- code;
- an exact formula or calculation;
- a list with caveats;
- references, links, names of sources;
- mixed Russian/English technical explanation;
- plain conversational question (checks that B does not damage easy answers);
- short factual question (checks that B does not pad a one-line answer).

Per level: 16 prompts x 2 seeds = 32 generations per arm.

## Measurements

Automated, by a deterministic grader (pure logic, CI-tested on fixtures):

- **Tag outcome per B generation**, one class each: well-formed (one block,
  closed, last, nothing but whitespace after it); missing; unclosed;
  text after the closing tag; more than one block; block inside a code fence;
  empty block; truncated (`done_reason = length`). Every class except
  well-formed is a tag failure.
- **Voice hygiene** for every arm's voice text: Markdown markers, table pipes,
  code fences, raw URLs. Reported, not a gate.
- **Time to first spoken sentence**, from the start of the turn's first
  request to the arrival of the token that completes the first sentence of the
  voice text (the first sentence terminator, the unit at which TTS starts
  speaking). A-prod: pass 1 in full plus pass 2 up to that token. B: up to that
  token inside the block. Also total wall time, summed `eval_count`, and
  `done_reason` for every call.
- **Runaway:** an empty visible answer or `done_reason = length`. For A, a
  runaway in either pass counts.

Human, blind, on seed 1 only (seed 2 feeds the automated measures). A pair is
one prompt at one level; the reviewer sees the two texts as X and Y in a
randomized order recorded by the harness and answers "X better", "Y better",
or "equal". "B lost" means the other arm was judged better after unblinding; a
tie is not a loss.

- Canvas pairs: B against A-prod, 16 per level. The canvas of A-eq is A-prod's,
  so there are no separate A-eq canvas pairs.
- Voice pairs: B against A-prod, 16 per level; B against A-eq, 16 at medium.
- Per voice, a flag for any claim not present in its own canvas ("invented
  claim").
- After each pair, the reviewer's guess of which text is B. Reported beside
  the result; a correct guess in 13 or more of 16 pairs is flagged as possible
  preference bias (v1.9.2 lesson: its arms were guessable by length and
  structure).

Review is on text by default. Listening through TTS is optional for a subset;
it is not required for a decision.

## Decision rule (owner-confirmed 2026-09-26; frozen, do not tune after the run)

Production block only. Counts are per level; "both levels" means OFF and
medium each satisfy the condition separately.

**Go** - write a production story for mode 3b (single pass with pass-2
fallback) - if all six hold at both levels:

1. Tag: at most 1 tag failure out of 32 B generations.
2. Canvas: B lost at most 4 of 16 canvas pairs.
3. Voice: B lost at most 6 of 16 voice pairs against A-prod.
4. Invented claims: the number of B voices flagged is not greater than the
   number of A-prod voices flagged (16 each).
5. Runaways: B runaways not greater than A-prod runaways (32 each).
6. Speed: the median, over the 32 matched (prompt, seed) generations, of
   A-prod's time to first spoken sentence minus B's is at least 1.0 s.

**Close** - record the result as a verified fact in `PROJECT.md`, as with
v1.9.2 - if either holds:

- canvas: B lost 7 or more of 16 canvas pairs at either level (the voice
  instruction damages the answer; nothing else can buy that back);
- speed: the median gain in criterion 6 is below 1.0 s at both levels (3b has
  nothing to offer, whatever its quality).

**Anything else** - including Go at one level only - goes to the owner with
the numbers. No additional runs without a named hypothesis they would test.

The equalized block never changes the decision; it is reported to explain it.

## Runaway guard

The harness sets its own `num_predict` for every call it makes, records
`done_reason`, and counts a truncation as a runaway, not as a finished answer.
The value is chosen when the harness is written, stated in the handoff, and
large enough that a truncation means a runaway rather than a long answer.

## Deliverables

- Frozen corpus and frozen B contract text (reviewed by the owner before the
  run).
- Harness under `manual/` (live Ollama; human-run) that writes raw outputs to
  a gitignored directory, plus the randomized X/Y key for blind review.
- Grader and tag parser with CI tests under `manual/tests/` on hand-written
  fixtures covering every tag outcome class and the first-sentence timing.
- Review sheet generator for the blind human pass.
- Self-sufficient human-run handoff per `CLAUDE.md` "Testing protocol"
  item 4.
- Results note; if the result is Go or Close, the verified fact goes into
  `PROJECT.md` and the raw study into `docs/experiments/`.

## Out of scope

- Any change under `src/jarvis`, including streaming parser, UI hiding of the
  block, TTS gating, journal storage, and how 3b would be selected among
  response modes. Those belong to a production story if the result is Go. For
  reference only: the canvas would map to `event.text` and the block to
  `metadata.spoken_derivative`, the shapes v1.9.0 and v1.9.1 already store
  and index.
- Interleaved blocks, voice-first ordering, block ids and references (v2.1).
- The v1.9.x first-pass canvas prompt experiments. Arm B's contract is itself
  one "pass 1 knows a voice follows" variant, so this spike answers part of
  that question for B's framing only; the v1.9.x item stays as written.
