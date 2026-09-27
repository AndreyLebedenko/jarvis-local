# Human-run handoff: mode 3b spike (single pass with a trailing `<tts>` block)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`
"Testing protocol"). Run by a human against live Ollama; the agent prepared it
and stops. Card: `tasks/spike-single-pass-tts-block.md`.

What this produces: raw generations for every arm of the card, two blind
review sheets that you fill in by hand, and a report that applies the card's
frozen decision rule and states Go, Close, or "goes to the owner".

Automated counterpart already green: `python -m pytest` (includes
`manual/tests/test_manual_check_single_pass_tts.py`,
`manual/tests/test_single_pass_tts_grader.py`,
`manual/tests/test_single_pass_tts_review.py`,
`manual/tests/test_single_pass_tts_files.py`).

Documentation debt: none. This handoff depends on no undocumented default.

## Literal references used throughout

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs. The harness reads `config.toml` from the
  current directory (option `--config`, default `config.toml`) and the memory
  files from `[memory].root` / `self_file` / `memory_file` (defaults `memory`,
  `self.md`, `memory.md`, `config.example.toml` `[memory]`).
- Harness entry point: `python -m manual.manual_check_single_pass_tts`
  (`manual/manual_check_single_pass_tts.py`). Subcommands: `run`, `review`,
  `review-equalized`, `score`. `--out DIR` goes before the subcommand. The
  default is `manual_check_single_pass_tts_out` (`DEFAULT_OUT`), which is
  gitignored.
- Model and endpoint: `[backend].model` and `[backend].endpoint` in
  `config.toml`. The spike runs whatever model is configured there and records
  the name in `<out>/run_meta.json`. At the time of writing, the local
  `config.toml` names `gemma4:12b-it-q4_K_M`.
- Sampling: `[generation]` plus `[generation.dialog.off]`,
  `[generation.dialog.medium]` and `[generation.spoken_derivative]` in
  `config.toml`. They are used unchanged, except that the harness sets `seed`
  and `num_predict` on every call.
- Values fixed in code (the citation lets you check the current value):
  - `NUM_PREDICT = 8192` (`manual/manual_check_single_pass_tts.py`) is the
    runaway cap. A call that stops there counts as a runaway.
  - `SEEDS = (19200, 4242)` (`manual/single_pass_tts_corpus.py`).
  - `REVIEW_SEED = 19200` is the seed the blind review uses.
  - `FIXED_TURN_EPOCH` is 2026-09-27 11:00 UTC. The time line every turn
    carries is frozen to this value, so all arms see the same turn.
- The frozen inputs are `CORPUS` (16 prompts) and `B_CONTRACT`, both in
  `manual/single_pass_tts_corpus.py`. Their hash goes into `run_meta.json`, so
  editing them mid-run is refused.

## 0. Before the run

1. Jarvis must not be running (no `python -m jarvis`, no `Jarvis.cmd`), and
   nothing else may use Ollama during the run. Both would distort timing, and
   another client would also break the prefix-cache reset described in step 2.
2. Ollama must be running and the model pulled. Check with the command below;
   the name from `[backend].model` must be listed:

   ```
   ollama list
   ```

   Do not edit `config.toml` or the memory files between the first `run` and
   the last `score`. The harness refuses to continue a run whose settings,
   prompts, or memory changed, and names what changed.

## 1. Smoke run (about a minute)

```
python -m manual.manual_check_single_pass_tts --out manual_check_single_pass_tts_out/smoke run --levels off --prompts fact_capital
```

Expected output:
- For each generation, one line per measured call: `a_pass1`, `a_prod_pass2`
  and `b`, in either order of arm.
- Each call line shows `eval=`, `prompt_eval=` and `done=stop`.
- The run ends with a `Done in ... min.` line.

**The cache check (important):** within one level, `a_pass1` and `b` must show
a `prompt_eval=` of about the same size, in the hundreds of tokens or more.
`b` is slightly larger by the length of the contract. If either is
much smaller than the other (for example tens of tokens), Ollama served the
prompt from its cache and the speed criterion would be biased. In that case
stop and report the two lines instead of continuing. A likely cause is
`OLLAMA_NUM_PARALLEL` greater than 1.

The smoke directory is not used later; you may delete it.

## 2. Full run (estimate 1.5 to 3 hours)

```
python -m manual.manual_check_single_pass_tts run
```

What the run does:
- 64 generations: 2 levels x 16 prompts x 2 seeds.
- Before each arm it sends a one-token cache-reset request, which is not
  recorded.
- Records land in `manual_check_single_pass_tts_out/calls/`, written once a
  whole generation finishes.

To resume after an interruption, run the same command again. Finished
generations are skipped, and a partial one is discarded and redone. If a
`RunMetaMismatchError` names changed keys, something in step 0.2 changed. Do
not delete `run_meta.json` to get around it; report it instead.

Keep an eye on the cache check from step 1. It should hold on the full run
too.

## 3. Production review sitting (blind)

```
python -m manual.manual_check_single_pass_tts review
```

It writes these files into the output directory:
- `review-production-sheet.md`: 64 pairs, minus any that were auto-resolved,
  then a list of every A-prod and B voice.
- `review-production-answers.toml`: the file you fill in.
- `review-key.json` and `review-records.sha256`.

**Do not open `review-key.json`.** It unblinds the pairs.

Read the sheet and fill every value in the answers file:
- `verdict`: `"X"`, `"Y"` or `"="`.
- `guess_b`: `"X"` or `"Y"`, the side you believe is the single-pass arm.
- For each voice, `invented`: `"yes"` if it states any claim absent from the
  canvas shown with it, else `"no"`.

Judging is on text. Listening through TTS is optional and not required for the
decision.

Running `review` again never overwrites a filled answers file. It refuses if
the records changed since the sheet was made.

## 4. Equalized review sitting (only after step 3 is complete)

```
python -m manual.manual_check_single_pass_tts review-equalized
```

The command refuses until `review-production-answers.toml` is complete and
valid, and then lists every missing or invalid entry. Once it succeeds it
writes `review-equalized-sheet.md` and `review-equalized-answers.toml`, which
you fill in the same way.

This sitting exists separately because at medium it shows B's text a second
time. Seen together with the production sitting, that repetition would reveal
B. It explains the result and never changes the decision; the report accepts
it being skipped.

## 5. Score

```
python -m manual.manual_check_single_pass_tts score
```

This writes `manual_check_single_pass_tts_out/report.md`: the six criteria
per level with the measured values, thresholds and pass/fail; the decision
(GO, CLOSE, or OWNER); the equalized block; your guess accuracy, with a
possible-bias flag at 13 of 16 correct; and hygiene and cost per arm.

## What to report back

- `report.md` in full. Everything else stays in the output directory, and the
  agent reads it from there.
- Any cache-check anomaly from steps 1-2, and anything unusual in the console
  output: errors, very long calls, `done=length` lines.
