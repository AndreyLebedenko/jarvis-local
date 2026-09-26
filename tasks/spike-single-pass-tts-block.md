# Spike: single-pass Text + voice with a trailing `<tts>` block

**Status:** Draft, awaiting owner review. Not started.
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

Can mode 3 (Text + voice) produce its canvas and its spoken commentary in one
generation - the canvas first, then one trailing `<tts>...</tts>` block -
without a worse canvas, a worse or less faithful voice, and with an acceptable
tag failure rate, compared with today's two passes?

## Fixed design choices (owner, do not re-open in this spike)

- **The block goes last.** The voice is written after the canvas exists, so
  every canvas token is in context when the voice is generated. Voice-first is
  rejected: it trades grounding for latency.
- **Exactly one block.** Interleaved canvas/voice blocks stay in v2.1 as a
  possible, questionable later improvement. Not measured here.
- **Two-pass stays the fallback in any production design this spike might
  justify:** a missing, broken, or truncated block falls back to today's
  pass 2 over the canvas. The spike measures how often that would happen; it
  does not build it.

## What is honestly expected

The trailing block does not start speech earlier than the canvas finishes, so
the gain over two passes is the second request's prefill and start-up, not a
large latency win. The real benefits being tested are one generation instead
of two, and a canvas-and-voice pair produced by the same reasoning. The real
risk is the canvas: an instruction to also write a spoken version may change
the canvas itself. That is why both channels are judged, not only the voice.

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

## Arms

For every corpus prompt, reasoning level, and seed:

- **A (today's mode 3).** Pass 1 composed exactly as a production mode-3 first
  pass (system prompt plus the dialog profile's prompt for the level). Pass 2
  exactly as `run_derivative_pass` in `app.py`: the spoken-derivative contract
  as system message, the pass-1 canvas as user message, reasoning OFF.
- **B (single pass).** The same pass-1 composition plus one appended contract
  telling the model to finish the answer, then write one `<tts>...</tts>` block:
  a spoken commentary over the answer above, prose only, no Markdown, no new
  facts. Contract text is drafted with the harness and frozen before the run;
  it reuses the intent of today's spoken-derivative contract so that the arms
  differ in mechanism, not in what they ask the voice to be.

Reasoning levels: OFF and medium (level 2). Seeds: two fixed seeds, the same
for both arms. Sampling: production `[generation]` values for both arms.

## Corpus

About 16 Russian prompts, drafted by the agent and frozen after owner review,
before any run. Categories, two or three prompts each:

- a table is the natural answer;
- code;
- an exact formula or calculation;
- a list with caveats;
- references, links, names of sources;
- mixed Russian/English technical explanation;
- plain conversational question (checks that B does not damage easy answers);
- short factual question (checks that B does not pad a one-line answer).

## Measurements

Automated, by a deterministic grader (pure logic, CI-tested on fixtures):

- **Tag outcome per B generation**, one class each: well-formed (one block,
  closed, last, nothing but whitespace after it); missing; unclosed;
  text after the closing tag; more than one block; block inside a code fence;
  empty block; truncated (`done_reason = length`).
- **Voice hygiene** for both arms' voice text: Markdown markers, table pipes,
  code fences, raw URLs.
- **Timing** from request start: time to first voice token (A: pass 1 total
  plus pass 2 to first content token; B: first token inside `<tts>`); total
  wall time; summed `eval_count`; `done_reason` for every call.
- **Runaways:** empty visible answer or `done_reason = length`, per arm and
  level.

Human, blind, on seed 1 only (seed 2 feeds the automated measures):

- For each prompt and level, canvas A and canvas B shown as X and Y in a
  randomized order recorded by the harness: preference X / Y / equal, and a
  defect note if either has a factual or instruction-following error.
- The same for the two voice texts, plus a flag per voice for any claim not
  present in its canvas.
- After each pair, the reviewer's guess of which one is B. This measures
  whether blinding held (v1.9.2 lesson: its arms were guessable by length
  and structure).

Review is on text by default. Listening through TTS is optional for a subset
if the owner wants it; it is not required for a decision.

## Decision rule (proposed; owner confirms the numbers before the run, then frozen)

Per reasoning level, over the seed-1 pairs:

- **Go** - write a production story (single pass with pass-2 fallback) - if
  all hold: well-formed tag outcome in at least 95% of B generations (both
  seeds); canvas B loses in at most 25% of pairs (ties are not losses); voice
  B loses in at most 30% of pairs; voice claims absent from the canvas no more
  frequent in B than in A; B runaways no more frequent than A runaways.
- **Close** - record as a verified fact in `PROJECT.md`, like v1.9.2 - if
  canvas B loses in more than 40% of pairs at either level: the instruction
  damages the answer, and no tag reliability can buy that back.
- **Anything in between** goes to the owner with the numbers. No additional
  runs without a named hypothesis they would test.

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
  fixtures covering every tag outcome class above.
- Review sheet generator for the blind human pass.
- Self-sufficient human-run handoff per `CLAUDE.md` "Testing protocol"
  item 4.
- Results note; if the result is Go or Close, the verified fact goes into
  `PROJECT.md` and the raw study into `docs/experiments/`.

## Out of scope

- Any change under `src/jarvis`, including streaming parser, UI hiding of the
  block, TTS gating, journal storage. Those belong to a production story if
  the result is Go. For reference only: the canvas would map to `event.text`
  and the block to `metadata.spoken_derivative`, the shapes v1.9.0 and v1.9.1
  already store and index.
- Interleaved blocks, voice-first ordering, block ids and references (v2.1).
- The v1.9.x first-pass canvas prompt experiments. Arm B's contract is itself
  one "pass 1 knows a voice follows" variant, so this spike answers part of
  that question for B's framing only; the v1.9.x item stays as written.
