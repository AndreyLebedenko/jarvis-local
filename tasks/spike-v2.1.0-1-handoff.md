# Human-run handoff: personal-proxy spike v2.1.0-1 (combined transcribe-and-sanitize)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`
"Testing protocol"). Run by a human against live Ollama and the microphone;
the agent prepared it and stops. Card:
`tasks/spike-v2.1.0-1-combined-transcribe-sanitize.md`.

What this produces: a corpus of 44 recordings made through the production
capture path, raw generations for the three arms of the card, a report that
applies the card's frozen decision rule and states GO, CLOSE, or "owner", and
a separate report for block R (restoration of original values).

Automated counterpart already green: `python -m pytest` (includes the
`manual/tests/test_*personal_proxy*.py` files and
`manual/tests/test_manual_record_personal_proxy_corpus.py`).

Documentation debt: none. This handoff depends on no undocumented default;
every default it relies on is cited below with its source.

## Literal references used throughout

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs. Both harnesses read `config.toml` from the
  current directory (option `--config`, default `config.toml`).
- Model and endpoint: `[backend].model` and `[backend].endpoint` in
  `config.toml`. The code default of `model` is `gemma4:12b`
  (`BackendSettings` in `src/jarvis/core/config.py`). A `config.ui.toml` next
  to `config.toml` overrides it per key; the harness prints a NOTE when that
  file exists. The spike runs whatever model is effective and records its name,
  digest, and the Ollama version in `run_meta.json`.
- Transcription request shape: `[generation.transcription]` (options and
  `prompt`) in `config.toml`; when `prompt` is unset the harness uses
  `DEFAULT_TRANSCRIPTION_INSTRUCTION` (`src/jarvis/journal/transcription.py`).
  Reasoning is off for every call of the spike.
- Capture settings used by the recorder, all from `[vad]` (code defaults in
  `VadSettings`, `src/jarvis/core/config.py`; commented in `config.example.toml`):
  `threshold = 0.5`, `max_chunk_seconds = 30`, `min_chunk_seconds = 3.0`,
  `padding_noise_rms = 0.002`, `request_end_pause_seconds = 2.0`. The
  microphone is `[microphone].device` / `host_api` (both `""` = the system
  default input device, `MicrophoneSettings`).
- Values fixed in code (the citation lets you check the current value):
  - `SEEDS = (19210, 4243)` in `manual/personal_proxy/corpus.py`: every
    generation runs at both seeds.
  - `NUM_PREDICT = 2048` in `manual/personal_proxy/runner.py`: the runaway
    cap. A call that stops there counts as truncated.
  - `STAGE0_IDS` (12 utterance ids) in
    `manual/manual_check_personal_proxy_spike.py`.
- Frozen inputs, hashed into `run_meta.json` so that editing any of them after
  the run starts is refused: the corpus and the topics text
  (`manual/personal_proxy/corpus.py`, `manual/personal_proxy/spike_topics.txt`),
  and the prompts and schemas (`manual/personal_proxy/prompts.py`).
- Output directories, all gitignored and containing only invented data:
  `personal_proxy_corpus_wavs/` (recordings),
  `manual_check_personal_proxy_spike_out/` (main run),
  `manual_check_personal_proxy_restoration_out/` (block R).

## 0. Before anything

1. Jarvis must not be running (no `python -m jarvis`, no `Jarvis.cmd`):
   it would hold the microphone, and a second Ollama client would distort
   timing and the prompt-cache check below.
2. Ollama must be running and the effective model pulled. Check:

   ```
   ollama list
   ```

   The name from `[backend].model` must be listed.
3. `OLLAMA_NUM_PARALLEL` must not be set above 1 for the Ollama server.
4. Use a quiet room and the microphone you normally use with Jarvis.
5. Do not edit `config.toml`, `config.ui.toml`, or any file under `manual/`
   from step 2 until the last `score` step. The harness refuses to continue a
   run whose frozen inputs changed and names what changed. Do not delete
   `run_meta.json` to get around it; report it instead.

## 1. Review the corpus (you freeze it; about 10 minutes)

```
python -m manual.personal_proxy.corpus
```

It prints the 44 scripted utterances with their labeled sensitive spans, the
expected verdict, an estimated reading time, and the test topics text. Check:

- each text is something you can read aloud naturally;
- every labeled span is really sensitive in that sentence and nothing
  sensitive is left unlabeled;
- topic utterances are the ones the topics text says must be refused.

Send back any edit you want. Edits to the corpus invalidate nothing yet; after
you say "frozen", nobody edits it again. All identities in it are invented.

## 2. Record (about 20-30 minutes)

```
python -m manual.manual_record_personal_proxy_corpus
```

For each utterance the recorder shows the text. Press Enter, read the text
aloud at a normal pace, then stay silent. Expect `Captured N.N s.` after about
2 seconds of silence (`request_end_pause_seconds = 2.0`: the production
capture publishes an utterance only after that much silence).

- Read continuously. A pause inside the sentence shorter than 2.0 s is
  merged, but a longer one ends the take early. The recorder prints a NOTE
  when the take is much shorter or longer than expected.
- Numbers are written as words in the script; read them exactly as written.
- At the prompt: Enter accepts the take, `r` records it again, `p` plays it
  back, `q` quits. Accepted takes are kept; run the same command again to
  continue where you stopped.
- To redo specific utterances later:

  ```
  python -m manual.manual_record_personal_proxy_corpus --redo id_email --redo q_judge
  ```

Expected end: `Recorded N now, M already present (complete). Directory:
personal_proxy_corpus_wavs`. The directory then holds 44 `.wav` files and
`manifest.json`. The silence, noise, and no-media controls are generated by the
harness; you record nothing for them.

## 3. Stage 0: output-format probe (about 10 minutes)

```
python -m manual.manual_check_personal_proxy_spike --out manual_check_personal_proxy_spike_out stage0 --wavs personal_proxy_corpus_wavs
```

`--out` goes before the subcommand. It runs the combined user-turn arm on 12
utterances at 2 seeds with and without Ollama's constrained `format`, and
writes `stage0_decision.json` with the choice (`use_format` true only if the
constrained mode is strictly more valid).

Expected output: per generation one line such as
`c_user-id_email-s0: ok | combined=2.3s prompt_eval=... eval=... done=stop`,
then `valid N/24` for each mode and `Stage 0 decision: {...}`.

Report back if any line says `ERROR`, or if either mode is valid on fewer than
half of the generations.

## 4. Main run (estimate 30-60 minutes)

```
python -m manual.manual_check_personal_proxy_spike --out manual_check_personal_proxy_spike_out run --wavs personal_proxy_corpus_wavs
```

What it does: 282 generations (47 subjects x 2 seeds x 3 arms: the 44
utterances plus 3 controls), after an unrecorded warm-up. Before each
generation it sends a one-token request with an unrelated prompt so that
Ollama's prompt-prefix cache cannot favor an arm. Records land in
`manual_check_personal_proxy_spike_out/calls/`, one file per generation.

To resume after an interruption, run the same command again: finished
generations are skipped and a partial one is redone.

Checks while it runs:

- **Warm-up:** the first printed generation must take about as long as the
  following ones. If it is several times slower, stop and report both lines.
- **Cache:** for the same utterance and seed, the `c_user` and `c_system`
  lines show `prompt_eval=` of the same order (within roughly 10%). If one is
  only tens of tokens, Ollama served the prompt from its cache and the speed
  criterion is biased: stop and report both lines.
- `ERROR: ...` in a line means that generation failed and is recorded as an
  error; report the message if more than a handful appear.

Expected end: `Done in N min: ran 282, skipped 0, errored K. GPU share of the
model: 1.0`. A GPU share below 1.0 means the model was partly on the CPU;
report it, since it changes every timing.

## 5. Score and read the verdict

```
python -m manual.manual_check_personal_proxy_spike --out manual_check_personal_proxy_spike_out score --wavs personal_proxy_corpus_wavs
```

It prints the report and writes `report.md` into the output directory. Read:

- `Outcome:` is `GO`, `CLOSE`, or `OWNER`, from the card's frozen decision
  rule. `GO` names the chosen combined arm; `CLOSE` means the story re-plans
  to the two-step shape; `OWNER` means the numbers go to you.
- A line starting with `STOP CONDITION` means the baseline transcription step
  alone failed on more than 10% of generations. Do not act on the outcome;
  report it.
- The `FAIL` lines under each arm name the criteria that failed, with values.
- The "False refusals" section lists, per arm, the utterances refused although
  they should have been sent, split into those whose only content is the
  sensitive datum (defensible) and the rest. A refusal sends nothing, so an arm
  that refuses more looks safer on leaks; read the leak rate together with it.
  This section is reported only and is not part of the rule.

## 6. Block R: restoration (about 20 minutes)

```
python -m manual.manual_check_personal_proxy_restoration --out manual_check_personal_proxy_restoration_out run
python -m manual.manual_check_personal_proxy_restoration --out manual_check_personal_proxy_restoration_out review
```

`run` sends the 30 synthetic sentences at both seeds (60 calls, text only).
`review` writes `review-sheet.md` and `review-answers.toml` into the output
directory. Open the sheet; for each item it shows two sentences, X and Y, in a
random order. In the answers file set `x` and `y` of every item to `ok` if that
sentence is grammatically right (the case and form of the inserted values) or
`bad` if not. Then:

```
python -m manual.manual_check_personal_proxy_restoration --out manual_check_personal_proxy_restoration_out score
```

It refuses to score while any mark is empty. The end of its output states
`KEEP restoration through the model` or `NOT SUPPORTED` with the failed
conditions.

## 7. What to send back

- `manual_check_personal_proxy_spike_out/report.md` and `run_meta.json`;
- `manual_check_personal_proxy_restoration_out/report.md`;
- the console lines for any `ERROR`, the warm-up or cache checks, or a
  `STOP CONDITION`;
- anything you noticed while recording (a utterance you found hard to read, a
  take that kept being cut).

The agent then writes the results note and the `PROJECT.md` facts, and
re-plans the story according to the outcome. The raw `calls/` files stay on
your machine; they contain only invented data.
