# Human-run handoff B: doubt trigger on the production check stage (task v2.1.0-8)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by
a human: it loads Whisper (GPU) and calls the live local Ollama endpoint with
the recordings of spikes v2.1.0-1 and v2.1.0-9. The agent prepared it and ran
none of it.

What it answers: with the production transcript check (task v2.1.0-4) and
`[personal_proxy].doubt_min_listed = 1`, on the 60 labeled recordings of spike
v2.1.0-10 (`tasks/done/spike-v2.1.0-10-ask-policy.md`, section "Data"): (a) what
share of requests would be asked about, (b) how many of the real errors are
asked about, (c) for how many of the real errors a listed doubt quotes the wrong
fragment. It then applies the rule below, which was frozen before the run.

The frozen rule (task card `tasks/task-v2.1.0-8-confirmation-exchange.md`,
2026-10-22): keep `doubt_min_listed = 1` if the asked share is at most 0.27 (the
25% budget plus 2 points), at least 6 of the 7 real errors are asked about, and
at least 4 of 7 name the wrong fragment. Otherwise the numbers go to the owner;
the threshold is not tuned in a loop (stop condition of the story). The tool
applies exactly this; the constants are `MAX_ASKED_SHARE`, `MIN_COVERED`,
`MIN_NAMED` in `manual/personal_proxy/doubt_trigger.py`.

This handoff does not rely on `PROJECT.md` or the README for this stage; every
default it uses is cited below. It does rely on the speech-to-text stage of task
v2.1.0-3 and the check stage of task v2.1.0-4 being installed: step 1.

Automated counterpart already green: `python -m pytest` (includes
`manual/tests/test_manual_doubt_trigger.py`,
`tests/test_personal_proxy_transcript_check.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs (the one where `pip install -e .` was done,
  README.md "Manual installation"). Wording for the model-load options follows
  `manual/transcript-check-handoff.md`.
- The configuration is a file you create in step 2 and pass with `--config`; the
  tool reads nothing else, so your own `config.toml` does not matter. A missing
  key means the code default (`src/jarvis/core/config.py`; commented in
  `config.example.toml`). The tool refuses to run (exit code 2, nothing run) if
  `flash_attention`, `kv_cache_type` or `doubt_min_listed` differ from the values
  below, and it prints the effective values it uses.
- `[backend]` keys: `endpoint = "http://localhost:11434"` (default; change it in
  the file if your Ollama listens elsewhere), `read_timeout_seconds = 120.0`
  (default), and the load options `flash_attention` and `kv_cache_type`. Both are
  unset by default and are sent with every request as load options (not read from
  server environment variables). The spikes ran with `flash_attention = true` and
  `kv_cache_type = "q8_0"`, and the rule was frozen for those, so you must set
  them: step 2 does. `[backend].model` and `[backend].num_ctx` are not used by
  this stage.
- `[personal_proxy]` keys: `doubt_min_listed = 1` (default; the threshold under
  test, set explicitly in step 2 so that a changed default cannot move it),
  `check_model = "gemma4:12b"`, `check_num_ctx = 8192`, `check_temperature =
  0.618`, `check_top_p = 0.9`, `check_top_k = 50`, `check_min_p = 0.05`,
  `check_repeat_penalty = 1.025`, `stt_weak_word_probability = 0.5`,
  `stt_model = "large-v3-turbo"`, `stt_device = "cuda"`, `stt_language = "ru"`,
  `stt_min_speech_seconds = 0.3`. The speech threshold is `[vad].threshold = 0.5`.
- Constants of the stage, not settings: the judge runs at temperature 0 with
  seed 1 and both requests use `num_predict` 2048 (`check_requests.py` in
  `src/jarvis/personal_proxy/`); the rewrite guard's alphabet limit is
  `CYRILLIC_SHARE_DROP = 0.5` (`rewrite_guard.py`, same directory).
- The 60 recordings are the utterances that carry labeled spans: 30 of the first
  corpus (`CORPUS` in `manual/personal_proxy/corpus.py`, recordings in
  `personal_proxy_corpus_wavs/`) and 30 of the second corpus (`CORPUS_V2` in
  `manual/personal_proxy/corpus_v2.py`, recordings in
  `personal_proxy_corpus_v2_wavs/`). Both directories are gitignored and hold
  invented data only; each must have its `manifest.json` and every utterance of
  its corpus (the tool verifies this and stops otherwise). Options `--v1-wavs`
  and `--v2-wavs` name other directories.
- A real error is the spike's label rule `addresses_assembled` (`LabelRule` and
  `is_bad` in `manual/personal_proxy/confidence.py`; expected addresses in
  `manual/personal_proxy/address_labels.py`), judged on the checked text the
  production stage returns. "Names the wrong fragment" uses `WRONG_FRAGMENT_KEYS`
  in `manual/personal_proxy/ask_policy.py`: a listed doubt contains one of the
  keys of that recording, as a lowercase substring. These keys were written after
  the spike data was seen (stated in the spike); the run does not change them.
- A failed check counts as asked. For every fallback reason except
  `EMPTY_TRANSCRIPT` (`call_failed`, `empty_sample`, `unparseable_judge`,
  `invented_address`, `alphabet_switch`) the stage returns one doubt and
  `would_ask` true (`src/jarvis/personal_proxy/check/transcript_check.py`), so such a
  recording is in the asked share even though no real doubt was listed. A
  recording whose check fell back this way therefore raises the share; the tool
  prints no separate line for it, so read the per-recording doubts.
- Asked means `would_ask` of the checked transcript
  (`src/jarvis/personal_proxy/check/check_result.py`), which the stage derives from the
  number of listed doubts and `doubt_min_listed`.

## 1. Prerequisites

1. The speech stage works: `python -m pip install -r requirements-stt.txt` and
   `python setup_stt_model.py` were done once (steps 2 and 3 of section "1.
   Install and fetch the weights" of `manual/stt-stage-handoff.md`, with network
   access).
2. Ollama is running at `[backend].endpoint` and lists the check model: `ollama
   list` shows `gemma4:12b`. If it is missing: `ollama pull gemma4:12b` (about
   7.6 GB, network needed once). The tool checks this itself (`GET /api/tags`)
   before loading Whisper and stops with exit code 2 and a message if not.
3. Both recording directories exist (see "Literal references"). If you have not
   recorded them on this machine, stop and tell the owner: recording them is
   `manual/manual_record_personal_proxy_corpus.py` (option `--corpus v2` for the
   second) and is not part of this handoff.
4. Close Jarvis and any other GPU-heavy program. Whisper and the check model fit
   the GPU together (spike v2.1.0-6: about 12.7 GB of 16.3 GB).

## 2. Create the configuration file

Create `config.handoff-b.toml` in the repository root with exactly this content
(overwrite it if it exists; change `endpoint` only if your Ollama is elsewhere).
The file holds no secret, but it is local to your machine: `.gitignore` lists
`config.handoff-b.toml`, so it is never committed:

```
[backend]
endpoint = "http://localhost:11434"
flash_attention = true
kv_cache_type = "q8_0"

[personal_proxy]
doubt_min_listed = 1
```

## 3. Run

`python -m manual.manual_check_doubt_trigger --config config.handoff-b.toml run`

(`--config` goes before `run`.) It prints the effective settings, then per
recording one line: `error=` (the label), `asked=` (would_ask) and the quoted
doubts; a recording the speech guard rejects prints `NO SPEECH; not checked` and
is left out. Expect a few minutes: 60 checks of two Gemma calls each. The first
call includes the model reload at `check_num_ctx = 8192`.

At the end it prints the counts, the limits and the verdict:

- `keep`: all three numbers are inside the frozen rule; `doubt_min_listed = 1`
  stays.
- `numbers_to_owner`: at least one number is outside the rule. Do nothing else:
  do not change `doubt_min_listed` and run again.
- `not_comparable`: fewer or more than 60 recordings were checked, or the labels
  found a number of real errors other than 7 (for example a NO SPEECH line, or a
  different model answer). The rule is defined for 60 and 7, so the numbers go to
  the owner as they are. One re-run is acceptable only if a failure of the
  environment (Ollama stopped, a missing directory) caused it.

The model is not deterministic; one run is one sample. Report the run you got.

## What to report

The settings line, the whole final block (counts, limits, verdict), the list of
recordings with `error=True` and for each whether it was asked and its doubts,
every `NO SPEECH` line, and the wall-clock time of the run.
